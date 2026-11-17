# -*- coding: utf-8 -*-
"""Verify the VPS release-prep script never mutates the source or exposes data."""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from tests.test_privacy_and_media import privacy_test_env


def test_vps_release_preparation_backs_up_and_migrates_only_copy(privacy_test_env, tmp_path):
    db = Path(privacy_test_env["db_path"])
    catalog = Path(privacy_test_env["deals_path"])
    uploads = Path(privacy_test_env["uploads_dir"])
    data = json.loads(catalog.read_text(encoding="utf-8"))
    for listing in data:
        listing["phone"] = None
        listing.pop("ownerName", None)
    catalog.write_text(json.dumps(data), encoding="utf-8")

    photo = uploads / ("f" * 32 + ".webp")
    photo.write_bytes(b"private test image")
    original_catalog = catalog.read_bytes()
    backup_root = tmp_path / "backups"
    backup_root.mkdir(mode=0o700)
    command = [
        sys.executable, "scripts/prepare_vps_release.py",
        "--db", str(db), "--deals", str(catalog),
        "--uploads", str(uploads), "--backup-root", str(backup_root)
    ]
    process = subprocess.run(
        command, cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, timeout=90, check=False
    )
    assert process.returncode == 0, process.stderr
    report = json.loads(process.stdout)
    assert report["production_changed"] is False
    assert report["disposable_migration"]["ready_for_smoke_test"] is True
    assert report["media_files_backed_up"] == 1

    snapshot = Path(report["backup_path"])
    assert snapshot.is_relative_to(backup_root)
    assert (snapshot / "restore" / "deals.json").read_bytes() == original_catalog
    assert catalog.read_bytes() == original_catalog
    assert (snapshot / "restore" / "uploads" / photo.name).read_bytes() == photo.read_bytes()
    assert os.stat(snapshot).st_mode & 0o077 == 0
    assert os.stat(snapshot / "restore" / "rent_deals.db").st_mode & 0o077 == 0

    with sqlite3.connect(snapshot / "restore" / "rent_deals.db") as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    with sqlite3.connect(snapshot / "dryrun" / "rent_deals.db") as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(landlord_submissions)")}
        assert {"submitter_id", "contact_verified", "verified_at"}.issubset(cols)


def test_release_preparation_rejects_public_backup_directory(privacy_test_env, tmp_path):
    directory = tmp_path / "public"
    directory.mkdir(mode=0o755)
    directory.chmod(0o755)  # Do not rely on CI runner umask.
    command = [
        sys.executable, "scripts/prepare_vps_release.py",
        "--db", privacy_test_env["db_path"],
        "--deals", privacy_test_env["deals_path"],
        "--uploads", privacy_test_env["uploads_dir"],
        "--backup-root", str(directory)
    ]
    process = subprocess.run(
        command, cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, timeout=30, check=False
    )
    assert process.returncode != 0
    assert list(directory.iterdir()) == []
