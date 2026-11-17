# -*- coding: utf-8 -*-
"""1.21: rights assertion must precede any photo transfer, with a private audit receipt.

These are isolated browser/API fixtures; they do not demonstrate copyright,
ownership, an actual Telegram landlord, or a production moderation outcome.
"""
import io
import json
import os
import sqlite3
import urllib.parse
from unittest.mock import AsyncMock, patch

import pytest
from playwright.async_api import async_playwright

from server import kyiv_radar_api as api
from tests.test_privacy_and_media import privacy_test_env, create_test_image
from tests.test_user_journeys_isolated import generate_valid_init_data, TEST_BOT_TOKEN

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
URL = "file:///" + os.path.join(ROOT, "index.html").replace("\\", "/")
INIT = "user=%7B%22id%22%3A12345%7D&auth_date=1700000000&hash=mockhash"
TG_URL = URL + "#tgWebAppData=" + urllib.parse.quote(INIT)


def _image_files():
    return [("photos", ("room.jpg", io.BytesIO(create_test_image()), "image/jpeg"))]


def test_upload_requires_declared_rights_before_writing_files(privacy_test_env):
    client = privacy_test_env["client"]
    auth = generate_valid_init_data(TEST_BOT_TOKEN, user_id=80431)

    for form in (
        {"initData": auth},
        {"initData": auth, "rightsConfirmed": "false", "consentVersion": api.LANDLORD_CONSENT_VERSION},
        {"initData": auth, "rightsConfirmed": "true", "consentVersion": "old-unknown-version"},
    ):
        res = client.post("/api/landlords/upload_photos", data=form, files=_image_files())
        assert res.status_code == 400
        assert "права" in res.json()["detail"] or "прав" in res.json()["detail"]
    assert os.listdir(privacy_test_env["uploads_dir"]) == []
    with sqlite3.connect(privacy_test_env["db_path"]) as conn:
        assert conn.execute("SELECT count(*) FROM landlord_uploads").fetchone()[0] == 0

    success = client.post("/api/landlords/upload_photos", data={
        "initData": auth,
        "rightsConfirmed": "true",
        "consentVersion": api.LANDLORD_CONSENT_VERSION,
    }, files=_image_files())
    assert success.status_code == 200
    assert success.json()["success"] is True


def test_submission_stores_private_consent_receipt_atomically(privacy_test_env):
    client = privacy_test_env["client"]
    auth = generate_valid_init_data(TEST_BOT_TOKEN, user_id=80432)
    payload = {
        "address": "вул. Тестова, 10, Київ",
        "price": "15500",
        "rooms": 1,
        "phone": "+380501234567",
        "photos": [],
        "rightsConfirmed": True,
        "initData": auth,
    }
    for bad in ({}, {"consentVersion": "not-supported"}):
        res = client.post("/api/landlords/submit", json={**payload, **bad})
        assert res.status_code == 400
        assert "форм" in res.json()["detail"]
    with sqlite3.connect(privacy_test_env["db_path"]) as conn:
        assert conn.execute("SELECT count(*) FROM landlord_submissions").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM landlord_consent_receipts").fetchone()[0] == 0

    with patch("server.kyiv_radar_api.send_telegram_alert", new_callable=AsyncMock) as alert:
        alert.return_value = True
        res = client.post("/api/landlords/submit", json={
            **payload, "consentVersion": api.LANDLORD_CONSENT_VERSION
        })
    assert res.status_code == 200
    sid = res.json()["id"]
    with sqlite3.connect(privacy_test_env["db_path"]) as conn:
        row = conn.execute(
            "SELECT consent_version,statement_sha256,accepted_at "
            "FROM landlord_consent_receipts WHERE submission_id=?", (sid,)
        ).fetchone()
        assert row is not None
        assert row[0] == api.LANDLORD_CONSENT_VERSION
        assert row[1] == api.LANDLORD_CONSENT_HASH
        assert row[2]
        assert len(row[1]) == 64
        assert "380" not in json.dumps(row)
        assert conn.execute(
            "SELECT status FROM landlord_submissions WHERE id=?", (sid,)
        ).fetchone()[0] == "pending_review"
    assert alert.called


@pytest.mark.asyncio
async def test_mobile_upload_is_blocked_until_checkbox_is_checked():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            viewport={"width": 390, "height": 650}, is_mobile=True, has_touch=True
        )
        calls = []

        async def upload(route):
            body = (route.request.post_data_buffer or b"").decode("latin1")
            calls.append(body)
            await route.fulfill(
                status=200, content_type="application/json",
                body=json.dumps({"success": True, "photos": ["a" * 32]}),
            )

        await page.route("**/api/landlords/upload_photos", upload)
        await page.goto(TG_URL, wait_until="domcontentloaded")
        await page.evaluate(
            "() => document.getElementById('landlordModal').classList.remove('hidden')"
        )
        consent = page.locator("#llRights")
        assert not await consent.is_checked()
        assert await page.locator("#llRightsHelp").is_visible()
        image = {
            "name": "room.png",
            "mimeType": "image/png",
            "buffer": create_test_image(format="PNG", with_exif=False),
        }
        await page.locator("#llPhotoInput").set_input_files(image)
        await page.wait_for_timeout(300)
        assert calls == []
        assert await page.locator("#llPhotoInput").evaluate("(el) => el.files.length") == 0

        await consent.check()
        await page.locator("#llPhotoInput").set_input_files(image)
        await page.wait_for_function("landlordUploadedPhotoIds.length === 1")
        assert len(calls) == 1
        assert "rightsConfirmed" in calls[0] and "true" in calls[0]
        assert api.LANDLORD_CONSENT_VERSION in calls[0]
        assert "Завантажено" in await page.locator("#llPhotoCountLabel").inner_text()
        await page.evaluate("closeLandlordModal()")
        await page.evaluate(
            "() => document.getElementById('landlordModal').classList.remove('hidden')"
        )
        assert not await consent.is_checked(), "No carry-over consent to another submission"
        await page.locator("#llPhotoInput").set_input_files(image)
        await page.wait_for_timeout(150)
        assert len(calls) == 1, "Reopened form must require a fresh rights assertion"
        await browser.close()


@pytest.mark.asyncio
async def test_short_telegram_webview_exposes_agreement_and_submit_with_scroll():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width":320,"height":568},is_mobile=True,has_touch=True)
        await page.goto(TG_URL, wait_until="domcontentloaded")
        await page.evaluate(
            "() => document.getElementById('landlordModal').classList.remove('hidden')"
        )
        scroll = page.locator("#krLandlordScroll")
        assert await scroll.is_visible()
        assert await page.locator("#llRights").count() == 1
        await scroll.evaluate("(el) => el.scrollTop = el.scrollHeight")
        submit = await page.locator("#llSubmitBtn").bounding_box()
        assert submit and submit["height"] >= 44
        assert submit["y"] >= -1 and submit["y"] + submit["height"] <= 569
        await browser.close()
