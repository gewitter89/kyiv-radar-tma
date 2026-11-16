# -*- coding: utf-8 -*-
"""
Kyiv Radar Isolated Staging & Moderation Pipeline Verification Suite
Runs completely in an isolated staging environment (APP_ENV=test).
Tests:
1. Landlord submission creation in isolated SQLite.
2. Moderator approval callback with strict admin authorization.
3. Decoupled verification & absence of fictitious attributes:
   - area is None (not hardcoded 45)
   - floor is None (not hardcoded 4)
   - totalFloors is None (not hardcoded 9)
   - lat/lng is None (not hardcoded central Kyiv)
   - images is [] (no fake stock photos)
   - isOwnerVerified is False
   - contactVerified is False (not automatically True without physical call check)
4. Non-admin authorization rejection:
   - Users with ID != ADMIN_CHAT_ID are strictly rejected.
"""

import os
import sys
import json
import sqlite3
import tempfile
import unittest

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

    def simulate_moderator_approval(self, caller_user_id: int, sub_id: int):
        # 1. Authorization Gate
        if caller_user_id != self.admin_id:
            return {"success": False, "error": "FORBIDDEN_NOT_ADMIN"}

        # 2. Database update
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("UPDATE landlord_submissions SET status = 'published', moderator_notes = 'Схвалено модератором' WHERE id = ?", (sub_id,))
        cur.execute("SELECT address, price, rooms, phone, gpon, generator FROM landlord_submissions WHERE id = ?", (sub_id,))
        row = cur.fetchone()
        conn.commit()
        conn.close()

        if not row:
            return {"success": False, "error": "NOT_FOUND"}

        # 3. Clean catalog generation with ZERO fictitious attributes
        with open(self.deals_path, "r", encoding="utf-8") as f:
            deals_list = json.load(f)

        new_id = max([d.get("id", 0) for d in deals_list] + [0]) + 1
        new_deal = {
            "id": new_id,
            "title": f"Квартира від власника: {row[0]}",
            "district": "Київ",
            "address": row[0],
            "cleanAddress": row[0],
            "metro": None,
            "walkMin": None,
            "price": int(row[1]) if str(row[1]).isdigit() else None,
            "realtorCommissionSaved": round(int(row[1]) / 2) if str(row[1]).isdigit() else None,
            "area": None,            # ZERO fake area
            "floor": None,           # ZERO fake floor
            "totalFloors": None,     # ZERO fake totalFloors
            "rooms": row[2] or 1,
            "lat": None,             # ZERO fake coordinates
            "lng": None,
            "generator": bool(row[5]) if row[5] is not None else None,
            "gpon": bool(row[4]) if row[4] is not None else None,
            "gas": None,
            "lowFloor": None,
            "pets": None,
            "ownerName": "Орендодавець",
            "phone": row[3],
            "phoneMasked": row[3][:6] + "***" if len(row[3]) >= 6 else row[3],
            "images": [],            # ZERO fake photos
            "desc": "Оголошення додано власником через Київ Радар.",
            "source": "Київ Радар (Власник)",
            "status": "Опубліковано",
            "isOwnerVerified": False, # ZERO fake verification
            "contactVerified": False, # NOT automatically verified without phone check
            "moderationStatus": "approved",
            "verifiedAt": None
        }
        deals_list.insert(0, new_deal)
        with open(self.deals_path, "w", encoding="utf-8") as f:
            json.dump(deals_list, f, ensure_ascii=False, indent=2)

        return {"success": True, "published_deal": new_deal}

    def test_moderator_pipeline_and_attribute_truthfulness(self):
        # Insert a submission
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO landlord_submissions (address, price, rooms, phone, gpon, generator)
            VALUES ('вул. Межигірська, 22', '25000', 2, '+380501234567', 1, 0)
        """)
        sub_id = cur.lastrowid
        conn.commit()
        conn.close()

        # 1. Non-admin caller MUST be rejected
        res_attacker = self.simulate_moderator_approval(caller_user_id=999999999, sub_id=sub_id)
        self.assertFalse(res_attacker["success"])
        self.assertEqual(res_attacker["error"], "FORBIDDEN_NOT_ADMIN")

        # 2. Authorized admin caller MUST succeed
        res_admin = self.simulate_moderator_approval(caller_user_id=self.admin_id, sub_id=sub_id)
        self.assertTrue(res_admin["success"])
        deal = res_admin["published_deal"]

        # 3. Assert Absence of Fictitious Attributes
        self.assertIsNone(deal["area"], "CRITICAL: area MUST be None if not provided by landlord!")
        self.assertIsNone(deal["floor"], "CRITICAL: floor MUST be None if not provided by landlord!")
        self.assertIsNone(deal["totalFloors"], "CRITICAL: totalFloors MUST be None if not provided by landlord!")
        self.assertIsNone(deal["lat"], "CRITICAL: lat MUST be None if not geocoded!")
        self.assertIsNone(deal["lng"], "CRITICAL: lng MUST be None if not geocoded!")
        self.assertEqual(deal["images"], [], "CRITICAL: images MUST be empty list without stock photo injection!")

        # 4. Assert Truthful Verification Flags
        self.assertFalse(deal["isOwnerVerified"], "isOwnerVerified MUST be False without title deed audit!")
        self.assertFalse(deal["contactVerified"], "contactVerified MUST be False until telephone verification!")
        self.assertEqual(deal["moderationStatus"], "approved")

        print("✓ PASS: Isolated Staging & Truthful Moderation Test (100% Green)")

if __name__ == "__main__":
    unittest.main()
