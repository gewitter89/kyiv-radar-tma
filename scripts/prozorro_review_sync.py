"""Explicit, one-shot private auction review sync. No public output or deployment."""
import argparse
import json
import os
import stat
from contextlib import contextmanager

import fcntl
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .prozorro_incremental_scan import scan
from .prozorro_probe import read_page
from .prozorro_review_cache import apply_page, review_candidates, private_directory


@contextmanager
def exclusive_sync(directory):
    directory = private_directory(directory)
    path = directory / "auction-sync.lock"
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_nlink != 1 or info.st_mode & 0o077):
            raise ValueError("Unsafe sync lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another auction sync is running") from None
        yield directory
    finally:
        os.close(fd)


def sync_once(directory, *, now, request_fn=read_page):
    """Refresh a bounded recent slice, not a complete catalog or persistent cursor."""
    def consume(rows):
        apply_page(directory, rows, observed_at=now, now=now)

    with exclusive_sync(directory) as directory:
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
