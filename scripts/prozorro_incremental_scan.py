"""Bounded incremental feed diagnostic. No persistence, publication or full-sync claim."""
import argparse
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

try:
    from .prozorro_probe import BASE, MAX_BYTES, read_page
    from .prozorro_auction_candidates import candidate, _aware, _utc
except ImportError:
    from prozorro_probe import BASE, MAX_BYTES, read_page
    from prozorro_auction_candidates import candidate, _aware, _utc


def scan(*, since, now, limit=10, pages=3, request_fn=read_page, consume_batch=None):
    now, cursor = _aware(now), _aware(since)
    if not timedelta(0) <= now - cursor <= timedelta(days=1):
        raise ValueError("Recent window required")
    if type(limit) is not int or not 2 <= limit <= 10:
        raise ValueError("Limit must be 2–10")
    if type(pages) is not int or not 1 <= pages <= 3:
        raise ValueError("At most three requests")
    seen = {}
    batch = []  # Bounded transient payloads; never logged or saved as raw JSON.
    requests = count = 0
    stop = "page_budget"
    for _ in range(pages):
        # Preserve the exact timestamp; never add epsilon to skip equal dates.
        url = BASE + quote(cursor.isoformat(timespec="microseconds").replace("+00:00", "Z"), safe="") + "?limit=" + str(limit)
        raw = request_fn(url)
        requests += 1
        if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
            raise ValueError("Invalid response")
        rows = json.loads(raw)
        if not isinstance(rows, list) or len(rows) > limit:
            raise ValueError("Unexpected page")
        stamps = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Unexpected row")
            stamp = _utc(row.get("dateModified"))
            if stamp < cursor or stamp > now + timedelta(minutes=1):
                raise ValueError("Unexpected feed timestamp")
            stamps.append(stamp)
        if stamps != sorted(stamps):
            raise ValueError("Unordered feed")
        count += len(rows)
        if consume_batch is not None:
            batch.extend(rows)
        for row, stamp in zip(rows, stamps):
            key = row.get("auctionId")
            # Only canonical public IDs are held transiently; never log them.
            if not isinstance(key, str) or len(key) > 64:
                continue
            result = candidate(row, observed_at=now, now=now)
            if key in seen and seen[key][0] == stamp:
                # Contradictory same-timestamp versions must fail closed.
                if seen[key][1] != result:
                    seen[key] = (stamp, None)
            elif key not in seen or stamp > seen[key][0]:
                seen[key] = (stamp, result)
        if len(rows) < limit:
            stop = "short_page"
            break
        if stamps[-1] <= cursor:
            stop = "cursor_stalled"
            break
        cursor = stamps[-1]
    if consume_batch is not None:
        # Only commit after every requested page has passed validation.
        consume_batch(batch)
    return {"requests": requests, "procedures_seen": count,
            "unique_review_candidates": sum(v[1] is not None for v in seen.values()),
            "stop_reason": stop, "coverage_complete": False,
            "publications": 0, "raw_records_saved": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-read-only", action="store_true")
    args = parser.parse_args()
    if not args.live_read_only:
        parser.error("Explicit opt-in required")
    now = datetime.now(timezone.utc)
    try:
        print(json.dumps(scan(since=now-timedelta(hours=1), now=now)))
    except Exception:
        parser.exit(1, "Bounded incremental diagnostic failed; no data saved.\n")


if __name__ == "__main__":
    main()
