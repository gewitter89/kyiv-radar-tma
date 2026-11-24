"""Offline auction read-model gate. No API, I/O, approval writer or publication.

Only trusted server-side callers may supply rights and approvals. Never accept
these objects from a browser or from a source provider. Default is disabled.
"""
import hashlib
import json
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from .prozorro_auction_candidates import AUCTION_ID, _aware, _utc, MAX_FRESHNESS

FIELDS = ("auction_id", "source_url", "kind", "city", "asset_class",
          "starting_bid_uah", "vat_included", "bidding_ends_at", "source")
SCOPE = "prozorro_auction_metadata_v1"
MAX_ITEMS = 2000
MAX_APPROVAL_AGE = timedelta(days=7)


def normalized_fields(row):
    key = row["auction_id"]
    if not isinstance(key, str) or not AUCTION_ID.fullmatch(key):
        raise ValueError("Invalid ID")
    url = "https://prozorro.sale/auction/" + key + "/"
    if (row["source_url"] != url or row["source"] != "prozorro_sale"
            or row["kind"] != "sale_auction" or row["city"] != "Київ"
            or row["asset_class"] != "apartment_classified"):
        raise ValueError("Unexpected source or kind")
    raw = row["starting_bid_uah"]
    if not isinstance(raw, str) or len(raw) > 24:
        raise ValueError("Invalid price")
    amount = Decimal(raw)
    if (not amount.is_finite() or not 0 < amount <= Decimal("1000000000000")
            or raw != format(amount, ".2f")):
        raise ValueError("Invalid price")
    if type(row["vat_included"]) is not bool:
        raise ValueError("Invalid VAT")
    end = _utc(row["bidding_ends_at"])
    out = {k: row[k] for k in FIELDS}
    out["bidding_ends_at"] = end.isoformat()
    return out


def fingerprint(row):
    return hashlib.sha256(json.dumps(normalized_fields(row), sort_keys=True,
                                      ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


def project(candidates, approvals, rights, *, now, enabled=False):
    """Return staging-only whitelist; errors/missing evidence fail closed.

    Approvals are per ID and exact content fingerprint, linked to reviewed
    rights evidence. A fresh observation alone cannot grant approval.
    This is not an authorization store or a production endpoint.
    """
    if enabled is not True:
        return []
    now = _aware(now)
    try:
        if not isinstance(rights, dict) or rights.get("status") != "approved" or rights.get("scope") != SCOPE:
            return []
        evidence = rights["evidence_id"]
        if not isinstance(evidence, str) or not 1 <= len(evidence) <= 128:
            return []
        rights_from, rights_until = _utc(rights["valid_from"]), _utc(rights["valid_until"])
        if not rights_from <= now < rights_until:
            return []
        if not isinstance(candidates, list) or len(candidates) > MAX_ITEMS or not isinstance(approvals, dict) or len(approvals) > MAX_ITEMS:
            return []
        ids = [r["auction_id"] for r in candidates]
        if any(not isinstance(k, str) for k in ids) or len(set(ids)) != len(ids):
            return []
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return []
    result = []
    for row in candidates:
        try:
            if row.get("review_status") != "pending_review" or row.get("publication_allowed") is not False:
                continue
            fields = normalized_fields(row)
            observed, end = _utc(row["observed_at"]), _utc(fields["bidding_ends_at"])
            if not timedelta(0) <= now-observed < MAX_FRESHNESS or end <= now:
                continue
            approval = approvals.get(fields["auction_id"])
            if not isinstance(approval, dict) or approval.get("status") != "approved":
                continue
            if approval.get("rights_evidence_id") != evidence or approval.get("fingerprint") != fingerprint(row):
                continue
            approved, expires = _utc(approval["approved_at"]), _utc(approval["valid_until"])
            if not rights_from <= approved <= now < expires or now-approved >= MAX_APPROVAL_AGE:
                continue
            valid = min(observed+MAX_FRESHNESS, end, rights_until, expires, approved+MAX_APPROVAL_AGE)
            if valid <= now:
                continue
            result.append(dict(fields, observed_at=observed.isoformat(), valid_until=valid.isoformat()))
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError, InvalidOperation):
            continue
    return result
