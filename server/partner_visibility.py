"""Private source-rights enforcement for explicitly marked partner listings.

This module filters the API's already-reviewed catalog and never publishes
private inventory by itself. No feeds, secrets or licenses are created here.
Legacy OLX/DIM.RIA cards are not silently upgraded into licensed partner data.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

SOURCE_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,63}$")
EXTERNAL_RE = re.compile(r"^[^\x00-\x1f\x7f]{1,128}$")


def is_partner_item(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    return (item.get("partnerSourceKey") is not None
            or item.get("partnerExternalId") is not None
            or str(item.get("source", "")).lower().startswith("partner:"))


def _identity(item: dict) -> tuple[str, str, str] | None:
    source = item.get("partnerSourceKey")
    external = item.get("partnerExternalId")
    original_url = item.get("url")
    if (not isinstance(source, str) or SOURCE_RE.fullmatch(source) is None
            or item.get("source") != f"partner:{source}"
            or not isinstance(external, (str, int)) or isinstance(external, bool)
            or not EXTERNAL_RE.fullmatch(str(external))
            or not isinstance(original_url, str) or not original_url.startswith("https://")
            or len(original_url) > 2000):
        return None
    return source, str(external), original_url


def _readonly_connection(db_path: str | None) -> sqlite3.Connection | None:
    if not db_path or not isinstance(db_path, str):
        return None
    try:
        supplied = Path(db_path).expanduser()
        if supplied.is_symlink() or not supplied.is_file():
            return None
        resolved = supplied.resolve(strict=True)
        if resolved.is_symlink():
            return None
        uri = "file:" + quote(str(resolved), safe="/") + "?mode=ro"
        return sqlite3.connect(uri, uri=True, timeout=3.0)
    except (OSError, ValueError, sqlite3.Error):
        return None


def enforce_partner_visibility(
    deals: list[dict], private_db: str | None,
    *, now: datetime | None = None,
) -> list[dict]:
    """Fail closed on every marked partner row, preserve legacy unrelated rows.

    Admission requires all of: explicit partner identity, independent recent
    availability evidence (set by the private reviewer, not copied from feed),
    source contract active and unexpired, approved inventory record, identical
    canonical source link. A separate publication gate is still required before
    an actual partner feed can be made public.
    """
    if not isinstance(deals, list):
        return []
    if not any(is_partner_item(row) for row in deals):
        return deals
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date().isoformat()
    conn = _readonly_connection(private_db)
    result: list[dict] = []
    try:
        for item in deals:
            if not is_partner_item(item):
                result.append(item)
                continue
            if conn is None or item.get("actualityConfirmed") is not True:
                continue
            identity = _identity(item)
            if identity is None:
                continue
            source, external, source_url = identity
            try:
                match = conn.execute(
                    "SELECT i.source_url FROM inventory AS i "
                    "JOIN source_rights AS r ON r.source=i.source "
                    "WHERE i.source=? AND i.external_id=? "
                    "AND i.review_status='approved' "
                    "AND r.status='active' AND r.valid_until>=? "
                    "AND length(r.scope_digest)=64 LIMIT 1",
                    (source, external, current),
                ).fetchone()
            except sqlite3.Error:
                # Missing/corrupt schema, locked or inaccessible DB -> no partner.
                continue
            if match is not None and source_url == match[0]:
                result.append(item)
    finally:
        if conn is not None:
            conn.close()
    return result
