# -*- coding: utf-8 -*-
"""v1.31: Telegram identity, consented cloud favorites and conflict safety."""
import hashlib
import hmac
import json
import sqlite3
import time
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from server import kyiv_radar_api as api

VALID = "kr2|olx|https://www.olx.ua/d/uk/obyavlenie/safe-offer-IDabc.html"
VALID2 = "kr2|partner%3Aagency|https://agency.example.ua/offer?id=123"


def signed(user_id, *, seconds_ago=0, tamper=False):
    params = {
        "auth_date": str(int(time.time()) - seconds_ago),
        "query_id": "AAE123",
        "user": json.dumps({"id": user_id, "first_name": "Tester"}, separators=(",", ":")),
    }
    check = "\n".join(f"{k}={params[k]}" for k in sorted(params))
    secret = hmac.new(b"WebAppData", api.BOT_TOKEN.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    params["hash"] = digest
    if tamper:
        params["user"] = json.dumps({"id": user_id + 1}, separators=(",", ":"))
    return urllib.parse.urlencode(params)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "BOT_TOKEN", "123456789:THIS_IS_ONLY_A_TEST_BOT_TOKEN")
    monkeypatch.setattr(api, "FAVORITES_SYNC_ENABLED", True)
    monkeypatch.setattr(api, "DB_PATH", str(tmp_path / "private_app.sqlite"))
    monkeypatch.setattr(api, "PRIVATE_CONTACTS_PATH", str(tmp_path / "no_contacts.json"))
    api.init_db()
    return TestClient(api.app)


def state(client, uid):
    return client.post("/api/favorites/state", json={"initData": signed(uid)})


def replace(client, uid, current, keys):
    return client.post("/api/favorites/replace", json={
        "initData": signed(uid),
        "generation": current["generation"],
        "revision": current["revision"],
        "keys": keys
    })


def test_cloud_sync_is_disabled_until_production_privacy_gate(client, monkeypatch):
    monkeypatch.setattr(api, "FAVORITES_SYNC_ENABLED", False)
    assert state(client, 41).status_code == 503


def test_signed_telegram_account_isolated_on_two_devices(client):
    first = state(client, 111)
    assert first.status_code == 200
    assert "no-store" in first.headers["cache-control"]
    snapshot = first.json()
    assert snapshot["revision"] == 0 and snapshot["keys"] == []
    saved = replace(client, 111, snapshot, [VALID])
    assert saved.status_code == 200
    assert saved.json()["revision"] == 1
    assert state(client, 111).json()["keys"] == [VALID]
    assert state(client, 222).json()["keys"] == []
    assert state(client, 222).json()["generation"] != snapshot["generation"]


def test_stale_device_cannot_overwrite_or_resurrect_removed_saved_listing(client):
    old = state(client, 333).json()
    # Device A saves a listing, device B still holds the old revision.
    assert replace(client, 333, old, [VALID]).status_code == 200
    old_response = replace(client, 333, old, [VALID2])
    assert old_response.status_code == 409
    assert state(client, 333).json()["keys"] == [VALID]
    fresh = state(client, 333).json()
    assert replace(client, 333, fresh, []).status_code == 200
    # A stale offline browser cannot silently upload its previous old snapshot.
    assert replace(client, 333, fresh, [VALID]).status_code == 409
    assert state(client, 333).json()["keys"] == []


@pytest.mark.parametrize("key", [
    "123",
    "kr2|olx|http://www.olx.ua/offer/a",
    "kr2|olx|https://localhost/offer/a",
    "kr2|olx|https://www.olx.ua/",
    "kr2|olx|https://www.olx.ua/offer?auth_token=secret",
    "kr2|olx|https://user:secret@www.olx.ua/offer",
    "kr2|olx|https://www.olx.ua/offer#secret",
    "kr2||https://www.olx.ua/offer",
])
def test_server_rejects_untrusted_keys(client, key):
    snapshot = state(client, 444).json()
    response = replace(client, 444, snapshot, [key])
    assert response.status_code == 422
    assert state(client, 444).json()["keys"] == []


def test_server_rejects_duplicates_and_overflow(client):
    snapshot = state(client, 555).json()
    assert replace(client, 555, snapshot, [VALID, VALID]).status_code == 422
    many = [f"kr2|olx|https://www.olx.ua/d/offer-{i}" for i in range(301)]
    assert replace(client, 555, snapshot, many).status_code == 422
    assert state(client, 555).json()["keys"] == []


def test_rejects_forged_expired_and_duplicate_telegram_init_data(client):
    assert client.post("/api/favorites/state",
                       json={"initData": signed(1, tamper=True)}).status_code == 401
    assert client.post("/api/favorites/state",
                       json={"initData": signed(1, seconds_ago=7200)}).status_code == 401
    init = signed(1) + "&user=%7B%22id%22%3A99999%7D"
    assert client.post("/api/favorites/state", json={"initData": init}).status_code == 401
    assert client.post("/api/favorites/state", json={"initData": "user=%7B%22id%22%3A1%7D"}).status_code == 401
    assert client.post("/api/favorites/state",
                       json={"initData": signed(True)}).status_code == 401


def test_explicit_account_purge_erases_rows_and_invalidates_old_devices(client):
    current = state(client, 777).json()
    assert replace(client, 777, current, [VALID, VALID2]).status_code == 200
    denied = client.post("/api/favorites/purge", json={
        "initData": signed(777), "generation": current["generation"],
        "confirmDelete": False
    })
    assert denied.status_code == 400
    purge = client.post("/api/favorites/purge", json={
        "initData": signed(777), "generation": current["generation"],
        "confirmDelete": True
    })
    assert purge.status_code == 200
    assert purge.json()["keys"] == []
    assert purge.json()["generation"] != current["generation"]
    assert replace(client, 777, current, [VALID]).status_code == 409
    latest = state(client, 777).json()
    assert latest["keys"] == []
    with sqlite3.connect(api.DB_PATH) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM favorite_sync_keys WHERE telegram_user_id=777"
        ).fetchone()[0] == 0


def test_only_public_permalink_keys_are_stored_without_personal_details(client):
    current = state(client, 888).json()
    response = replace(client, 888, current, [VALID, VALID2])
    assert response.status_code == 200
    assert "phone" not in response.text and "first_name" not in response.text
    with sqlite3.connect(api.DB_PATH) as conn:
        tables = conn.execute(
            "SELECT stable_identity FROM favorite_sync_keys WHERE telegram_user_id=888 ORDER BY stable_identity"
        ).fetchall()
    assert {row[0] for row in tables} == {VALID, VALID2}
