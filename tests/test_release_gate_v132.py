# -*- coding: utf-8 -*-
"""Fail-closed distribution checks: no historical or synthetic inventory on site."""
import tempfile
import unittest
from pathlib import Path

from scripts.check_public_distribution import verify


GATE = ('<html><script>const KYIV_DEALS_INIT = [];\n'
        'const source = ""; source.startsWith("partner:"); '
        'source === "київ радар (пряма заявка)";</script></html>')


class PublicDistGateTests(unittest.TestCase):
    def _root(self, html=GATE, data="[]\n"):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        (root / "data").mkdir()
        (root / "index.html").write_text(html, encoding="utf-8")
        (root / "data/deals.json").write_text(data, encoding="utf-8")
        self.addCleanup(temp.cleanup)
        return root

    def test_empty_source_is_valid(self):
        verify(self._root())

    def test_old_embedded_rows_are_rejected(self):
        with self.assertRaisesRegex(AssertionError, "zero inventory"):
            verify(self._root(GATE.replace('KYIV_DEALS_INIT = []',
                 'KYIV_DEALS_INIT = [{"id":1,"source":"OLX"}]')))

    def test_historic_json_records_are_rejected(self):
        with self.assertRaisesRegex(AssertionError, "must be"):
            verify(self._root(data='[{"id":1,"source":"OLX"}]'))

    def test_faked_bundle_from_test_generator_is_rejected(self):
        with self.assertRaises(AssertionError):
            verify(self._root(GATE.replace("KYIV_DEALS_INIT = []",
                     'KYIV_DEALS_INIT = [{"fixtureOnly":true}]')))

    def test_missing_live_eligibility_gate_is_rejected(self):
        with self.assertRaisesRegex(AssertionError, "source eligibility"):
            verify(self._root(GATE.replace('source.startsWith("partner:");', "")))


if __name__ == "__main__":
    unittest.main()
