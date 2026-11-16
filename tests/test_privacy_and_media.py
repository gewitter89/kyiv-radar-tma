# -*- coding: utf-8 -*-
"""
Kyiv Radar Enterprise Privacy & Media Verification Suite
Validates:
1. Public Catalog Privacy: /api/deals NEVER returns raw landlord phone numbers.
2. Landlord Photo Upload: Validates image type, strips all EXIF/GPS metadata, converts to WebP.
3. Upload Security: Rejects non-image files and oversized payloads.
4. Contact Rate Limiting: Blocks more than 10 contact requests per hour per user.
"""

import io
import os
import sys
import json
import time
import tempfile
import pytest
from unittest.mock import patch, AsyncMock
from PIL import Image
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

TEST_BOT_TOKEN = "123456789:TEST_BOT_TOKEN_FOR_HMAC_VALIDATION"
os.environ["BOT_TOKEN"] = TEST_BOT_TOKEN
os.environ["APP_ENV"] = "test"

from server import kyiv_radar_api
from tests.test_user_journeys_isolated import generate_valid_init_data

def create_test_image(format="JPEG", size=(800, 600), color="blue", with_exif=True):
    """Creates an in-memory image with dummy EXIF metadata."""
    img = Image.new("RGB", size, color=color)
    bio = io.BytesIO()
    if format == "JPEG" and with_exif:
        exif = img.getexif()
        exif[0x010E] = "Test Image Description"
        exif[0x0112] = 1 # Normal orientation
        img.save(bio, format="JPEG", exif=exif)
    else:
        img.save(bio, format=format)
    return bio.getvalue()

@pytest.fixture
def privacy_test_env():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        test_db = os.path.join(tmpdir, "test_privacy.db")
        test_deals = os.path.join(tmpdir, "test_deals.json")
        test_priv = os.path.join(tmpdir, "test_priv.json")
        test_uploads = os.path.join(tmpdir, "uploads", "landlords")
        os.makedirs(test_uploads, exist_ok=True)

        deals_data = [
            {
                "id": 1,
                "title": "Квартира #1",
                "address": "вул. Хрещатик, 1",
                "price": 15000,
                "phone": "+380671112233", # Raw phone in disk catalog
                "private_note": "internal moderation note must never be public",
                "ownerName": "private submitter's name",
                "phoneMasked": "+38 (067) •••-••-33",
                "isOwnerVerified": False
            }
        ]
        with open(test_deals, "w", encoding="utf-8") as f:
            json.dump(deals_data, f)

        priv_data = {
            "1": {
                "phone": "+380671112233",
                "ownerName": "Олег",
                "phoneMasked": "+38 (067) •••-••-33"
            }
        }
        with open(test_priv, "w", encoding="utf-8") as f:
            json.dump(priv_data, f)

        orig_db = kyiv_radar_api.DB_PATH
        orig_deals = kyiv_radar_api.DEALS_JSON_PATH
        orig_priv = kyiv_radar_api.PRIVATE_CONTACTS_PATH
        orig_uploads = kyiv_radar_api.UPLOADS_BASE_DIR
        orig_token = kyiv_radar_api.BOT_TOKEN
        orig_env = kyiv_radar_api.APP_ENV

        kyiv_radar_api.DB_PATH = test_db
        kyiv_radar_api.DEALS_JSON_PATH = test_deals
        kyiv_radar_api.PRIVATE_CONTACTS_PATH = test_priv
        kyiv_radar_api.UPLOADS_BASE_DIR = test_uploads
        kyiv_radar_api.BOT_TOKEN = TEST_BOT_TOKEN
        kyiv_radar_api.APP_ENV = "test"

        kyiv_radar_api.init_db()
        client = TestClient(kyiv_radar_api.app)

        yield {
            "client": client,
            "db_path": test_db,
            "deals_path": test_deals,
            "uploads_dir": test_uploads
        }

        kyiv_radar_api.DB_PATH = orig_db
        kyiv_radar_api.DEALS_JSON_PATH = orig_deals
        kyiv_radar_api.PRIVATE_CONTACTS_PATH = orig_priv
        kyiv_radar_api.UPLOADS_BASE_DIR = orig_uploads
        kyiv_radar_api.BOT_TOKEN = orig_token
        kyiv_radar_api.APP_ENV = orig_env

def test_public_catalog_sanitizes_phones(privacy_test_env):
    """GET /api/deals MUST NEVER expose raw phone numbers to anyone."""
    client = privacy_test_env["client"]
    resp = client.get("/api/deals")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert len(data["deals"]) == 1
    # Raw phone must be completely None in public API payload
    assert data["deals"][0]["phone"] is None
    # Masked representation remains safe
    assert data["deals"][0]["phoneMasked"] == "+38 (067) •••-••-33"
    assert "private_note" not in data["deals"][0]
    assert "ownerName" not in data["deals"][0]

def test_photo_upload_valid_exif_stripped(privacy_test_env):
    """POST /api/landlords/upload_photos accepts valid JPEG, strips EXIF, converts to WebP."""
    client = privacy_test_env["client"]
    jpeg_bytes = create_test_image(format="JPEG", with_exif=True)

    files = [
        ("photos", ("living_room.jpg", io.BytesIO(jpeg_bytes), "image/jpeg"))
    ]
    auth = generate_valid_init_data(TEST_BOT_TOKEN, user_id=123456)
    resp = client.post("/api/landlords/upload_photos", data={"initData": auth}, files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["count"] == 1
    photo_id = data["photos"][0]
    assert len(photo_id) == 32 and all(ch in "0123456789abcdef" for ch in photo_id)
    assert client.get(f"/api/media/{photo_id}").status_code == 404

    # Verify that stored file on disk has zero EXIF metadata
    filename = photo_id + ".webp"
    disk_path = os.path.join(privacy_test_env["uploads_dir"], filename)
    assert os.path.exists(disk_path)
    with Image.open(disk_path) as saved_img:
        assert saved_img.format == "WEBP"
        exif = saved_img.getexif()
        assert len(exif) == 0, "All EXIF and GPS tags MUST be completely stripped!"

def test_photo_upload_rejects_non_images(privacy_test_env):
    """POST /api/landlords/upload_photos rejects malicious or non-image files."""
    client = privacy_test_env["client"]
    fake_file = b"This is a text script pretending to be an image."
    files = [
        ("photos", ("malicious.jpg", io.BytesIO(fake_file), "image/jpeg"))
    ]
    auth = generate_valid_init_data(TEST_BOT_TOKEN, user_id=123456)
    resp = client.post("/api/landlords/upload_photos", data={"initData": auth}, files=files)
    assert resp.status_code == 400
    assert "Пошкоджене" in resp.json()["detail"] or "непідтримуване" in resp.json()["detail"]

def test_photo_upload_rejects_too_many(privacy_test_env):
    """POST /api/landlords/upload_photos rejects more than 10 photos in a single batch."""
    client = privacy_test_env["client"]
    jpeg_bytes = create_test_image(format="JPEG", with_exif=False)
    files = [
        ("photos", (f"photo_{i}.jpg", io.BytesIO(jpeg_bytes), "image/jpeg"))
        for i in range(11)
    ]
    auth = generate_valid_init_data(TEST_BOT_TOKEN, user_id=123456)
    resp = client.post("/api/landlords/upload_photos", data={"initData": auth}, files=files)
    assert resp.status_code == 400
    assert "1 до 10 фотографій" in resp.json()["detail"]

def test_send_contact_rate_limiting(privacy_test_env):
    """POST /api/send_contact limits contact requests to 10/hour per user ID."""
    client = privacy_test_env["client"]
    user_id = 99887766
    init_data = generate_valid_init_data(TEST_BOT_TOKEN, user_id=user_id)

    with patch("server.kyiv_radar_api.send_telegram_alert", new_callable=AsyncMock) as mock_alert:
        mock_alert.return_value = True

        for i in range(10):
            resp = client.post("/api/send_contact", json={"dealId": 1, "initData": init_data})
            assert resp.status_code == 200, f"Request {i+1} should succeed"

        # 11th request must be rejected with HTTP 429
        resp_blocked = client.post("/api/send_contact", json={"dealId": 1, "initData": init_data})
        assert resp_blocked.status_code == 429
        assert "Перевищено ліміт запитів контактів" in resp_blocked.json()["detail"]


def test_anonymous_media_upload_and_injected_references_are_rejected(privacy_test_env):
    """Anonymous uploads and arbitrary strings cannot become published photo sources."""
    client = privacy_test_env["client"]
    img_bytes = create_test_image()
    anonymous = client.post(
        "/api/landlords/upload_photos",
        files=[("photos", ("image.jpg", io.BytesIO(img_bytes), "image/jpeg"))]
    )
    assert anonymous.status_code in (401, 422)

    auth = generate_valid_init_data(TEST_BOT_TOKEN, user_id=10001)
    submit = client.post("/api/landlords/submit", json={
        "address": "вул. Глибочицька, 9, Київ",
        "price": "14000", "rooms": 1, "phone": "+380501234567",
        "initData": auth, "rightsConfirmed": True, "photos": ["javascript:alert(1)"]
    })
    assert submit.status_code == 400
    assert "фотографій" in submit.json()["detail"].lower()


def test_photo_ownership_and_moderated_public_access(privacy_test_env):
    """Upload -> private -> owner-bound submission -> moderator approval -> public WebP."""
    from server.bot_moderation import process_landlord_approval

    client = privacy_test_env["client"]
    owner_auth = generate_valid_init_data(TEST_BOT_TOKEN, user_id=20002)
    other_auth = generate_valid_init_data(TEST_BOT_TOKEN, user_id=30003)
    response = client.post(
        "/api/landlords/upload_photos",
        data={"initData": owner_auth},
        files=[("photos", ("room.jpg", io.BytesIO(create_test_image()), "image/jpeg"))]
    )
    assert response.status_code == 200, response.text
    photo_id = response.json()["photos"][0]
    assert client.get("/api/media/" + photo_id).status_code == 404

    payload = {
        "address": "вул. Глибочицька, 12, Київ",
        "price": "17500", "rooms": 1,
        "phone": "+380671234567", "rightsConfirmed": True, "photos": [photo_id]
    }
    with patch("server.kyiv_radar_api.send_telegram_alert", new_callable=AsyncMock) as alert, \
         patch("server.kyiv_radar_api.send_landlord_photo_previews", new_callable=AsyncMock) as previews:
        alert.return_value = True
        previews.return_value = True
        bad = client.post("/api/landlords/submit", json=dict(payload, initData=other_auth))
        assert bad.status_code == 403
        good = client.post("/api/landlords/submit", json=dict(payload, initData=owner_auth))
        assert good.status_code == 200, good.text
        submission_id = good.json()["id"]

    # Submission alone must not disclose the photo on the public endpoint.
    assert client.get("/api/media/" + photo_id).status_code == 404
    accepted = process_landlord_approval(
        submission_id, 555, 555,
        privacy_test_env["db_path"], privacy_test_env["deals_path"]
    )
    assert accepted["success"] is True, accepted
    photo = client.get("/api/media/" + photo_id)
    assert photo.status_code == 200
    assert photo.headers["content-type"].startswith("image/webp")
    assert client.get("/api/media/not-a-valid-uuid").status_code == 404

    catalog = client.get("/api/deals").json()["deals"]
    published = next(x for x in catalog if x["id"] == accepted["published_deal"]["id"])
    assert published["phone"] is None
    assert published["images"] == [
        "https://vmi3445944.contaboserver.net/api/media/" + photo_id
    ]
