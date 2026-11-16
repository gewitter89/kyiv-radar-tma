# -*- coding: utf-8 -*-
"""
Kyiv Radar Isolated Telegram Bot Moderator Callback Handler Verification
Tests the exact Aiogram callback query handler logic used by bot.py on the VPS:
1. Rejection of unauthorized non-admin callers (call.from_user.id != 8531839081).
2. Approval sets contactVerified=False initially ("Контакт не перевірено").
3. Separate explicit contact verification action (process_contact_verification) sets contactVerified=True.
4. Two-phase commit: SQLite is not marked published if deals catalog write fails.
5. Strict idempotency: second callback click returns already_approved without duplicating deal in catalog.
"""

import os
import sys
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock

# Add project root to sys.path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from server.bot_moderation import process_landlord_approval, process_contact_verification

class TestModeratorCallbackIsolated(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_rent_deals.db")
        self.deals_path = os.path.join(self.temp_dir.name, "test_deals.json")
        self.admin_id = 8531839081

        # Initialize test SQLite schema
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE landlord_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                address TEXT NOT NULL,
                price TEXT NOT NULL,
                rooms INTEGER NOT NULL,
                phone TEXT NOT NULL,
                gpon INTEGER DEFAULT 0,
                generator INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending_review',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                moderator_notes TEXT,
                contact_verified INTEGER DEFAULT 0,
                verified_at TEXT,
                verification_method TEXT
            )
        """)
        conn.commit()
        conn.close()

        # Initialize base deals catalog
        with open(self.deals_path, "w", encoding="utf-8") as f:
            json.dump([{"id": 1, "title": "Base Deal", "price": 20000}], f)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_callback_authorization_and_idempotency(self):
        # 1. Insert test submission
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO landlord_submissions (address, price, rooms, phone, gpon, generator)
            VALUES ('вул. Хрещатик, 15', '30000', 3, '+380671112233', 1, 1)
        """)
        sub_id = cur.lastrowid
        conn.commit()
        conn.close()

        # 2. Simulate Attacker Callback (Unauthorized)
        mock_attacker_call = MagicMock()
        mock_attacker_call.data = f"ll_approve_{sub_id}"
        mock_attacker_call.from_user.id = 123456789 # Non-admin

        res_attacker = process_landlord_approval(
            sub_id=sub_id,
            caller_id=mock_attacker_call.from_user.id,
            admin_id=self.admin_id,
            db_path=self.db_path,
            deals_path=self.deals_path
        )
        self.assertFalse(res_attacker["success"], "Unauthorized callback must fail!")
        self.assertIn("Доступ заборонено", res_attacker["error"])

        # 3. Simulate Authorized Admin Approval Callback
        mock_admin_call = MagicMock()
        mock_admin_call.data = f"ll_approve_{sub_id}"
        mock_admin_call.from_user.id = self.admin_id

        res_admin = process_landlord_approval(
            sub_id=sub_id,
            caller_id=mock_admin_call.from_user.id,
            admin_id=self.admin_id,
            db_path=self.db_path,
            deals_path=self.deals_path
        )
        self.assertTrue(res_admin["success"], "Admin approval must succeed!")
        self.assertFalse(res_admin["already_approved"], "First approval must not be marked already_approved")

        # Verify deal added to catalog with contactVerified=False (Truthful Decoupling)
        with open(self.deals_path, "r", encoding="utf-8") as f:
            catalog = json.load(f)
        self.assertEqual(len(catalog), 2, "Catalog should now have 2 deals")
        new_deal = catalog[0]
        self.assertEqual(new_deal["submission_id"], sub_id)
        self.assertEqual(new_deal["verificationStatus"], "published_unverified")
        self.assertEqual(new_deal["statusLabel"], "Контакт не перевірено")
        self.assertFalse(new_deal["isOwnerVerified"], "Owner is NOT verified without title deeds")
        self.assertFalse(new_deal["contactVerified"], "Contact is NOT verified upon mere approval!")
        self.assertIsNone(new_deal["realtorCommissionSaved"], "No fake savings allowed!")

        # 4. Separate Explicit Contact Verification Action
        res_verify = process_contact_verification(
            sub_id=sub_id,
            caller_id=self.admin_id,
            admin_id=self.admin_id,
            db_path=self.db_path,
            deals_path=self.deals_path,
            method="phone"
        )
        self.assertTrue(res_verify["success"], "Explicit contact verification must succeed")
        with open(self.deals_path, "r", encoding="utf-8") as f:
            catalog_verified = json.load(f)
        verified_deal = catalog_verified[0]
        self.assertTrue(verified_deal["contactVerified"], "contactVerified MUST be True after explicit verification!")
        self.assertEqual(verified_deal["verificationStatus"], "contact_verified")
        self.assertEqual(verified_deal["phoneVerificationMethod"], "phone")
        self.assertIsNotNone(verified_deal["phoneVerifiedAt"])

        # 5. Simulate Idempotent Repeat Approval Click
        res_repeat = process_landlord_approval(
            sub_id=sub_id,
            caller_id=mock_admin_call.from_user.id,
            admin_id=self.admin_id,
            db_path=self.db_path,
            deals_path=self.deals_path
        )
        self.assertTrue(res_repeat["success"], "Repeat call should be gracefully handled")
        self.assertTrue(res_repeat["already_approved"], "Repeat call MUST be flagged as already_approved")

        # Verify NO duplicate deal was appended to catalog
        with open(self.deals_path, "r", encoding="utf-8") as f:
            catalog_after = json.load(f)
        self.assertEqual(len(catalog_after), 2, "Catalog must remain exactly 2 deals (zero duplicates)!")

        # 6. Two-Phase Failure Test (Corrupted Deals Path)
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO landlord_submissions (address, price, rooms, phone)
            VALUES ('вул. Антоновича, 100', '22000', 1, '+380679998877')
        """)
        fail_sub_id = cur.lastrowid
        conn.commit()
        conn.close()

        res_fail = process_landlord_approval(
            sub_id=fail_sub_id,
            caller_id=self.admin_id,
            admin_id=self.admin_id,
            db_path=self.db_path,
            deals_path="/invalid/non_existent_dir/deals.json"
        )
        self.assertFalse(res_fail["success"], "Must fail when catalog path unwritable")

        # Verify SQLite was NOT updated to published!
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT status FROM landlord_submissions WHERE id = ?", (fail_sub_id,))
        status_after_fail = cur.fetchone()[0]
        conn.close()
        self.assertEqual(status_after_fail, "pending_review", "SQLite MUST NOT be marked published if catalog write fails!")

        print("✓ PASS: Isolated Telegram Callback Handler, Decoupled Contact Verification & Two-Phase Commit Verified")

if __name__ == "__main__":
    unittest.main()
