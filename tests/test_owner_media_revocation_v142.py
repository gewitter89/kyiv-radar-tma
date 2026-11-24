# -*- coding: utf-8 -*-
"""P0: previously approved landlord photos cannot bypass a listing takedown."""
import json
import os
import sqlite3

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("BOT_TOKEN", "123456789:LOCAL_TEST_MEDIA_GATE")
from server import kyiv_radar_api as api

PHOTO = "b" * 32
OTHER_PHOTO = "c" * 32
SOURCE = "Київ Радар (Пряма заявка)"


@pytest.fixture
def public_photo(tmp_path, monkeypatch):
    db = tmp_path / "private.sqlite"
    catalog = tmp_path / "deals.json"
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    monkeypatch.setattr(api, "DB_PATH", str(db))
    monkeypatch.setattr(api, "DEALS_JSON_PATH", str(catalog))
    monkeypatch.setattr(api, "UPLOADS_BASE_DIR", str(uploads))
    monkeypatch.setattr(api, "REVIEW_REGISTER_PATH", "")
    monkeypatch.setattr(api, "PARTNER_EXPORT_PATH", "")
    monkeypatch.setattr(api, "PARTNER_PUBLICATION_AUTH_PATH", "")
    api.init_db()
    with sqlite3.connect(db) as conn:
        sid = conn.execute(
            "INSERT INTO landlord_submissions "
            "(address, price, rooms, phone, status, photos) VALUES (?,?,?,?,?,?)",
            ("Київ, тест", "10000", 1, "+380000000000", "published",
             json.dumps([PHOTO])),
        ).lastrowid
        conn.execute(
            "INSERT INTO landlord_uploads "
            "(photo_id, owner_telegram_id, submission_id, status) VALUES (?,?,?,?)",
            (PHOTO, 12345, sid, "approved"),
        )
        conn.execute(
            "INSERT INTO landlord_uploads "
            "(photo_id, owner_telegram_id, submission_id, status) VALUES (?,?,?,?)",
            (OTHER_PHOTO, 12345, sid, "approved"),
        )
    (uploads / (PHOTO + ".webp")).write_bytes(b"test-approved-photo")
    (uploads / (OTHER_PHOTO + ".webp")).write_bytes(b"test-other-photo")
    deal = {
        "id": 200, "submission_id": sid, "source": SOURCE,
        "moderationStatus": "approved",
        "title": "Тест", "price": 10000,
        "images": [f"{api.PUBLIC_API_BASE}/api/media/{PHOTO}"],
    }
    catalog.write_text(json.dumps([deal]), encoding="utf-8")
    return TestClient(api.app), db, catalog, uploads, sid, deal


def test_approved_owner_photo_requires_current_public_listing(public_photo):
    client, db, catalog, uploads, sid, deal = public_photo
    endpoint = "/api/media/" + PHOTO
    response = client.get(endpoint)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/webp")
    assert "no-store" in response.headers["cache-control"]

    # Removing the public catalog entry revokes old bookmarked photo URLs.
    catalog.write_text("[]", encoding="utf-8")
    assert client.get(endpoint).status_code == 404
    assert (uploads / (PHOTO + ".webp")).exists()  # Private backup preserved.
    catalog.write_text(json.dumps([deal]), encoding="utf-8")

    # A withdrawn submission revokes media even if static JSON is still stale.
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE landlord_submissions SET status='withdrawn' WHERE id=?", (sid,))
    assert client.get(endpoint).status_code == 404
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE landlord_submissions SET status='published' WHERE id=?", (sid,))

    # Changing the authored photo set is itself a revocation.
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE landlord_submissions SET photos='[]' WHERE id=?", (sid,))
    assert client.get(endpoint).status_code == 404


def test_approved_photo_cannot_be_activated_by_another_listing(public_photo):
    client, db, catalog, uploads, sid, deal = public_photo
    assert client.get("/api/media/" + OTHER_PHOTO).status_code == 404
    # Even if the linked catalog row remains, a new image URL must match
    # the recorded original submission photo list, not just an approved DB flag.
    catalog.write_text(json.dumps([dict(deal,
        images=[f"{api.PUBLIC_API_BASE}/api/media/{OTHER_PHOTO}"])]), encoding="utf-8")
    assert client.get("/api/media/" + OTHER_PHOTO).status_code == 404
    assert client.get("/api/media/" + PHOTO).status_code == 404


def test_private_reviewer_withdrawal_and_db_failure_both_fail_closed(
        public_photo, monkeypatch, tmp_path):
    client, db, catalog, uploads, sid, deal = public_photo
    review = tmp_path / "private_reviews.json"
    review.write_text(json.dumps({
        "schema_version": 1, "listings": {"200": {"state": "withdrawn"}}
    }), encoding="utf-8")
    monkeypatch.setattr(api, "REVIEW_REGISTER_PATH", str(review))
    assert client.get("/api/media/" + PHOTO).status_code == 404

    monkeypatch.setattr(api, "REVIEW_REGISTER_PATH", "")
    monkeypatch.setattr(api, "DB_PATH", str(tmp_path / "missing.sqlite"))
    assert client.get("/api/media/" + PHOTO).status_code == 404


def test_pending_or_malformed_media_stays_private(public_photo):
    client, db, catalog, uploads, sid, deal = public_photo
    assert client.get("/api/media/not-a-uuid").status_code == 404
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE landlord_uploads SET status='pending' WHERE photo_id=?", (PHOTO,))
    assert client.get("/api/media/" + PHOTO).status_code == 404
