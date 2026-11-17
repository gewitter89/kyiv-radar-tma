"""Guard against accidental re-publication of personal listing fields.

The GitHub Pages app has two independent client-side listing copies.
Both must be checked: the JSON feed and the large inline initial catalog.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_public_deals_file_contains_no_names_or_raw_contacts():
    listings = json.loads((ROOT / "data" / "deals.json").read_text(encoding="utf-8"))
    assert len(listings) > 0
    assert all("ownerName" not in entry for entry in listings)
    assert all(not entry.get("phone") for entry in listings)


def test_embedded_initial_catalog_does_not_reintroduce_private_fields():
    text = (ROOT / "index.html").read_text(encoding="utf-8")
    match = re.search(r"const KYIV_DEALS_INIT\s*=\s*(\[[^\n]+\]);", text)
    assert match, "Inline fallback catalog was not found"
    listings = json.loads(match.group(1))
    assert len(listings) > 0
    assert all("ownerName" not in entry for entry in listings)
    assert all(not entry.get("phone") for entry in listings)


def test_public_copy_does_not_label_unverified_contact_as_owner():
    text = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "deal.ownerName || 'Власник житла'" not in text
