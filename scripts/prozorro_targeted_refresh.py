"""Bounded targeted discovery and per-auction revalidation for private review."""
import argparse
import json
from datetime import datetime, timezone

from .prozorro_auction_candidates import AUCTION_ID, METHODS, _aware, _utc
from .prozorro_probe import read_page, MAX_BYTES
from .prozorro_review_cache import apply_page, review_candidates, private_directory, recheck_ids
from .prozorro_review_sync import exclusive_sync

BASE = "https://procedure.prozorro.sale/api/search/procedures/"
MAX_RECHECK = 5
LIMIT = 10


def _json(url, request_fn):
    raw = request_fn(url)
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ValueError("Invalid response size")
    return json.loads(raw)


def _validate(row, now):
    if not isinstance(row, dict):
        raise ValueError("Unexpected procedure shape")
    stamp = _utc(row.get("dateModified"))
    if stamp > now:
        raise ValueError("Future modification")
    return row


def discover(*, now, request_fn=read_page):
    """Only two documented selling methods, one bounded page each."""
    now = _aware(now)
    rows = []
    for method in METHODS:
        page = _json(BASE+"bySellingMethod/"+method+"?limit="+str(LIMIT), request_fn)
        if not isinstance(page, list) or len(page) > LIMIT:
            raise ValueError("Unexpected selling-method page")
        for row in page:
            _validate(row, now)
            if row.get("sellingMethod") != method:
                raise ValueError("Unexpected selling method")
            rows.append(row)
    return rows


def recheck(auction_id, *, now, request_fn=read_page):
    if not isinstance(auction_id, str) or not AUCTION_ID.fullmatch(auction_id):
        raise ValueError("Invalid auction ID")
    row = _validate(_json(BASE+"byAuctionId/"+auction_id, request_fn), _aware(now))
    if row.get("auctionId") != auction_id:
        raise ValueError("Unexpected auction identity")
    return row


def refresh(directory, *, now, request_fn=read_page):
    """Atomic bounded private refresh; no claim of full discovery or coverage."""
    now = _aware(now)
    with exclusive_sync(directory) as directory:
        # Oldest retained entries first, even if hidden due to stale observation.
        ids = recheck_ids(directory, now=now, limit=MAX_RECHECK)
        rows = discover(now=now, request_fn=request_fn)
        rows.extend(recheck(key, now=now, request_fn=request_fn) for key in ids)
        apply_page(directory, rows, observed_at=now, now=now)
        return {"discovery_requests": len(METHODS), "recheck_requests": len(ids),
                "procedures_seen": len(rows),
                "private_review_count": len(review_candidates(directory, now=now)),
                "coverage_complete": False, "publications": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-dir", required=True)
    parser.add_argument("--live-private-review", action="store_true")
    args = parser.parse_args()
    if not args.live_private_review:
        parser.error("Explicit opt-in required")
    try:
        print(json.dumps(refresh(private_directory(args.private_dir), now=datetime.now(timezone.utc))))
    except Exception:
        parser.exit(1, "Targeted refresh failed; no public output.\n")


if __name__ == "__main__":
    main()
