"""Private Telegram-authenticated favorites state: strict optimistic concurrency.

No tokens or contact details stored. Browser-initiated manual sync only.
An old device cannot overwrite newer state without fetching fresh revision
and explicitly choosing how to reconcile.
"""
from __future__ import annotations

import secrets
import sqlite3
import urllib.parse
from urllib.parse import urlsplit

MAX_ITEMS = 300
MAX_KEY_LENGTH = 2100


class FavoritesConflict(Exception):
    pass


class InvalidFavorites(ValueError):
    pass


def valid_identity(value: object) -> bool:
    if not isinstance(value, str) or not 8 <= len(value) <= MAX_KEY_LENGTH:
        return False
    parts = value.split("|", 2)
    if len(parts) != 3 or parts[0] != "kr2":
        return False
    try:
        source = urllib.parse.unquote(parts[1])
        if not source or len(source) > 80 or "|" in source or any(ord(c) < 32 for c in source):
            return False
        url = urlsplit(parts[2])
        if (url.scheme != "https" or not url.hostname or
            "." not in url.hostname or url.username or url.password or
            url.fragment or not url.path or url.path == "/"):
            return False
        for name, value in urllib.parse.parse_qsl(url.query, keep_blank_values=True):
            if name not in {"id", "offer_id", "listing_id", "object_id", "internal_id"}:
                return False
            if not value or len(value) > 100 or not all(
                c.isascii() and (c.isalnum() or c in "_-") for c in value
            ):
                return False
        return True
    except (ValueError, TypeError):
        return False


def create_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS favorite_sync_accounts (
          telegram_user_id INTEGER PRIMARY KEY,
          generation TEXT NOT NULL,
          revision INTEGER NOT NULL DEFAULT 0,
          CHECK (revision >= 0)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS favorite_sync_keys (
          telegram_user_id INTEGER NOT NULL,
          stable_identity TEXT NOT NULL,
          PRIMARY KEY (telegram_user_id, stable_identity)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS ix_favorite_sync_user ON favorite_sync_keys(telegram_user_id)")


def _db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=5)
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def state(db_path: str, user_id: int) -> dict:
    with _db(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        entry = conn.execute(
            "SELECT generation,revision FROM favorite_sync_accounts WHERE telegram_user_id=?",
            (user_id,)
        ).fetchone()
        if entry is None:
            entry = (secrets.token_hex(16), 0)
            conn.execute(
                "INSERT INTO favorite_sync_accounts(telegram_user_id,generation,revision) VALUES (?,?,0)",
                (user_id, entry[0])
            )
        keys = [
            row[0] for row in conn.execute(
                "SELECT stable_identity FROM favorite_sync_keys "
                "WHERE telegram_user_id=? ORDER BY stable_identity", (user_id,)
            ).fetchall()
        ]
        return {"revision": entry[1], "generation": entry[0], "keys": keys}


def replace(db_path: str, user_id: int, generation: str, revision: int, keys: list[str]) -> dict:
    if (not isinstance(keys, list) or len(keys) > MAX_ITEMS or
        len(keys) != len(set(keys)) or not all(valid_identity(key) for key in keys)):
        raise InvalidFavorites("Invalid or duplicate favorite identifiers")
    if not isinstance(revision, int) or revision < 0 or not isinstance(generation, str):
        raise InvalidFavorites("Invalid revision")
    with _db(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        previous = conn.execute(
            "SELECT generation,revision FROM favorite_sync_accounts WHERE telegram_user_id=?",
            (user_id,)
        ).fetchone()
        if previous is None or previous != (generation, revision):
            raise FavoritesConflict("Favorites were updated on another device")
        # One atomic replacement conditioned on the revision. Never merge or
        # resurrect an entry from a stale browser automatically.
        conn.execute("DELETE FROM favorite_sync_keys WHERE telegram_user_id=?", (user_id,))
        conn.executemany(
            "INSERT INTO favorite_sync_keys(telegram_user_id,stable_identity) VALUES (?,?)",
            [(user_id, key) for key in sorted(keys)]
        )
        conn.execute(
            "UPDATE favorite_sync_accounts SET revision=revision+1 WHERE telegram_user_id=?",
            (user_id,)
        )
        return {"revision": revision + 1, "generation": generation, "keys": sorted(keys)}


def purge(db_path: str, user_id: int, generation: str) -> dict:
    with _db(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        old = conn.execute(
            "SELECT generation,revision FROM favorite_sync_accounts WHERE telegram_user_id=?",
            (user_id,)
        ).fetchone()
        if old is None or old[0] != generation:
            raise FavoritesConflict("Account session was reset")
        conn.execute("DELETE FROM favorite_sync_keys WHERE telegram_user_id=?", (user_id,))
        fresh = secrets.token_hex(16)
        conn.execute(
            "UPDATE favorite_sync_accounts SET generation=?,revision=revision+1 "
            "WHERE telegram_user_id=?", (fresh, user_id)
        )
        return {"revision": old[1] + 1, "generation": fresh, "keys": []}
