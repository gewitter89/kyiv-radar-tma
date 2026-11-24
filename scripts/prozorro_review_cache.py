"""Private, offline review cache for the auction pilot; NOT a publication source.

Trusted operator/fetcher must supply complete observed pages. No CLI, scheduling,
networking, raw payload persistence or integration with ordinary listings.
"""
import json
import os
import sqlite3
import stat
from datetime import timedelta
from pathlib import Path

from .prozorro_auction_candidates import candidate, _aware, _utc, MAX_FRESHNESS, AUCTION_ID

ROOT = Path(__file__).resolve().parents[1]
ID = AUCTION_ID
MAX_ROWS = 30
MAX_CACHE_ROWS = 2000
MAX_DB_BYTES = 16 * 1024 * 1024
RETAIN = timedelta(days=2)
SCHEMA = """CREATE TABLE IF NOT EXISTS auction_review (
    auction_id TEXT PRIMARY KEY,
    modified TEXT NOT NULL,
    observed TEXT NOT NULL,
    payload TEXT
)"""


def _stamp(dt):
    return _aware(dt).isoformat(timespec="microseconds")


def private_directory(directory):
    # Only a dedicated, pre-existing private directory, never the public repo.
    directory = Path(directory)
    if directory.is_symlink():
        raise ValueError("Private directory required")
    directory = directory.resolve()
    if directory.is_relative_to(ROOT) or not directory.is_dir():
        raise ValueError("Private directory required")
    info = directory.stat()
    if os.name != "posix" or info.st_mode & 0o077 or info.st_uid != os.geteuid():
        raise ValueError("Owned private directory mode 0700 required")
    return directory


def _connect(directory):
    directory = private_directory(directory)
    path = directory / "auction-review.sqlite"
    flags = os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_nlink != 1
                or info.st_uid != os.geteuid() or info.st_size > MAX_DB_BYTES):
            raise ValueError("Private regular database required")
    finally:
        os.close(fd)
    conn = sqlite3.connect(path, timeout=3)
    try:
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
        if page_size <= 0 or page_size > MAX_DB_BYTES:
            raise ValueError("Invalid database page size")
        conn.execute(f"PRAGMA max_page_count={MAX_DB_BYTES // page_size}")
        conn.execute(SCHEMA)
    except Exception:
        conn.close()
        raise
    return conn


def apply_page(directory, procedures, *, observed_at, now):
    """Apply bounded observations atomically. Never infer withdrawal from absence."""
    now, observed = _aware(now), _aware(observed_at)
    if not timedelta(0) <= now - observed <= MAX_FRESHNESS:
        raise ValueError("Stale observation")
    if not isinstance(procedures, list) or len(procedures) > MAX_ROWS:
        raise ValueError("Bounded page required")
    # Validate before touching disk. Only canonical IDs enter the cache.
    updates = {}
    for row in procedures:
        if not isinstance(row, dict):
            raise ValueError("Unexpected procedure")
        key = row.get("auctionId")
        if not isinstance(key, str) or not ID.fullmatch(key):
            continue
        modified = _utc(row.get("dateModified"))
        if modified > observed + timedelta(minutes=1):
            raise ValueError("Future modification")
        result = candidate(row, observed_at=observed, now=now)
        if result:
            result.pop("observed_at", None)
        stamp = _stamp(modified)
        previous = updates.get(key)
        if previous is None or stamp > previous[0]:
            updates[key] = (stamp, result)
        elif stamp == previous[0] and previous[1] != result:
            updates[key] = (stamp, None)
    conn = _connect(directory)
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            # Keep withdrawal markers longer than the accepted feed lookback.
            conn.execute("DELETE FROM auction_review WHERE observed < ?", (_stamp(now - RETAIN),))
            for key, (modified, result) in updates.items():
                existing = conn.execute(
                    "SELECT modified, observed, payload FROM auction_review WHERE auction_id=?",
                    (key,)).fetchone()
                data = json.dumps(result, sort_keys=True, separators=(",", ":")) if result else None
                if existing:
                    old_modified, old_observed, old_data = existing
                    if modified < old_modified or _stamp(observed) < old_observed:
                        continue
                    # Same-version disagreements are quarantined, including
                    # a protected/withdrawn observation; never revive on replay.
                    if modified == old_modified and old_data != data:
                        data = None
                elif data is None:
                    # Do not store IDs of previously unseen rejected procedures.
                    continue
                conn.execute(
                    "INSERT INTO auction_review VALUES (?,?,?,?) "
                    "ON CONFLICT(auction_id) DO UPDATE SET modified=excluded.modified,"
                    "observed=excluded.observed,payload=excluded.payload",
                    (key, modified, _stamp(observed), data))
            if conn.execute("SELECT COUNT(*) FROM auction_review").fetchone()[0] > MAX_CACHE_ROWS:
                raise ValueError("Private cache row limit exceeded")
        return {"observations": len(procedures), "publications": 0}
    finally:
        conn.close()


def review_candidates(directory, *, now):
    """Private review only. Expired and stale records are invisible."""
    now = _aware(now)
    conn = _connect(directory)
    try:
        output = []
        for observed, data in conn.execute(
            "SELECT observed,payload FROM auction_review WHERE payload IS NOT NULL ORDER BY auction_id"
        ):
            stamp = _utc(observed)
            row = json.loads(data)
            if timedelta(0) <= now - stamp <= MAX_FRESHNESS and now < _utc(row["bidding_ends_at"]):
                row["observed_at"] = observed
                row["review_status"] = "pending_review"
                row["publication_allowed"] = False
                output.append(row)
        return output
    finally:
        conn.close()


def recheck_ids(directory, *, now, limit=5):
    """Oldest retained candidates, including hidden stale rows, for direct lookup."""
    now = _aware(now)
    if type(limit) is not int or not 1 <= limit <= 5:
        raise ValueError("Invalid recheck limit")
    conn = _connect(directory)
    try:
        return [key for (key,) in conn.execute(
            "SELECT auction_id FROM auction_review "
            "WHERE payload IS NOT NULL AND observed >= ? AND observed <= ? "
            "ORDER BY observed, auction_id LIMIT ?",
            (_stamp(now-RETAIN), _stamp(now), limit)) if ID.fullmatch(key)]
    finally:
        conn.close()
