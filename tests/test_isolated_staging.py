# -*- coding: utf-8 -*-
"""
Kyiv Radar Isolated Staging & Real Moderation Verification Suite
Runs completely in an isolated staging environment (APP_ENV=test).
Directly imports and validates the real production moderation handler:
`server.bot_moderation.process_landlord_approval`.

Tests:
1. Real moderation approval pipeline execution.
2. Strict moderator authorization (only ADMIN_CHAT_ID 8531839081 permitted).
3. Non-admin attacker rejection.
4. Absence of fictitious attributes (area, floor, coordinates, stock photos).
5. Decoupled truthful verification flags (isOwnerVerified=False, contactVerified=False).
"""

import os
import sys
import json
import sqlite3
import tempfile
import unittest

# Add project root to sys.path to import server modules
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from server.bot_moderation import process_landlord_approval

class TestModerationPipelineIsolated(unittest.TestCase):
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

    def test_real_moderator_approval_handler(self):
        # 1. Insert real pending submission into test DB
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO landlord_submissions (address, price, rooms, phone, gpon, generator)
            VALUES ('вул. Межигірська, 22', '25000', 2, '+380501234567', 1, 0)
        """)
        sub_id = cur.lastrowid
        conn.commit()
        conn.close()

        # 2. Test unauthorized caller rejection (e.g. non-admin Telegram user)
        res_attacker = process_landlord_approval(
            sub_id=sub_id,
            caller_id=999999999, # Attacker ID
            admin_id=self.admin_id,
            db_path=self.db_path,
            deals_path=self.deals_path
        )
        self.assertFalse(res_attacker["success"], "Unauthorized caller MUST be rejected!")
        self.assertIn("Доступ заборонено", res_attacker["error"])

        # 3. Test authorized admin approval via real production function
        res_admin = process_landlord_approval(
            sub_id=sub_id,
            caller_id=self.admin_id,
            admin_id=self.admin_id,
            db_path=self.db_path,
            deals_path=self.deals_path
        )
        self.assertTrue(res_admin["success"], f"Admin approval failed: {res_admin}")
        deal = res_admin["published_deal"]

        # 4. Strict assertions: NO fictitious attributes permitted!
        self.assertIsNone(deal["area"], "CRITICAL: area MUST be None if not provided by landlord!")
        self.assertIsNone(deal["floor"], "CRITICAL: floor MUST be None if not provided by landlord!")
        self.assertIsNone(deal["totalFloors"], "CRITICAL: totalFloors MUST be None if not provided by landlord!")
        self.assertIsNone(deal["lat"], "CRITICAL: lat MUST be None without geocoding!")
        self.assertIsNone(deal["lng"], "CRITICAL: lng MUST be None without geocoding!")
        self.assertEqual(deal["images"], [], "CRITICAL: images MUST be empty list without stock photo injection!")

        # 5. Strict assertions: Truthful verification flags
        self.assertFalse(deal["isOwnerVerified"], "isOwnerVerified MUST be False without title deed audit!")
        self.assertFalse(deal["contactVerified"], "contactVerified MUST be False upon initial approval!")
        self.assertEqual(deal["verificationStatus"], "published_unverified")
        self.assertEqual(deal["moderationStatus"], "approved")

        # 5b. Separate Contact Verification Action
        from server.bot_moderation import process_contact_verification
        res_cv = process_contact_verification(
            sub_id=sub_id,
            caller_id=self.admin_id,
            admin_id=self.admin_id,
            db_path=self.db_path,
            deals_path=self.deals_path,
            method="phone"
        )
        self.assertTrue(res_cv["success"], "Explicit contact verification must succeed")
        with open(self.deals_path, "r", encoding="utf-8") as f:
            cat_after_cv = json.load(f)
        self.assertTrue(cat_after_cv[0]["contactVerified"], "contactVerified must be True after verification!")
        self.assertEqual(cat_after_cv[0]["verificationStatus"], "contact_verified")

        # 6. Verify database record updated in SQLite
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT status, moderator_notes FROM landlord_submissions WHERE id = ?", (sub_id,))
        row = cur.fetchone()
        conn.close()
        self.assertEqual(row[0], "published")

        # 7. Verify Idempotency on repeated approval
        res_repeat = process_landlord_approval(
            sub_id=sub_id,
            caller_id=self.admin_id,
            admin_id=self.admin_id,
            db_path=self.db_path,
            deals_path=self.deals_path
        )
        self.assertTrue(res_repeat["success"], "Repeat call handled safely")
        self.assertTrue(res_repeat["already_approved"], "Repeat call must indicate already_approved")

        # Confirm no duplicate deal added to deals.json
        with open(self.deals_path, "r", encoding="utf-8") as f:
            catalog = json.load(f)
        self.assertEqual(len(catalog), 2, "Catalog must remain with exactly 2 deals (zero duplicates)!")

        print("✓ PASS: Real Production Moderation Function Tested in Isolation (100% Truthful & Authorized)")

if __name__ == "__main__":
    unittest.main()
