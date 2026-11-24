# -*- coding: utf-8 -*-
"""Fail-closed source rights regression for all shared public server read paths."""
import sqlite3
from fastapi.testclient import TestClient

from server import kyiv_radar_api as api


def test_source_gate_is_explicit_and_rejects_legacy_or_unreviewed_rows():
    ok = api._is_public_catalog_eligible
    assert not ok({"id": 1, "source": "OLX", "actualityConfirmed": True})
    assert not ok({"id": 2, "source": "DOM.RIA", "reviewedByRadar": True})
    assert not ok({"id": 3, "source": "київ радар", "moderationStatus": "approved"})
    assert not ok({"id": 4, "source": "Київ Радар (Пряма заявка)", "moderationStatus": "pending_review"})
    assert not ok({"id": 4, "source": "Київ Радар (Пряма заявка)", "moderationStatus": "approved"})
    assert not ok({"id": 4, "source": "Київ Радар (Пряма заявка)", "moderationStatus": "approved", "submission_id": True})
    assert not ok({"id": 4, "source": "Київ Радар (Пряма заявка)", "moderationStatus": "approved", "submission_id": 101, "fixtureOnly": True})
    assert ok({"id": 4, "source": "Київ Радар (Пряма заявка)", "moderationStatus": "approved", "submission_id": 101})
    assert ok({"id": 101, "source": "partner:agency_demo"})


def test_legacy_never_reaches_catalog_health_or_contact(monkeypatch):
    archived = {"id": 777, "source": "OLX", "title": "archived synthetic",
                "phone": "+380501112233", "actualityConfirmed": True}
    monkeypatch.setattr(api, "load_trusted_deals", lambda: [archived])
    monkeypatch.setattr(api, "load_private_register", lambda *_: {})
    monkeypatch.setattr(api, "validate_telegram_init_data", lambda _data: {"id": 123})
    monkeypatch.setattr(api, "check_rate_limit", lambda *a, **kwargs: True)
    def deny_private_lookup(*_args):
        raise AssertionError("Legacy record must not reach contact vault")
    monkeypatch.setattr(api, "get_private_contact", deny_private_lookup)

    client = TestClient(api.app)
    response = client.get("/api/deals")
    assert response.status_code == 200
    assert response.json()["deals"] == []
    assert client.get("/api/health").json()["deals_count"] == 0
    contacted = client.post("/api/send_contact", json={"dealId": 777, "initData": "synthetic"})
    assert contacted.status_code == 404


def test_moderated_direct_submission_is_retained_and_sanitized(monkeypatch, tmp_path):
    db = tmp_path / "owner_status.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE landlord_submissions (id INTEGER PRIMARY KEY, status TEXT NOT NULL)")
        conn.execute("INSERT INTO landlord_submissions VALUES (222, 'published')")
    monkeypatch.setattr(api, "DB_PATH", str(db))
    synthetic = {"id": 778, "source": "Київ Радар (Пряма заявка)",
                 "submission_id": 222, "moderationStatus": "approved",
                 "title": "Synthetic owner listing", "price": 10000,
                 "phone": "+380501112233", "ownerName": "private"}
    monkeypatch.setattr(api, "load_trusted_deals", lambda: [synthetic])
    monkeypatch.setattr(api, "load_private_register", lambda *_: {})
    client = TestClient(api.app)
    rows = client.get("/api/deals").json()["deals"]
    assert [r["id"] for r in rows] == [778]
    assert rows[0]["phone"] is None
    assert "ownerName" not in rows[0]
    assert client.get("/api/health").json()["deals_count"] == 1
