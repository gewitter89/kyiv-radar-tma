"""One public procedure schema check, with no raw response persistence or publication."""
import argparse
import json
import re
from datetime import datetime, timezone
from .prozorro_probe import read_page, MAX_BYTES
from .prozorro_auction_candidates import candidate

BASE = "https://procedure.prozorro.sale/api/procedures/"
ID = re.compile(r"[0-9a-f]{24}")
AUCTION = re.compile(r"(?:ALE001|CSE001)-UA-[0-9]{8}-[0-9]{5}")


def inspect(*, procedure_id, auction_id, request_fn=read_page, now=None):
    if not isinstance(procedure_id, str) or not ID.fullmatch(procedure_id):
        raise ValueError("Invalid procedure ID")
    if not isinstance(auction_id, str) or not AUCTION.fullmatch(auction_id):
        raise ValueError("Invalid auction ID")
    raw = request_fn(BASE + procedure_id)
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ValueError("Invalid response")
    row = json.loads(raw)
    if not isinstance(row, dict) or row.get("auctionId") != auction_id:
        raise ValueError("Unexpected procedure identity or shape")
    if row.get("_protected", False) is not False or row.get("_protect_level") or row.get("mode", "real") != "real":
        return {"protected_or_test": True, "publications": 0}
    items = row.get("items")
    single = isinstance(items, list) and len(items) == 1 and isinstance(items[0], dict)
    item = items[0] if single else {}
    classification = item.get("classification")
    address = item.get("address")
    value = row.get("value")
    period = row.get("tenderPeriod")
    now = now or datetime.now(timezone.utc)
    return {
        "identity_confirmed": True,
        "ale_method": row.get("sellingMethod") == "alienation-english",
        "active_tendering": row.get("status") == "active_tendering",
        "single_item": single,
        "cav_apartment": isinstance(classification, dict) and classification.get("scheme") == "CAV" and classification.get("id") == "04111000-9",
        "kyiv_locality": isinstance(address, dict) and address.get("locality") in ("Київ", "м. Київ"),
        "ukrainian_country": isinstance(address, dict) and address.get("countryName") in ("Україна", "Ukraine"),
        "uah": isinstance(value, dict) and value.get("currency") == "UAH",
        "vat_boolean": isinstance(value, dict) and type(value.get("valueAddedTaxIncluded")) is bool,
        "tender_window_present": isinstance(period, dict) and all(isinstance(period.get(k), str) for k in ("startDate", "endDate")),
        "current_adapter_accepts": candidate(row, observed_at=now, now=now) is not None,
        "publications": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--procedure-id", required=True)
    parser.add_argument("--auction-id", required=True)
    parser.add_argument("--live-read-only", action="store_true")
    args = parser.parse_args()
    if not args.live_read_only:
        parser.error("Explicit opt-in required")
    try:
        print(json.dumps(inspect(procedure_id=args.procedure_id, auction_id=args.auction_id)))
    except Exception:
        parser.exit(1, "Targeted schema check failed; no raw data retained.\n")


if __name__ == "__main__":
    main()
