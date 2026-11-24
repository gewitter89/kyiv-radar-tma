"""Explicit, one-shot private auction review sync. No public output or deployment."""
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .prozorro_incremental_scan import scan
from .prozorro_probe import read_page
from .prozorro_review_cache import apply_page, review_candidates


def sync_once(directory, *, now, request_fn=read_page):
    """Refresh a bounded recent slice, not a complete catalog or persistent cursor."""
    def consume(rows):
        apply_page(directory, rows, observed_at=now, now=now)

    report = scan(since=now-timedelta(hours=1), now=now,
                  request_fn=request_fn, consume_batch=consume)
    report["private_review_count"] = len(review_candidates(directory, now=now))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-private-review", action="store_true")
    parser.add_argument("--private-dir", type=Path, required=True)
    args = parser.parse_args()
    if not args.live_private_review:
        parser.error("Explicit --live-private-review required")
    try:
        report = sync_once(args.private_dir, now=datetime.now(timezone.utc))
    except Exception:
        parser.exit(1, "Private review sync failed; inspect locally. No publication.\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
