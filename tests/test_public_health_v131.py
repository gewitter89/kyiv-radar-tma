# -*- coding: utf-8 -*-
"""v1.31: valid zero-inventory state is not an HTTP/service outage.

This suite does not contact the real production API or write to any database.
"""
import unittest

from scripts.monitor_public_health import verify_public_api, verify_pages_html


HEALTH = {"status": "healthy", "version": "1.5.0"}


class PublicHealthV131Tests(unittest.TestCase):
    def test_zero_inventory_is_valid_structure(self):
        self.assertEqual(verify_public_api(HEALTH, {"success": True, "deals": []}), 0)

    def test_missing_deals_is_not_valid_empty_catalog(self):
        with self.assertRaisesRegex(AssertionError, "deals array"):
            verify_public_api(HEALTH, {"success": True})

    def test_null_deals_is_not_valid_empty_catalog(self):
        with self.assertRaisesRegex(AssertionError, "deals array"):
            verify_public_api(HEALTH, {"success": True, "deals": None})

    def test_false_success_is_failure_even_when_empty(self):
        with self.assertRaisesRegex(AssertionError, "unsuccessful"):
            verify_public_api(HEALTH, {"success": False, "deals": []})

    def test_unhealthy_api_is_not_misclassified_as_empty(self):
        with self.assertRaisesRegex(AssertionError, "not healthy"):
            verify_public_api({"status": "down", "version": "1.5.0"},
                              {"success": True, "deals": []})

    def test_empty_version_is_invalid(self):
        with self.assertRaisesRegex(AssertionError, "invalid version"):
            verify_public_api({"status": "healthy", "version": ""},
                              {"success": True, "deals": []})

    def test_valid_visible_deal_count(self):
        self.assertEqual(verify_public_api(HEALTH, {"success": True, "deals": [
            {"id": 1, "phone": None}, {"id": 2}
        ]}), 2)

    def test_duplicate_ids_are_rejected(self):
        with self.assertRaisesRegex(AssertionError, "duplicated"):
            verify_public_api(HEALTH, {"success": True, "deals": [
                {"id": 1}, {"id": 1}
            ]})

    def test_private_fields_are_still_rejected(self):
        for secret_key in ("ownerName", "private_note", "initData"):
            with self.subTest(secret_key=secret_key):
                with self.assertRaises(AssertionError):
                    verify_public_api(HEALTH, {"success": True, "deals": [
                        {"id": 1, secret_key: "synthetic-secret"}
                    ]})

    def test_title_still_required(self):
        verify_pages_html("<html><head><title>Київ Радар</title></head></html>")
        with self.assertRaises(AssertionError):
            verify_pages_html("<html><title>Wrong site</title></html>")


if __name__ == "__main__":
    unittest.main()
