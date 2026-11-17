#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Create a private, consistent release backup and test schema migration on a copy.

NO production writes. Does not restart services, deploy, edit .env or touch bot tokens.
Backups may contain phone numbers; never upload their contents to GitHub or chat.
"""
import argparse
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.preflight_release import inspect_release


def safe_copy(src: Path, dst: Path):
    if src.is_symlink():
        raise RuntimeError("Backup source must not be a symbolic link")
    shutil.copyfile(src, dst)
    dst.chmod(0o600)


def backup_sqlite(source: Path, destination: Path):
    uri = "file:" + quote(str(source.resolve()), safe="/") + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=10) as current:
        with sqlite3.connect(destination) as snapshot:
            current.backup(snapshot)
            if snapshot.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("SQLite backup integrity check failed")
    destination.chmod(0o600)


def backup_media(source: Path, destination: Path):
    destination.mkdir(mode=0o700)
    if not source.exists():
        return 0
    if not source.is_dir() or source.is_symlink():
        raise RuntimeError("Photo directory must be a real directory")
    file_count = 0
    for root, dirs, files in os.walk(source, followlinks=False):
        root_path = Path(root)
        relative = root_path.relative_to(source)
        for directory in dirs:
            item = root_path / directory
            if item.is_symlink():
                raise RuntimeError("Refusing to follow linked media directory")
            (destination / relative / directory).mkdir(mode=0o700, exist_ok=True)
        for filename in files:
            item = root_path / filename
            if not item.is_file() or item.is_symlink():
                raise RuntimeError("Refusing unsupported media file")
            safe_copy(item, destination / relative / filename)
            file_count += 1
    return file_count


def main():
    parser = argparse.ArgumentParser(description="Private, backup-only Kyiv Radar release preparation")
    parser.add_argument("--db", required=True)
    parser.add_argument("--deals", required=True)
    parser.add_argument("--uploads", required=True)
    parser.add_argument("--private-contacts", default="")
    parser.add_argument("--backup-root", required=True)
    args = parser.parse_args()

    db = Path(args.db).resolve()
    deals = Path(args.deals).resolve()
    uploads = Path(args.uploads).resolve()
    vault = Path(args.private_contacts).resolve() if args.private_contacts else None
    backup_root = Path(args.backup_root).resolve()
    if not db.is_file() or not deals.is_file() or db.is_symlink() or deals.is_symlink():
        parser.error("Source database and public catalog must be regular files")
    if backup_root.exists() and (backup_root.is_symlink() or
                                 (os.name != "nt" and stat.S_IMODE(backup_root.stat().st_mode) & 0o077)):
        parser.error("Backup root must be a private directory (mode 0700)")
    backup_root.mkdir(parents=True, mode=0o700, exist_ok=True)
    if not backup_root.is_dir():
        parser.error("Backup root must be a directory")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_root / ("radar-" + stamp + "-" + uuid.uuid4().hex[:8])
    target.mkdir(mode=0o700)
    restore = target / "restore"
    dryrun = target / "dryrun"
    restore.mkdir(mode=0o700)
    dryrun.mkdir(mode=0o700)

    try:
        backup_sqlite(db, restore / "rent_deals.db")
        safe_copy(deals, restore / "deals.json")
        if vault and vault.is_file():
            safe_copy(vault, restore / "private_contacts.json")
        media_count = backup_media(uploads, restore / "uploads")

        # Keep the restore DB pristine. Only the disposable *dryrun* gets migrations.
        safe_copy(restore / "rent_deals.db", dryrun / "rent_deals.db")
        safe_copy(restore / "deals.json", dryrun / "deals.json")
        (dryrun / "uploads").mkdir(mode=0o700)
        subprocess_env = os.environ.copy()
        subprocess_env.update({
            "APP_ENV": "test",
            "BOT_TOKEN": "123456789:LOCAL_RELEASE_PREFLIGHT_ONLY",
            "TELEGRAM_BOT_TOKEN": "123456789:LOCAL_RELEASE_PREFLIGHT_ONLY",
            "KYIV_RADAR_DB_PATH": str(dryrun / "rent_deals.db"),
            "KYIV_RADAR_DEALS_PATH": str(dryrun / "deals.json"),
            "KYIV_RADAR_UPLOADS_DIR": str(dryrun / "uploads"),
            "KYIV_RADAR_PRIVATE_CONTACTS_PATH": str(restore / "private_contacts.json"),
        })
        proc = subprocess.run(
            [sys.executable, "-c", "from server.kyiv_radar_api import init_db; init_db()"],
            env=subprocess_env, cwd=ROOT, capture_output=True, timeout=45, check=False
        )
        if proc.returncode != 0:
            raise RuntimeError("Disposable database migration failed; production untouched")
        result = inspect_release(
            str(dryrun / "rent_deals.db"),
            str(dryrun / "deals.json"),
            str(dryrun / "uploads")
        )
        summary = {
            "production_changed": False,
            "backup_path": str(target),
            "restore_db_integrity": "ok",
            "media_files_backed_up": media_count,
            "disposable_migration": result
        }
        (target / "manifest.json").write_text(json.dumps(
            summary, ensure_ascii=False, indent=2), encoding="utf-8")
        (target / "manifest.json").chmod(0o600)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if result["ready_for_smoke_test"] else 2
    except Exception as error:
        # Keep the private snapshot for forensic recovery; reveal no data or secrets.
        print(json.dumps({"production_changed": False,
                          "backup_path": str(target),
                          "error_type": type(error).__name__,
                          "release_preflight_passed": False}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
