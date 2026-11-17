#!/usr/bin/env python3
"""Official DIM.RIA search ID discovery, disabled unless explicitly executed.

Stores ONLY source ad IDs in a PRIVATE database. Search API results are not
a license to republish titles, photos, addresses, prices, or private contacts.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    from .market_inventory import checked_input, load_agreement, path_is_public
except ImportError:
    from market_inventory import checked_input, load_agreement, path_is_public

URL = "https://developers.ria.com/dom/search"
HOURLY_LIMIT = 30
MONTHLY_LIMIT = 1000
MAX_PAGES_PER_RUN = 25

DDL = """
CREATE TABLE IF NOT EXISTS quota (
    hour_utc TEXT NOT NULL,
    month_utc TEXT NOT NULL,
    consumed INTEGER NOT NULL CHECK (consumed = 1)
);
CREATE INDEX IF NOT EXISTS ix_quota_hour ON quota(hour_utc);
CREATE INDEX IF NOT EXISTS ix_quota_month ON quota(month_utc);
CREATE TABLE IF NOT EXISTS discovered_ids (
    provider TEXT NOT NULL DEFAULT 'DIM.RIA',
    advert_id TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY(provider, advert_id)
);
"""


def positive(value: int, field: str) -> int:
    if type(value) is not int or not 1 <= value <= 10_000_000:
        raise ValueError(f"Invalid {field}")
    return value


def db_connect(path: Path):
    original = path.expanduser()
    if original.is_symlink():
        raise ValueError("Symlink destination is forbidden")
    target = original.resolve()
    if path_is_public(target) or not target.parent.is_dir():
        raise ValueError("Only a private SQLite destination is permitted")
    umask = os.umask(0o077)
    try:
        conn = sqlite3.connect(target, timeout=30)
    finally:
        os.umask(umask)
    conn.executescript(DDL)
    conn.commit()
    return conn


def reserve_quota(conn: sqlite3.Connection, now: datetime):
    utc = now.astimezone(timezone.utc).isoformat()
    hour, month = utc[:13], utc[:7]
    conn.execute("BEGIN IMMEDIATE")
    try:
        count_hour = conn.execute("SELECT COUNT(*) FROM quota WHERE hour_utc=?", (hour,)).fetchone()[0]
        count_month = conn.execute("SELECT COUNT(*) FROM quota WHERE month_utc=?", (month,)).fetchone()[0]
        if count_hour >= HOURLY_LIMIT or count_month >= MONTHLY_LIMIT:
            raise ValueError("Local official API request budget exhausted")
        conn.execute("INSERT INTO quota(hour_utc,month_utc,consumed) VALUES (?,?,1)", (hour, month))
        conn.commit()  # Reserve BEFORE request, including timeouts and 429.
    except Exception:
        conn.rollback()
        raise


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Official API redirect denied")


def official_request(url: str) -> bytes:
    opener = urllib.request.build_opener(NoRedirect())
    req = urllib.request.Request(url, headers={"Accept": "application/json",
                                                "User-Agent": "KyivRadar-permitted-discovery/1.0"})
    try:
        with opener.open(req, timeout=15) as res:
            if res.status != 200:
                raise ValueError("Official API request unsuccessful")
            return res.read(4 * 1024 * 1024)
    except urllib.error.HTTPError:
        raise ValueError("Official API rejected request (including possible 429)") from None
    except urllib.error.URLError:
        raise ValueError("Official API transport unavailable") from None


def discover(agreement_file: Path, database_file: Path, *,
             api_key: str, category: int, realty_type: int, operation_type: int,
             state_id: int, city_id: int, pages: int, now: datetime | None = None,
             request_fn=official_request) -> dict:
    now = now or datetime.now(timezone.utc)
    approval = load_agreement(agreement_file, now)
    if approval.get("source_key") != "dim_ria" or \
       "dom.ria.com" not in approval.get("allowed_source_hosts", []):
        raise ValueError("This discovery adapter requires private DIM.RIA approval")
    if not isinstance(api_key, str) or not 20 <= len(api_key) <= 256 or any(x.isspace() for x in api_key):
        raise ValueError("Missing valid private DIM_RIA_API_KEY")
    if type(pages) is not int or not 1 <= pages <= MAX_PAGES_PER_RUN:
        raise ValueError("At most 25 search pages may be requested per run")
    params = {k: positive(v, k) for k,v in {
        "category": category, "realty_type": realty_type, "operation_type": operation_type,
        "state_id": state_id, "city_id": city_id}.items()}
    conn = db_connect(database_file)
    stats = {"pages_requested": 0, "ids_found": 0, "new_ids": 0,
             "publications": 0, "details_copied": 0, "images_copied": 0}
    try:
        for page in range(pages):
            reserve_quota(conn, now)
            qs = urllib.parse.urlencode({**params, "page": page, "api_key": api_key})
            request_url = URL + "?" + qs
            # Never log request_url: API key appears in the query by provider design.
            payload = json.loads(request_fn(request_url))
            if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
                raise ValueError("Unexpected official API response shape")
            items = payload["items"]
            if len(items) > 500:
                raise ValueError("Unexpected response size")
            parsed = set()
            for value in items:
                if not isinstance(value, (str, int)) or isinstance(value, bool) or \
                   not str(value).isdigit() or not 1 <= len(str(value)) <= 18:
                    raise ValueError("Invalid provider advert ID")
                parsed.add(str(value))
            stats["ids_found"] += len(parsed)
            stats["pages_requested"] += 1
            time = now.astimezone(timezone.utc).isoformat()
            with conn:
                for advert_id in parsed:
                    record = conn.execute(
                        "SELECT 1 FROM discovered_ids WHERE provider='DIM.RIA' AND advert_id=?",
                        (advert_id,)).fetchone()
                    if record is None:
                        conn.execute("INSERT INTO discovered_ids(provider, advert_id, first_seen_at, last_seen_at) "
                                     "VALUES ('DIM.RIA',?,?,?)", (advert_id, time, time))
                        stats["new_ids"] += 1
                    else:
                        conn.execute("UPDATE discovered_ids SET last_seen_at=? "
                                     "WHERE provider='DIM.RIA' AND advert_id=?", (time, advert_id))
            if not items:
                break
        return stats
    finally:
        conn.close()


def main() -> int:
    p = argparse.ArgumentParser(description="Opt-in official DIM.RIA search discovery; IDs only")
    p.add_argument("--agreement", type=Path, required=True)
    p.add_argument("--database", type=Path, required=True)
    p.add_argument("--category", type=int, required=True)
    p.add_argument("--realty-type", type=int, required=True)
    p.add_argument("--operation-type", type=int, required=True)
    p.add_argument("--state-id", type=int, required=True)
    p.add_argument("--city-id", type=int, required=True)
    p.add_argument("--pages", type=int, default=1)
    p.add_argument("--execute", action="store_true",
                   help="Authorize real provider calls with a private API key")
    args = p.parse_args()
    if not args.execute:
        print(json.dumps({"ok": True, "mode": "plan_only", "network_calls": 0,
                          "requires_key": True, "pages": args.pages}))
        return 0
    try:
        result = discover(
            args.agreement, args.database,
            api_key=os.environ.get("DIM_RIA_API_KEY", ""),
            category=args.category, realty_type=args.realty_type,
            operation_type=args.operation_type, state_id=args.state_id,
            city_id=args.city_id, pages=args.pages)
        print(json.dumps({"ok": True, **result}))
        return 0
    except (ValueError, OSError, sqlite3.Error, json.JSONDecodeError, TypeError):
        print(json.dumps({"ok": False, "error": "Provider, configuration or quota error. Review privately."}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
