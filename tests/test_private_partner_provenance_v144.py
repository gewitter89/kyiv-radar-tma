# -*- coding: utf-8 -*-
"""Partner metadata must originate from private authorization, never static JSON."""
import json
import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("BOT_TOKEN", "123456789:LOCAL_PROVENANCE_TEST")
from server import kyiv_radar_api as api


def direct_owner(item_id=10):
    return {
        "id": item_id, "source": "Київ Радар (Пряма заявка)",
        "submission_id": 300, "moderationStatus": "approved",
        "title": "Тест без реальних адрес", "price": 10000,
    }


def partner(item_id=20):
    return {
        "id": item_id, "source": "partner:agency",
        "partnerSourceKey": "agency", "partnerExternalId": "P-20",
        "url": "https://agency.example.test/p/20", "price": 10000,
        "actualityConfirmed": True, "reviewedByRadar": True,
    }


def test_static_json_cannot_inject_partner_even_with_review_flags(tmp_path, monkeypatch):
    static = tmp_path / "catalog.json"
    fake = partner()
    stealth = dict(direct_owner(21), partnerExternalId="P-21")
    static.write_text(json.dumps([
        direct_owner(), fake, stealth,
        {"id": 22, "source": "PARTNER:agency", "price": 10000},
        {"id": 23, "source": "OLX", "actualityConfirmed": True},
    ], ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(api, "DEALS_JSON_PATH", str(static))
    monkeypatch.setattr(api, "PARTNER_EXPORT_PATH", "")
    monkeypatch.setattr(api, "PARTNER_PUBLICATION_AUTH_PATH", "")
    loaded = api.load_trusted_deals()
    assert [row["id"] for row in loaded] == [10, 23]
    # Even forged two-flag legacy listings cannot become public.
    assert [row["id"] for row in api.load_effective_deals()] == [10]


def test_only_private_receipt_export_can_add_partner(tmp_path, monkeypatch):
    static = tmp_path / "catalog.json"
    static.write_text(json.dumps([direct_owner(), partner(30)], ensure_ascii=False),
                      encoding="utf-8")
    monkeypatch.setattr(api, "DEALS_JSON_PATH", str(static))
    monkeypatch.setattr(api, "PARTNER_EXPORT_PATH", str(tmp_path / "off_web_export.json"))
    monkeypatch.setattr(api, "PARTNER_PUBLICATION_AUTH_PATH",
                        str(tmp_path / "off_web_rights.json"))
    calls = []
    def authorized_export(export_path, rights_path):
        calls.append((export_path, rights_path))
        return [partner(30)]
    monkeypatch.setattr(api, "read_private_export", authorized_export)
    loaded = api.load_trusted_deals()
    assert [row["id"] for row in loaded] == [10, 30]
    assert calls == [(api.PARTNER_EXPORT_PATH, api.PARTNER_PUBLICATION_AUTH_PATH)]


def test_no_receipt_means_no_partner_read_and_duplicate_owner_ids_win(
        tmp_path, monkeypatch):
    static = tmp_path / "catalog.json"
    static.write_text(json.dumps([direct_owner(30), partner(40)], ensure_ascii=False))
    monkeypatch.setattr(api, "DEALS_JSON_PATH", str(static))
    monkeypatch.setattr(api, "PARTNER_EXPORT_PATH", str(tmp_path / "export.json"))
    monkeypatch.setattr(api, "PARTNER_PUBLICATION_AUTH_PATH", "")
    def forbidden(*args):
        raise AssertionError("No external export without both private paths")
    monkeypatch.setattr(api, "read_private_export", forbidden)
    assert [row["id"] for row in api.load_trusted_deals()] == [30]

    # With authorization, a partner may not replace a first-party row ID.
    monkeypatch.setattr(api, "PARTNER_PUBLICATION_AUTH_PATH", str(tmp_path / "rights.json"))
    monkeypatch.setattr(api, "read_private_export", lambda *_: [partner(30), partner(50)])
    rows = api.load_trusted_deals()
    assert [x["id"] for x in rows] == [30, 50]
    assert rows[0]["source"] == "Київ Радар (Пряма заявка)"
