#!/usr/bin/env python3
"""Rights- and reviewer-gated private publication preparation for Kyiv Radar.

NEVER fetches feeds, signs contracts, approves listings, copies owner info, or
changes a public file. The export is a short-lived, private source for the
server's independent per-request rights and reviewer checks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from .listing_trust import load_private_register, public_listing_view

ROOT = Path(__file__).resolve().parents[1]
KEY = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,63}$")
ALLOWED = {"source_url", "operation", "property_type", "city", "district",
           "price_uah", "rooms", "area_m2"}
REQUIRED = {"source_url", "operation", "property_type", "city", "price_uah"}
MAX_EXPORT_ROWS = 2000
MAX_EXPORT_SIZE = 8_000_000
MAX_RECEIPT_SIZE = 100_000
MAX_AGE = timedelta(hours=48)


def private_path(path: str | Path | None, *, existing: bool) -> Path:
    if not path:
        raise ValueError("Private path required")
    original = Path(path).expanduser()
    if original.is_symlink():
        raise ValueError("Symlink paths are not allowed")
    target = original.resolve(strict=existing)
    if target.is_relative_to(ROOT):
        raise ValueError("Private files must remain outside the public repository")
    if existing and not target.is_file():
        raise ValueError("Private input file required")
    if not existing and (not target.parent.is_dir() or target.exists()):
        raise ValueError("New private export path must not exist")
    return target


def parse_date(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Date is required")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise ValueError("Date must be YYYY-MM-DD") from None


def publication_receipt(path: str | Path | None, *, now: datetime | None = None) -> tuple[dict, str]:
    """Operator-attested contractual rights; NOT a substitute for checking a contract."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    p = private_path(path, existing=True)
    if p.stat().st_size > MAX_RECEIPT_SIZE:
        raise ValueError("Authorization too large")
    raw = p.read_bytes()
    obj = json.loads(raw)
    if not isinstance(obj, dict) or obj.get("schema_version") != 1:
        raise ValueError("Unknown publication authorization format")
    if obj.get("publication_permitted") is not True:
        raise ValueError("Publication has not been authorized")
    source, contract = obj.get("source_key"), obj.get("agreement_ref")
    if (not isinstance(source, str) or not KEY.fullmatch(source) or
        not isinstance(contract, str) or not KEY.fullmatch(contract)):
        raise ValueError("Source and private agreement reference are required")
    if parse_date(obj.get("valid_until")) < now.date().isoformat():
        raise ValueError("Publication consent expired")
    fields = obj.get("permitted_fields")
    if not isinstance(fields, list) or len(fields) != len(set(str(x) for x in fields)):
        raise ValueError("Invalid publication field scope")
    if not all(isinstance(x, str) for x in fields):
        raise ValueError("Invalid publication field type")
    granted = set(fields)
    if not REQUIRED.issubset(granted) or not granted.issubset(ALLOWED):
        raise ValueError("Missing core metadata rights or unsupported licensed fields")
    for field in ("reviewed_by", "evidence_ref"):
        value = obj.get(field)
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 160:
            raise ValueError("Manual reviewer and private evidence reference required")
    checked = obj.get("reviewed_at")
    try:
        date = datetime.fromisoformat(checked.replace("Z", "+00:00"))
        if date.tzinfo is None:
            raise ValueError()
    except (AttributeError, ValueError, TypeError):
        raise ValueError("Verified operator review timestamp required") from None
    elapsed = now - date.astimezone(timezone.utc)
    if elapsed < -timedelta(minutes=5) or elapsed > timedelta(days=30):
        raise ValueError("Operator authorization review is stale")
    # The file's content hash binds each export to the precise reviewed scope.
    return obj, hashlib.sha256(raw).hexdigest()


def stable_id(source: str, external_id: str) -> int:
    digest = hashlib.sha256((source + "\0" + external_id).encode("utf-8")).digest()
    return 1_000_000_000_000 + (int.from_bytes(digest[:8], "big") % 8_000_000_000_000_000)


def _rights_connection(db_path: str | Path) -> sqlite3.Connection:
    path = private_path(db_path, existing=True)
    uri = "file:" + quote(str(path), safe="/") + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=5)


def prepare_private_export(db_path: str | Path, authorization_path: str | Path,
                           reviews_path: str | Path, *, now: datetime | None = None) -> dict:
    """Build a sanitized private export preview in memory, no writes."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    receipt, receipt_hash = publication_receipt(authorization_path, now=now)
    source, contract = receipt["source_key"], receipt["agreement_ref"]
    reviews_file = private_path(reviews_path, existing=True)
    reviews = load_private_register(str(reviews_file))
    if not reviews:
        raise ValueError("No private independent review register available")
    current_day = now.date().isoformat()
    with _rights_connection(db_path) as conn:
        row = conn.execute(
            "SELECT agreement_ref, valid_until, status FROM source_rights WHERE source=?",
            (source,),
        ).fetchone()
        if not row or row[0] != contract or row[2] != "active" or row[1] < current_day:
            raise ValueError("Source contract does not permit publication")
        if receipt["valid_until"] > row[1]:
            raise ValueError("Publication consent exceeds source agreement")
        items = conn.execute(
            "SELECT external_id,source_url,operation,property_type,city,district,"
            "price_uah,rooms,area_m2 FROM inventory "
            "WHERE source=? AND review_status='approved' "
            "ORDER BY external_id LIMIT ?",
            (source, MAX_EXPORT_ROWS + 1),
        ).fetchall()
    if len(items) > MAX_EXPORT_ROWS:
        raise ValueError("Export requires pagination and smaller reviewed batch")

    allowed_fields = set(receipt["permitted_fields"])
    export: list[dict] = []
    used_ids: set[int] = set()
    for external_id, source_url, operation, kind, city, district, price, rooms, area in items:
        # The currently deployed UX is specifically Kyiv apartment rentals.
        # Other cities/sales are ingested privately but never mislabeled as rentals.
        if operation != "rent" or kind != "apartment" or city != "Київ":
            continue
        if type(price) is not int or price <= 0:
            continue
        numeric = stable_id(source, str(external_id))
        if numeric in used_ids:
            raise ValueError("Listing ID collision requires manual resolution")
        used_ids.add(numeric)
        deal = {
            "id": numeric,
            "source": f"partner:{source}",
            "partnerSourceKey": source,
            "partnerExternalId": str(external_id),
            "url": source_url,
            "title": "Квартира — Київ",
            "price": price,
            "district": district if "district" in allowed_fields and district else "Район уточнюється",
            "address": city + (", " + district if "district" in allowed_fields and district else ""),
            "status": "Пропозиція партнера",
            "images": [],
            "contactVerified": False,
            "isOwnerVerified": False,
            "commissionVerified": False,
            "locationVerified": False,
            "actualityConfirmed": False,
        }
        if "rooms" in allowed_fields and type(rooms) is int and rooms > 0:
            deal["rooms"] = rooms
        if "area_m2" in allowed_fields and type(area) in (int, float) and area > 0:
            deal["area"] = area
        # The reviewer is independent of the provider, and their confidential
        # evidence is never serialized into the output file.
        checked = public_listing_view([deal], reviews, now=now)
        if checked and checked[0].get("actualityConfirmed") is True:
            # Keep the private authorization information out of the cards.
            export.append(deal)

    return {
        "schema_version": 1,
        "source_key": source,
        "agreement_ref": contract,
        "authorization_sha256": receipt_hash,
        "generated_at": now.isoformat(timespec="seconds"),
        "items": export,
    }


def read_private_export(export_path: str | None, authorization_path: str | None,
                        *, now: datetime | None = None) -> list[dict]:
    """Read a short-lived export only with the same current publication receipt."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        receipt, signature = publication_receipt(authorization_path, now=now)
        path = private_path(export_path, existing=True)
        if path.stat().st_size > MAX_EXPORT_SIZE:
            return []
        blob = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(blob, dict) or blob.get("schema_version") != 1:
            return []
        if (blob.get("source_key") != receipt["source_key"]
                or blob.get("agreement_ref") != receipt["agreement_ref"]
                or blob.get("authorization_sha256") != signature):
            return []
        generated = datetime.fromisoformat(blob["generated_at"])
        if generated.tzinfo is None:
            return []
        age = now - generated.astimezone(timezone.utc)
        if age < -timedelta(minutes=5) or age > MAX_AGE:
            return []
        items = blob.get("items")
        if not isinstance(items, list) or len(items) > MAX_EXPORT_ROWS:
            return []
        fields = {"id", "source", "partnerSourceKey", "partnerExternalId", "url",
                  "title", "price", "district", "address", "status", "images",
                  "rooms", "area", "contactVerified", "isOwnerVerified",
                  "commissionVerified", "locationVerified", "actualityConfirmed"}
        clean = []
        used = set()
        for item in items:
            if not isinstance(item, dict) or not set(item).issubset(fields):
                return []
            external = item.get("partnerExternalId")
            if (not isinstance(external, str)
                    or not 1 <= len(external) <= 128
                    or any(ord(ch) < 32 or ord(ch) == 127 for ch in external)
                    or item.get("source") != f"partner:{receipt['source_key']}"
                    or item.get("partnerSourceKey") != receipt["source_key"]
                    or type(item.get("id")) is not int
                    or item["id"] != stable_id(receipt["source_key"], external)
                    or item["id"] in used
                    or item.get("images") != []
                    or item.get("title") != "Квартира — Київ"
                    or item.get("status") != "Пропозиція партнера"):
                return []
            scope = set(receipt["permitted_fields"])
            if ("rooms" in item and "rooms" not in scope) or (
                "area" in item and "area_m2" not in scope):
                return []
            district = item.get("district")
            address = item.get("address")
            if "district" not in scope:
                if district != "Район уточнюється" or address != "Київ":
                    return []
            elif (not isinstance(district, str)
                  or not 1 <= len(district) <= 100
                  or address not in ("Київ", "Київ, " + district)):
                return []
            if any(item.get(field) is True for field in (
                "contactVerified", "isOwnerVerified", "commissionVerified",
                "locationVerified", "actualityConfirmed"
            )):
                return []
            used.add(item["id"])
            clean.append(item)
        return clean
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error,
            UnicodeError, json.JSONDecodeError, OverflowError):
        return []


def write_private_export(output: str | Path, payload: dict) -> None:
    target = private_path(output, existing=False)
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_EXPORT_SIZE:
        raise ValueError("Private export too large")
    fd, tmp = tempfile.mkstemp(prefix=".kr-export-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main() -> int:
    p = argparse.ArgumentParser(description="Private, approval-gated partner publication preview")
    p.add_argument("--database", type=Path, required=True)
    p.add_argument("--authorization", type=Path, required=True)
    p.add_argument("--reviews", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--execute", action="store_true",
                   help="Write private export after manual rights and reviewer checks")
    args = p.parse_args()
    try:
        result = prepare_private_export(args.database, args.authorization, args.reviews)
        if args.execute:
            write_private_export(args.output, result)
        print(json.dumps({"ok": True, "mode": "private_export" if args.execute else "plan_only",
                          "eligible": len(result["items"]), "publications": 0}))
        return 0
    except (ValueError, OSError, sqlite3.Error, TypeError, json.JSONDecodeError):
        print('{"ok":false,"error":"Publication rights or private inputs rejected"}')
        return 2


if __name__ == "__main__":
    sys.exit(main())
