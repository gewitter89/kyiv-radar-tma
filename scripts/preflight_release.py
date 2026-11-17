#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Read-only compatibility preflight for Kyiv Radar releases.

Does not modify a database, catalog, media file, token, or service.
Exits 0 when the new media schema and safe public catalog are ready;
exits 2 with non-sensitive diagnostics otherwise.
"""
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote

REQUIRED_SCHEMA = {
    "landlord_submissions": {"id", "status", "photos", "submitter_id",
                             "contact_verified", "verified_at", "verification_method"},
    "landlord_uploads": {"photo_id", "owner_telegram_id", "submission_id",
                         "status", "created_at"},
    "private_deal_contacts": {"deal_id", "phone"},
    "rate_limits": {"key", "timestamp"},
}


def inspect_release(db_path: str, deals_path: str, uploads_path: str) -> dict:
    errors = []
    warnings = []
    counts = {}
    db_file, catalog_file, photo_dir = (Path(p).expanduser() for p in
                                         (db_path, deals_path, uploads_path))

    if not catalog_file.is_file():
        errors.append("Public catalog file is missing")
    else:
        try:
            with catalog_file.open(encoding="utf-8") as stream:
                records = json.load(stream)
            if not isinstance(records, list):
                errors.append("Catalog must be a JSON array")
            else:
                counts["catalog_listings"] = len(records)
                ids = []
                for record in records:
                    if not isinstance(record, dict) or not isinstance(record.get("id"), int):
                        errors.append("Catalog contains malformed listing identifiers")
                        break
                    ids.append(record["id"])
                if len(ids) != len(set(ids)):
                    errors.append("Catalog contains duplicate listing identifiers")
                if any(isinstance(row, dict) and row.get("phone")
                       for row in records):
                    errors.append("Catalog contains a raw public phone value")
                if any(isinstance(row, dict) and row.get("ownerName")
                       for row in records):
                    warnings.append("Catalog contains a private owner-name field; check public export")
        except (OSError, UnicodeError, json.JSONDecodeError):
            errors.append("Catalog is unreadable or invalid JSON")

    if not db_file.is_file():
        errors.append("SQLite database is missing")
    else:
        try:
            uri = "file:" + quote(str(db_file.resolve()), safe="/") + "?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=3)
            try:
                for table, needed_columns in REQUIRED_SCHEMA.items():
                    columns = {
                        column[1] for column in conn.execute(
                            "PRAGMA table_info(" + table + ")"
                        )
                    }
                    if not columns:
                        errors.append("Missing database table: " + table)
                    elif missing := needed_columns - columns:
                        errors.append("Missing " + table + " columns: " + ", ".join(sorted(missing)))
                if not any(error.startswith("Missing database table: landlord_uploads") for error in errors):
                    counts["registered_images"] = conn.execute(
                        "SELECT COUNT(*) FROM landlord_uploads"
                    ).fetchone()[0]
                if not any(error.startswith("Missing database table: private_deal_contacts") for error in errors):
                    # Record only IDs and counts in diagnostics: never log contact values.
                    available_contact_ids = {
                        row[0] for row in conn.execute(
                            "SELECT deal_id FROM private_deal_contacts "
                            "WHERE phone IS NOT NULL AND length(trim(phone)) >= 9"
                        )
                    }
                    counts["private_contacts_available"] = len(available_contact_ids)
                    if isinstance(locals().get("records"), list):
                        listing_ids = {
                            row["id"] for row in records
                            if isinstance(row, dict) and type(row.get("id")) is int
                        }
                        missing_contacts = listing_ids - available_contact_ids
                        counts["listings_without_private_contact"] = len(missing_contacts)
                        if missing_contacts:
                            warnings.append("Some listings have no contact in the protected database")
                        if listing_ids and not available_contact_ids:
                            errors.append("No protected contacts available for published listings")
            finally:
                conn.close()
        except sqlite3.Error:
            errors.append("Cannot inspect database in read-only mode")

    if not photo_dir.is_dir():
        errors.append("Media storage directory is missing")
    elif not os.access(photo_dir, os.R_OK | os.X_OK):
        errors.append("Media storage directory cannot be read")
    else:
        try:
            fs = os.statvfs(photo_dir)
            free_mb = fs.f_bavail * fs.f_frsize // (1024 * 1024)
            counts["media_disk_free_mb"] = free_mb
            if free_mb < 512:
                warnings.append("Media storage has less than 512 MB free")
        except OSError:
            warnings.append("Available disk space could not be checked")

    return {"ready_for_smoke_test": not errors, "errors": errors,
            "warnings": warnings, "counts": counts}


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Kyiv Radar release preflight")
    parser.add_argument("--db", default=os.getenv(
        "KYIV_RADAR_DB_PATH", "/opt/resell-radar-ukraine/data/rent_deals.db"))
    parser.add_argument("--deals", default=os.getenv(
        "KYIV_RADAR_DEALS_PATH", "/opt/kyiv-radar-tma/data/deals.json"))
    parser.add_argument("--uploads", default=os.getenv(
        "KYIV_RADAR_UPLOADS_DIR", "/opt/kyiv-radar-tma/uploads/landlords"))
    args = parser.parse_args()
    result = inspect_release(args.db, args.deals, args.uploads)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["ready_for_smoke_test"] else 2


if __name__ == "__main__":
    sys.exit(main())
