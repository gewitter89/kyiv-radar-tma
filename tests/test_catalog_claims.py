# -*- coding: utf-8 -*-
"""Imported catalog must not make unsupported owner or amenity claims."""
import json
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456789:TEST_BOT_TOKEN_FOR_HMAC_VALIDATION")
os.environ.setdefault("APP_ENV", "test")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from server import kyiv_radar_api as api

UNSUPPORTED = [
    "Здається реальна квартира від власника без посередників.",
    "Повний комплект меблів та техніки, інтернет працює стабільно.",
]


def test_json_and_embedded_catalogue_have_zero_fabricated_template_claims():
    deals = json.loads((ROOT / "data" / "deals.json").read_text(encoding="utf-8"))
    assert deals, 'Catalog must not be empty'
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    match = re.search(r"const KYIV_DEALS_INIT = (\[[^\n]+\]);", html)
    assert match, "Expected offline fallback catalog"
    embedded = json.loads(match.group(1))
    assert len(embedded) == len(deals)
    for collection in (deals, embedded):
        for deal in collection:
            for claim in UNSUPPORTED:
                assert claim not in str(deal.get("desc", ""))


def test_historical_unlicensed_import_is_not_published_even_if_api_works(monkeypatch):
    """A stale OLX import must not reach public JSON via a server-side fallback."""
    monkeypatch.setattr(api, "load_trusted_deals", lambda: [{
        "id": 7, "source": "OLX", "isOwnerVerified": False,
        "desc": "Здається реальна квартира від власника без посередників. ",
        "phone": "+380631234567", "ownerName": "private person",
    }])
    resp = TestClient(api.app).get("/api/deals")
    assert resp.status_code == 200
    assert resp.json()["deals"] == []


def test_api_removes_templates_and_raw_phone_for_moderated_first_party(monkeypatch):
    """Positive privacy regression uses a synthetic, approved direct submission."""
    monkeypatch.setattr(api, "load_trusted_deals", lambda: [{
        "id": 7, "source": "Київ Радар (Пряма заявка)",
        "submission_id": 707, "moderationStatus": "approved",
        "isOwnerVerified": False,
        "desc": "Здається реальна квартира від власника без посередників. "
                "Оригінальна назва. "
                "Повний комплект меблів та техніки, інтернет працює стабільно.",
        "phone": "+380631234567", "ownerName": "private person",
    }])
    resp = TestClient(api.app).get("/api/deals")
    assert resp.status_code == 200
    rows = resp.json()["deals"]
    assert len(rows) == 1
    deal = rows[0]
    assert deal["desc"] == "Оригінальна назва."
    assert deal["phone"] is None
    assert "ownerName" not in deal
    assert deal["isOwnerVerified"] is False
