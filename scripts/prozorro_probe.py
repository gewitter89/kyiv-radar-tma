"""Bounded, opt-in, read-only one-page CBD3 probe. No storage or publication."""
import argparse
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

try:
    from .prozorro_auction_candidates import candidate
except ImportError:
    from prozorro_auction_candidates import candidate

BASE = "https://procedure.prozorro.sale/api/search/byDateModified/"
MAX_BYTES = 4 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_page(url):
    request = Request(url, headers={"Accept": "application/json",
                                    "User-Agent": "KyivRadar-OpenDataPilot/0.1"})
    with build_opener(NoRedirect()).open(request, timeout=15) as response:
        if response.status != 200 or response.headers.get_content_type() != "application/json":
            raise ValueError("Unexpected API response")
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Response too large")
    return raw


def probe(*, since, now, limit=10, request_fn=read_page):
    if not isinstance(since, datetime) or not isinstance(now, datetime):
        raise ValueError("Datetime required")
    if since.utcoffset() is None or now.utcoffset() is None:
        raise ValueError("Timezone required")
    since, now = since.astimezone(timezone.utc), now.astimezone(timezone.utc)
    if not timedelta(0) <= now - since <= timedelta(days=1):
        raise ValueError("Only a recent one-day probe is permitted")
    if type(limit) is not int or not 1 <= limit <= 10:
        raise ValueError("Limit must be 1–10")
    url = BASE + quote(since.isoformat(timespec="milliseconds").replace("+00:00", "Z"), safe="") + "?limit=" + str(limit)
    raw = request_fn(url)
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ValueError("Invalid or oversized response")
    try:
        rows = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError("Invalid JSON") from None
    # Official documentation describes a list of full procedure objects.
    # Do not silently guess at an unfamiliar response envelope.
    if not isinstance(rows, list) or len(rows) > limit or any(not isinstance(r, dict) for r in rows):
        raise ValueError("Unexpected procedure page shape")
    seen = set()
    for row in rows:
        result = candidate(row, observed_at=now, now=now)
        if result is not None:
            seen.add(result["auction_id"])
    return {"requests": 1, "procedures_seen": len(rows),
            "unique_review_candidates": len(seen),
            "publications": 0, "raw_records_saved": 0,
            "coverage_complete": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-read-only", action="store_true")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    if not args.live_read_only:
        parser.error("Explicit --live-read-only required")
    now = datetime.now(timezone.utc)
    try:
        print(json.dumps(probe(since=now-timedelta(hours=1), now=now, limit=args.limit)))
    except Exception:
        # Never print remote response text, metadata, or request details.
        parser.exit(1, "Open-data probe failed; no data published or saved.\n")


if __name__ == "__main__":
    main()
