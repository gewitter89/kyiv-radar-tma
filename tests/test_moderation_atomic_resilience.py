# -*- coding: utf-8 -*-
"""
Kyiv Radar Moderation Atomic Publishing & Resilience Test Suite
Validates:
1. Compensating transaction rollback: if SQLite commit fails after writing catalog,
   deals.json is restored to exact previous snapshot and success=False is returned.
2. Filesystem write error handling: leaves SQLite in pending_review and returns success=False.
3. Concurrency protection: simultaneous approvals are serialized cleanly without data loss.
4. Contact verification compensating rollback on SQLite failure.
"""

import os
import sys
import json
import sqlite3
import tempfile
import threading
from unittest.mock import patch, MagicMock
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from server.bot_moderation import process_landlord_approval, process_contact_verification

ADMIN_ID = 8531839081

@pytest.fixture
def test_env():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_radar.db")
        deals_path = os.path.join(tmpdir, "deals.json")

        # Initialize SQLite DB
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE landlord_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                address TEXT NOT NULL,
                price TEXT NOT NULL,
                rooms INTEGER DEFAULT 1,
                phone TEXT NOT NULL,
                gpon INTEGER DEFAULT 0,
                generator INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending_review',
                moderator_notes TEXT,
                contact_verified INTEGER DEFAULT 0,
                verified_at TEXT,
                verification_method TEXT
            )
        """)
        cur.execute("""
            INSERT INTO landlord_submissions (id, address, price, rooms, phone, status)
            VALUES (101, 'вул. Саксаганського, 20', '25000', 2, '+380501112233', 'pending_review')
        """)
        cur.execute("""
            INSERT INTO landlord_submissions (id, address, price, rooms, phone, status)
            VALUES (102, 'вул. Рейтарська, 15', '30000', 3, '+380504445566', 'pending_review')
        """)
        conn.commit()
        conn.close()

        # Initialize initial deals.json catalog with 1 baseline item
        initial_deals = [
            {
                "id": 1,
                "title": "Базова квартира",
                "price": 15000,
                "address": "Київ, Центр",
                "phone": "+380500000000",
                "isOwnerVerified": False,
                "contactVerified": False,
                "commissionVerified": False,
                "commissionNote": "Комісія уточнюється"
            }
        ]
        with open(deals_path, 'w', encoding='utf-8') as f:
            json.dump(initial_deals, f, ensure_ascii=False)

        yield {"db_path": db_path, "deals_path": deals_path, "initial_deals": initial_deals}

def test_successful_approval_flow(test_env):
    """Test standard approval publishes deal and updates SQLite."""
    res = process_landlord_approval(
        sub_id=101,
        caller_id=ADMIN_ID,
        admin_id=ADMIN_ID,
        db_path=test_env["db_path"],
        deals_path=test_env["deals_path"]
    )
    assert res["success"] is True
    assert res["already_approved"] is False

    # Check deals.json
    with open(test_env["deals_path"], 'r', encoding='utf-8') as f:
        catalog = json.load(f)
    assert len(catalog) == 2
    published_deal = catalog[0]
    assert published_deal["submission_id"] == 101
    assert published_deal["contactVerified"] is False
    assert published_deal["isOwnerVerified"] is False
    assert published_deal["commissionVerified"] is False
    assert published_deal["commissionNote"] == "Комісія уточнюється"

    # Check DB
    conn = sqlite3.connect(test_env["db_path"])
    cur = conn.cursor()
    cur.execute("SELECT status FROM landlord_submissions WHERE id = 101")
    assert cur.fetchone()[0] == "published"
    conn.close()

def test_sqlite_failure_triggers_compensating_rollback(test_env):
    """
    CRITICAL AUDIT REQUIREMENT:
    If SQLite commit fails after writing catalog, the catalog MUST be rolled back
    to its exact previous snapshot, and the function MUST return success=False.
    """
    deals_path = test_env["deals_path"]
    with open(deals_path, 'r', encoding='utf-8') as f:
        pre_content = f.read()

    # Simulate SQLite execute failure during Phase 2 (status commit)
    original_connect = sqlite3.connect

    class FaultyCursor(sqlite3.Cursor):
        def execute(self, sql, *exec_args, **exec_kwargs):
            if "UPDATE landlord_submissions SET status" in sql:
                raise sqlite3.OperationalError("Simulated database disk I/O failure during commit")
            return super().execute(sql, *exec_args, **exec_kwargs)

    class FaultyConnection(sqlite3.Connection):
        def cursor(self, *args, **kwargs):
            return super().cursor(FaultyCursor)

    with patch("sqlite3.connect", side_effect=lambda *args, **kwargs: original_connect(test_env["db_path"], factory=FaultyConnection)):
        res = process_landlord_approval(
            sub_id=102,
            caller_id=ADMIN_ID,
            admin_id=ADMIN_ID,
            db_path=test_env["db_path"],
            deals_path=deals_path
        )

    # 1. Function must report FAILURE, NOT success!
    assert res["success"] is False
    assert "Помилка фіксації статусу в SQLite" in res["error"]
    assert "Каталог повернуто до початкового стану" in res["error"]

    # 2. deals.json must be restored to its EXACT pre-call state
    with open(deals_path, 'r', encoding='utf-8') as f:
        post_content = f.read()
    assert post_content == pre_content
    catalog = json.loads(post_content)
    assert len(catalog) == 1
    assert not any(d.get("submission_id") == 102 for d in catalog)

    # 3. SQLite record remains pending_review
    conn = sqlite3.connect(test_env["db_path"])
    cur = conn.cursor()
    cur.execute("SELECT status FROM landlord_submissions WHERE id = 102")
    assert cur.fetchone()[0] == "pending_review"
    conn.close()

def test_filesystem_failure_aborts_without_db_change(test_env):
    """If file writing fails, SQLite must remain uncommitted and success=False."""
    with patch("os.replace", side_effect=OSError("Read-only filesystem or disk full")):
        res = process_landlord_approval(
            sub_id=101,
            caller_id=ADMIN_ID,
            admin_id=ADMIN_ID,
            db_path=test_env["db_path"],
            deals_path=test_env["deals_path"]
        )

    assert res["success"] is False
    assert "Помилка збереження у файл каталогу" in res["error"]

    # Check DB remains pending
    conn = sqlite3.connect(test_env["db_path"])
    cur = conn.cursor()
    cur.execute("SELECT status FROM landlord_submissions WHERE id = 101")
    assert cur.fetchone()[0] == "pending_review"
    conn.close()

def test_contact_verification_sqlite_failure_rollback(test_env):
    """Contact verification rolls back catalog if SQLite update fails."""
    # First publish successfully
    process_landlord_approval(101, ADMIN_ID, ADMIN_ID, test_env["db_path"], test_env["deals_path"])

    with open(test_env["deals_path"], 'r', encoding='utf-8') as f:
        catalog_before_ver = json.load(f)
    assert catalog_before_ver[0]["contactVerified"] is False

    original_connect = sqlite3.connect

    class FaultyCursorVer(sqlite3.Cursor):
        def execute(self, sql, *exec_args, **exec_kwargs):
            if "UPDATE landlord_submissions" in sql and "contact_verified" in sql:
                raise sqlite3.OperationalError("Simulated DB lock timeout")
            return super().execute(sql, *exec_args, **exec_kwargs)

    class FaultyConnectionVer(sqlite3.Connection):
        def cursor(self, *args, **kwargs):
            return super().cursor(FaultyCursorVer)

    with patch("sqlite3.connect", side_effect=lambda *args, **kwargs: original_connect(test_env["db_path"], factory=FaultyConnectionVer)):
        res = process_contact_verification(101, ADMIN_ID, ADMIN_ID, test_env["db_path"], test_env["deals_path"], method="phone")

    assert res["success"] is False
    assert "Помилка оновлення бази даних" in res["error"]

    # deals.json must retain contactVerified=False
    with open(test_env["deals_path"], 'r', encoding='utf-8') as f:
        catalog_after = json.load(f)
    assert catalog_after[0]["contactVerified"] is False

def test_concurrency_lock_protection(test_env):
    """Concurrent threads attempting approvals do not corrupt deals.json."""
    results = []

    def run_approval(sub_id):
        res = process_landlord_approval(
            sub_id=sub_id,
            caller_id=ADMIN_ID,
            admin_id=ADMIN_ID,
            db_path=test_env["db_path"],
            deals_path=test_env["deals_path"]
        )
        results.append(res)

    t1 = threading.Thread(target=run_approval, args=(101,))
    t2 = threading.Thread(target=run_approval, args=(102,))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert all(r["success"] is True for r in results)
    with open(test_env["deals_path"], 'r', encoding='utf-8') as f:
        catalog = json.load(f)
    # Both deals must be in catalog without corruption
    assert len(catalog) == 3
    sub_ids = {d.get("submission_id") for d in catalog if "submission_id" in d}
    assert sub_ids == {101, 102}
