# -*- coding: utf-8 -*-
"""No network. Contract tests for the post-release read-only verifier."""
import unittest
from scripts.verify_public_release_v132 import check_pages, check_api

HTML = "<html><head><title>Київ Радар — тест</title></head><body><script>const KYIV_DEALS_INIT = [];</script></body></html>"
HEALTH = {"status": "healthy", "version": "1.8.0", "deals_count": 0}


class ReleaseSmokeV132(unittest.TestCase):
    def test_empty_published_site_and_api_are_valid(self):
        check_pages(HTML, [])
        self.assertEqual(check_api(HEALTH, {"success": True, "deals": []}), 0)

    def test_html_with_historical_inventory_is_rejected(self):
        bad = HTML.replace("const KYIV_DEALS_INIT = []",
                           'const KYIV_DEALS_INIT = [{"source":"OLX"}]')
        with self.assertRaisesRegex(AssertionError, "inline catalog"):
            check_pages(bad, [])

    def test_json_with_historical_inventory_is_rejected(self):
        with self.assertRaisesRegex(AssertionError, "static JSON"):
            check_pages(HTML, [{"id": 1}])

    def test_legacy_direct_api_row_is_rejected(self):
        for source in ("OLX", "DOM.RIA", "Unknown"):
            with self.subTest(source=source):
                with self.assertRaisesRegex(AssertionError, "source"):
                    check_api({"status": "healthy", "version": "1.8.0",
                               "deals_count": 1},
                              {"success": True, "deals": [{"id": 1, "source": source,
                                                          "phone": None}]})

    def test_approved_first_party_and_partner_are_accepted(self):
        items = [
            {"id": 11, "source": "Київ Радар (Пряма заявка)", "phone": None},
            {"id": 12, "source": "partner:agency", "phone": None}
        ]
        self.assertEqual(check_api({"status": "healthy", "version": "1.8.0",
                                    "deals_count": 2},
                                   {"success": True, "deals": items}), 2)

    def test_sensitive_fields_cannot_pass(self):
        for key in ("phoneRaw", "initData", "ownerName", "evidence_ref"):
            with self.subTest(key=key):
                with self.assertRaisesRegex(AssertionError, "private fields"):
                    check_api({"status": "healthy", "version": "1.8.0"},
                              {"success": True, "deals": [{
                                  "id": 11, "source": "Київ Радар (Пряма заявка)",
                                  key: "private-test-only"
                              }]})

    def test_count_mismatch_rejected(self):
        with self.assertRaisesRegex(AssertionError, "counts"):
            check_api({"status": "healthy", "version": "1.8.0",
                       "deals_count": 2}, {"success": True, "deals": []})

    def test_no_signed_session_or_external_connection_needed(self):
        # All verifiers are pure functions. The test never invokes main().
        check_pages(HTML, [])
        self.assertEqual(check_api(HEALTH, {"success": True, "deals": []}), 0)


if __name__ == "__main__":
    unittest.main()
