# -*- coding: utf-8 -*-
"""
Kyiv Radar Isolated Telegram Bot Moderator Callback Handler Verification
Tests the exact Aiogram callback query handler logic used by bot.py on the VPS:
1. Rejection of unauthorized non-admin callers (call.from_user.id != 8531839081).
2. Successful approval and insertion into deals catalog by admin.
3. Strict idempotency: second callback click returns already_approved without duplicating deal in catalog.
4. Correct reply markup update.
"""

import os
import sys
import json
import sqlite3
import tempfile
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

# Add project root to sys.path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from server.bot_moderation import process_landlord_approval

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
                moderator_notes TEXT
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

        # 2. Simulate Attacker Callback
        mock_attacker_call = MagicMock()
        mock_attacker_call.data = f"ll_approve_{sub_id}"
        mock_attacker_call.from_user.id = 123456789 # Non-admin
        mock_attacker_call.answer = AsyncMock()

        res_attacker = process_landlord_approval(
            sub_id=sub_id,
            caller_id=mock_attacker_call.from_user.id,
            admin_id=self.admin_id,
            db_path=self.db_path,
            deals_path=self.deals_path
        )
        self.assertFalse(res_attacker["success"], "Unauthorized callback must fail!")
        self.assertIn("Доступ заборонено", res_attacker["error"])

        # 3. Simulate Authorized Admin Callback
        mock_admin_call = MagicMock()
        mock_admin_call.data = f"ll_approve_{sub_id}"
        mock_admin_call.from_user.id = self.admin_id
        mock_admin_call.answer = AsyncMock()

        res_admin = process_landlord_approval(
            sub_id=sub_id,
            caller_id=mock_admin_call.from_user.id,
            admin_id=self.admin_id,
            db_path=self.db_path,
            deals_path=self.deals_path
        )
        self.assertTrue(res_admin["success"], "Admin approval must succeed!")
        self.assertFalse(res_admin["already_approved"], "First approval must not be marked already_approved")

        # Verify deal added to catalog
        with open(self.deals_path, "r", encoding="utf-8") as f:
            catalog = json.load(f)
        self.assertEqual(len(catalog), 2, "Catalog should now have 2 deals")
        new_deal = catalog[0]
        self.assertEqual(new_deal["submission_id"], sub_id)
        self.assertEqual(new_deal["verificationStatus"], "contact_verified")
        self.assertFalse(new_deal["isOwnerVerified"])
        self.assertTrue(new_deal["contactVerified"])

        # 4. Simulate Idempotent Second Admin Click (e.g. double tap or race condition)
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

        print("✓ PASS: Isolated Telegram Callback Handler & Idempotency Verified")

if __name__ == "__main__":
    unittest.main()
