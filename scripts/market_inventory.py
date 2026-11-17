#!/usr/bin/env python3
"""Mass intake for permissioned Ukrainian real-estate feeds.

PRIVATE staging only. No scraping, website requests, media copying, contacts,
automated approval, publish/export, notifications, or production DB mutation.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
OPERATIONS = {"rent", "sale", "daily_rent"}
PROPERTY_TYPES = {"apartment", "room", "house", "townhouse", "commercial",
                  "office", "warehouse", "land", "garage", "parking", "new_build"}
SOURCE_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,63}$")
ID_RE = re.compile(r"^[^\x00-\x1f\x7f]{1,128}$")
MAX_FEED_BYTES = 250 * 1024 * 1024
MAX_RECORDS = 1_000_000
SCHEMA = """
CREATE TABLE IF NOT EXISTS inventory (
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    operation TEXT NOT NULL,
    property_type TEXT NOT NULL,
    city TEXT NOT NULL,
    district TEXT,
    price_uah INTEGER,
    rooms INTEGER,
    area_m2 REAL,
    unit_key TEXT,
    imported_first_at TEXT NOT NULL,
    imported_last_at TEXT NOT NULL,
    last_batch TEXT NOT NULL,
    misses INTEGER NOT NULL DEFAULT 0,
    review_status TEXT NOT NULL DEFAULT 'pending_review',
    PRIMARY KEY(source, external_id)
);
CREATE INDEX IF NOT EXISTS ix_inventory_url ON inventory(source_url);
CREATE INDEX IF NOT EXISTS ix_inventory_filter ON inventory(operation, property_type, city);
CREATE INDEX IF NOT EXISTS ix_inventory_batch ON inventory(source, last_batch);
CREATE TABLE IF NOT EXISTS batches (
    batch TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    run_at TEXT NOT NULL,
    full_snapshot INTEGER NOT NULL,
    count INTEGER NOT NULL,
    agreement_ref TEXT NOT NULL
);
"""


def path_is_public(path: Path) -> bool:
    return path.resolve().is_relative_to(ROOT)


def checked_input(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path_is_public(path):
        raise ValueError("Private partner feed and attestation may not be stored in public repository")
    if not path.is_file() or path.stat().st_size > MAX_FEED_BYTES:
        raise ValueError("Missing, inaccessible, or oversized input")
    return path


def load_agreement(path: Path, now: datetime) -> dict:
    obj = json.loads(checked_input(path).read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("Agreement must be a JSON object")
    if obj.get("operator_rights_reviewed") is not True:
        raise ValueError("Manual contractual rights review is required")
    if obj.get("metadata_display_permitted") is not True:
        raise ValueError("No permission to use listing metadata")
    source = obj.get("source_key", "")
    if not isinstance(source, str) or not SOURCE_RE.fullmatch(source):
        raise ValueError("Invalid partner source key")
    ref = obj.get("agreement_ref", "")
    if not isinstance(ref, str) or not SOURCE_RE.fullmatch(ref):
        raise ValueError("Private agreement reference required")
    ends = obj.get("valid_until", "")
    try:
        expiry = datetime.strptime(ends, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        raise ValueError("valid_until must be YYYY-MM-DD") from None
    if expiry.date() < now.date():
        raise ValueError("Agreement expired")
    hosts = obj.get("allowed_source_hosts")
    if (not isinstance(hosts, list) or not hosts or len(hosts) > 30 or
        any(not isinstance(h, str) or h.lower() != h or
            not re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+", h) for h in hosts)):
        raise ValueError("Explicit lowercase allowed_source_hosts required")
    if not isinstance(obj.get("full_snapshot_allowed", False), bool):
        raise ValueError("full_snapshot_allowed must be boolean")
    return obj


def canonical_url(value: object, allowed_hosts: list[str]) -> str:
    if not isinstance(value, str) or not value or len(value) > 2000:
        raise ValueError("Missing or oversized source_url")
    try:
        url = urlsplit(value)
        host = (url.hostname or "").lower()
        if (url.scheme != "https" or host not in allowed_hosts or url.username or
            url.password or url.port not in (None, 443) or not url.path.startswith("/")):
            raise ValueError()
        path = url.path.rstrip("/") or "/"
        # Never store tracking, auth, share tokens, or arbitrary query strings.
        return urlunsplit(("https", host, path, "", ""))
    except (ValueError, TypeError):
        raise ValueError("Source URL is not approved HTTPS host") from None


def integer(value: object, name: str, upper: int) -> int | None:
    if value is None or value == "":
        return None
    if type(value) is bool or not isinstance(value, (int, str)):
        raise ValueError(f"Invalid {name}")
    raw = str(value)
    if not re.fullmatch(r"[1-9]\d*", raw):
        raise ValueError(f"Invalid {name}")
    n = int(raw)
    if n > upper:
        raise ValueError(f"Out of range {name}")
    return n


def normalise(row: object, agreement: dict) -> dict:
    if not isinstance(row, dict):
        raise ValueError("Record must be an object")
    key = row.get("external_id")
    if not isinstance(key, (str, int)) or isinstance(key, bool):
        raise ValueError("External ID must be string/integer")
    key = str(key)
    if not ID_RE.fullmatch(key):
        raise ValueError("Invalid external ID")
    operation, prop = row.get("operation"), row.get("property_type")
    if operation not in OPERATIONS or prop not in PROPERTY_TYPES:
        raise ValueError("Unsupported operation or property type")
    city = row.get("city")
    if not isinstance(city, str) or not 2 <= len(city.strip()) <= 100:
        raise ValueError("Missing city")
    district = row.get("district")
    if district is not None and (not isinstance(district, str) or len(district) > 100):
        raise ValueError("Invalid district")
    area = row.get("area_m2")
    if area not in ("", None):
        try:
            area = float(area)
        except (TypeError, ValueError):
            raise ValueError("Invalid area_m2") from None
        if not 0 < area < 1_000_000 or area != area:
            raise ValueError("Invalid area_m2")
    else:
        area = None
    unit = row.get("unit_key")
    if unit is not None and (not isinstance(unit, str) or len(unit) > 128 or
                             any(ord(ch) < 32 for ch in unit)):
        raise ValueError("Invalid unit_key")
    return {
        "external_id": key,
        "source_url": canonical_url(row.get("source_url"), agreement["allowed_source_hosts"]),
        "operation": operation,
        "property_type": prop,
        "city": city.strip(),
        "district": district.strip() if district else None,
        "price_uah": integer(row.get("price_uah"), "price_uah", 10**12),
        "rooms": integer(row.get("rooms"), "rooms", 100),
        "area_m2": area,
        "unit_key": unit,
        # Titles, descriptions, owner information, phone, coordinates and photos
        # are deliberately not imported, even if supplied by partner's file.
    }


def read_rows(path: Path):
    if path.suffix.lower() == ".jsonl":
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                if line.strip():
                    yield json.loads(line)
    elif path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            yield from csv.DictReader(stream)
    elif path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("JSON feed must contain an array")
        yield from data
    else:
        raise ValueError("Only JSONL, JSON and CSV permissioned feeds are supported")


def ingest(feed_path: Path, agreement_path: Path, database_path: Path,
           *, full_snapshot: bool = False, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    feed = checked_input(feed_path)
    agreement = load_agreement(agreement_path, now)
    if full_snapshot and agreement.get("full_snapshot_allowed") is not True:
        raise ValueError("Agreement does not authorize full snapshots")
    requested = database_path.expanduser()
    if requested.is_symlink():
        raise ValueError("Symlink destination forbidden")
    target = requested.resolve()
    if path_is_public(target):
        raise ValueError("Private inventory DB may not be stored inside the public repo")
    if not target.parent.is_dir():
        raise ValueError("Database parent directory must exist")

    old_umask = os.umask(0o077)
    try:
        conn = sqlite3.connect(str(target), timeout=45)
    finally:
        os.umask(old_umask)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        source = agreement["source_key"]
        existing = conn.execute("SELECT COUNT(*) FROM inventory WHERE source=?", (source,)).fetchone()[0]
        timestamp = now.astimezone(timezone.utc).isoformat()
        # Collision-free run id without secrets: timestamp plus PID and sequential batches.
        import uuid
        batch = uuid.uuid4().hex
        stats = {"accepted": 0, "inserted": 0, "changed": 0, "unchanged": 0,
                 "possible_duplicates": 0, "needs_withdrawal_review": 0}
        seen: set[str] = set()
        for input_row in read_rows(feed):
            row = normalise(input_row, agreement)
            ext = row["external_id"]
            if ext in seen:
                raise ValueError("Repeated external_id in the same feed; abort atomic batch")
            seen.add(ext)
            stats["accepted"] += 1
            if stats["accepted"] > MAX_RECORDS:
                raise ValueError("Feed exceeds one million records")
            previous = conn.execute(
                "SELECT source_url, operation, property_type, city, district, price_uah, "
                "rooms, area_m2, unit_key, review_status FROM inventory WHERE source=? AND external_id=?",
                (source, ext)).fetchone()
            payload = tuple(row[c] for c in ("source_url", "operation", "property_type",
                                              "city", "district", "price_uah", "rooms", "area_m2", "unit_key"))
            if previous is None:
                status = "pending_review"
                stats["inserted"] += 1
                # Cross-feed duplicates are candidates for human review, never merged.
                if conn.execute(
                    "SELECT 1 FROM inventory WHERE source_url=? OR "
                    "(? IS NOT NULL AND unit_key=?) LIMIT 1",
                    (row["source_url"], row["unit_key"], row["unit_key"])
                ).fetchone():
                    stats["possible_duplicates"] += 1
                conn.execute(
                    "INSERT INTO inventory (source, external_id, source_url, operation, "
                    "property_type, city, district, price_uah, rooms, area_m2, unit_key, "
                    "imported_first_at, imported_last_at, last_batch, review_status) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (source, ext, *payload, timestamp, timestamp, batch, status))
            elif tuple(previous[:9]) != payload:
                stats["changed"] += 1
                # Changing any approved listing requires renewed human verification.
                status = ("needs_review" if previous[9] == "approved"
                          else "pending_review" if previous[9] == "possible_withdrawn"
                          else previous[9])
                conn.execute(
                    "UPDATE inventory SET source_url=?, operation=?, property_type=?, "
                    "city=?, district=?, price_uah=?, rooms=?, area_m2=?, unit_key=?, "
                    "imported_last_at=?, last_batch=?, misses=0, review_status=? "
                    "WHERE source=? AND external_id=?",
                    (*payload, timestamp, batch, status, source, ext))
            else:
                stats["unchanged"] += 1
                conn.execute(
                    "UPDATE inventory SET imported_last_at=?,last_batch=?,misses=0, "
                    "review_status=CASE WHEN review_status='possible_withdrawn' "
                    "THEN 'pending_review' ELSE review_status END "
                    "WHERE source=? AND external_id=?",
                    (timestamp, batch, source, ext))

        if full_snapshot:
            # Empty/truncated feed is a likely outage, not mass withdrawal.
            if not stats["accepted"] or (existing >= 20 and stats["accepted"] < existing * 0.5):
                raise ValueError("Incomplete snapshot: refuse mass stale-marking")
            conn.execute(
                "UPDATE inventory SET misses=misses+1 WHERE source=? AND last_batch<>?",
                (source, batch))
            updated = conn.execute(
                "UPDATE inventory SET review_status='possible_withdrawn' "
                "WHERE source=? AND last_batch<>? AND misses>=2 AND "
                "review_status NOT IN ('rejected','possible_withdrawn')",
                (source, batch))
            stats["needs_withdrawal_review"] = updated.rowcount
        conn.execute(
            "INSERT INTO batches(batch,source,run_at,full_snapshot,count,agreement_ref) "
            "VALUES (?,?,?,?,?,?)",
            (batch, source, timestamp, int(full_snapshot), stats["accepted"],
             agreement["agreement_ref"]))
        conn.commit()
        return {"source": source, "full_snapshot": full_snapshot, **stats,
                "publications": 0, "contacts_copied": 0, "media_copied": 0}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> int:
    p = argparse.ArgumentParser(description="Private, rights-gated bulk property inventory")
    p.add_argument("--feed", type=Path, required=True)
    p.add_argument("--agreement", type=Path, required=True)
    p.add_argument("--database", type=Path, required=True)
    p.add_argument("--full-snapshot", action="store_true")
    args = p.parse_args()
    try:
        result = ingest(args.feed, args.agreement, args.database,
                        full_snapshot=args.full_snapshot)
        print(json.dumps({"ok": True, **result}, ensure_ascii=False))
        return 0
    except (ValueError, OSError, sqlite3.Error, UnicodeError,
            json.JSONDecodeError, csv.Error) as error:
        # No paths, raw feed data, contact details or API credentials in logs.
        print(json.dumps({"ok": False, "error_type": type(error).__name__}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
