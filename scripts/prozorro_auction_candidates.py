"""Experimental offline Prozorro.Sale CBD3 auction candidate normalizer.

No networking, storage, publication, ordinary listing conversion or bidding.
Input: a single procedure object; schema contract still needs live API QA.
Only a narrow sale-auction subset is accepted; all output requires review.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import re

METHODS = {"commercialSell-english": "CSE001"}
APARTMENT_CODES = {"04111000-9"}
MAX_FRESHNESS = timedelta(hours=1)


def _utc(value):
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("Invalid timestamp")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("Timezone required")
    return dt.astimezone(timezone.utc)


def _aware(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Aware datetime required")
    return value.astimezone(timezone.utc)


def candidate(procedure, *, observed_at, now):
    """Return only whitelisted auction metadata, or None if ineligible.

    observed_at must come from a trusted fetcher, not the provider payload.
    No live fetcher or public consumer exists in this prototype.
    """
    now, observed_at = _aware(now), _aware(observed_at)
    if not timedelta(0) <= now - observed_at <= MAX_FRESHNESS:
        return None
    try:
        method = procedure["sellingMethod"]
        prefix = METHODS.get(method)
        auction_id = procedure["auctionId"]
        if not prefix or not isinstance(auction_id, str) or not re.fullmatch(
            prefix + r"-UA-[0-9]{8}-[0-9]{5}", auction_id
        ):
            return None
        if procedure["status"] != "active_tendering":
            return None
        start = _utc(procedure["tenderPeriod"]["startDate"])
        end = _utc(procedure["tenderPeriod"]["endDate"])
        if not start <= now < end:
            return None
        items = procedure["items"]
        if not isinstance(items, list) or len(items) != 1:
            return None
        item = items[0]
        classification = item["classification"]
        if classification["scheme"] != "CAV" or classification["id"] not in APARTMENT_CODES:
            return None
        address = item["address"]
        if (address["countryName"] not in ("Україна", "Ukraine")
            or address["locality"] not in ("Київ", "м. Київ")
            or address["region"] not in ("Київ", "м. Київ", "Київська область")):
            return None
        value = procedure["value"]
        if value["currency"] != "UAH" or type(value["valueAddedTaxIncluded"]) is not bool:
            return None
        raw = value["amount"]
        if type(raw) not in (int, float, str) or len(str(raw)) > 24:
            return None
        amount = Decimal(str(raw))
        if not amount.is_finite() or not 0 < amount <= Decimal("1000000000000"):
            return None
        if amount != amount.quantize(Decimal("0.01")):
            return None
        return {
            "source": "prozorro_sale",
            "auction_id": auction_id,
            "source_url": "https://prozorro.sale/auction/" + auction_id + "/",
            "kind": "sale_auction",
            "city": "Київ",
            "asset_class": "apartment_classified",
            "starting_bid_uah": format(amount, ".2f"),
            "vat_included": value["valueAddedTaxIncluded"],
            "bidding_ends_at": end.isoformat(),
            "observed_at": observed_at.isoformat(),
            "review_status": "pending_review",
            "publication_allowed": False,
        }
    except (KeyError, TypeError, ValueError, AttributeError, InvalidOperation, OverflowError):
        return None
