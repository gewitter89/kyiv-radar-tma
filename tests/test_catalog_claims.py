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


def test_api_blocks_old_import_and_scrubs_first_party_template_claims(monkeypatch):
    unsupported = (
        "Здається реальна квартира від власника без посередників. "
        "Оригінальна назва. "
        "Повний комплект меблів та техніки, інтернет працює стабільно."
    )
    old_import = {
        "id": 7, "source": "OLX", "desc": unsupported,
        "phone": "+380631234567", "ownerName": "private person",
    }
    synthetic_direct = {
        "id": 8, "source": "Київ Радар (Пряма заявка)",
        "submission_id": 8, "moderationStatus": "approved",
        "isOwnerVerified": False, "desc": unsupported,
        "phone": "+380631234567", "ownerName": "private person",
    }
    monkeypatch.setattr(api, "load_trusted_deals",
                        lambda: [old_import, synthetic_direct])
    resp = TestClient(api.app).get("/api/deals")
    assert resp.status_code == 200
    assert [row["id"] for row in resp.json()["deals"]] == [8]
    deal = resp.json()["deals"][0]
    assert deal["desc"] == "Оригінальна назва."
    assert deal["phone"] is None
    assert "ownerName" not in deal
    assert deal["isOwnerVerified"] is False
