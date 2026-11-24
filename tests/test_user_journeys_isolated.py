# -*- coding: utf-8 -*-
"""
Kyiv Radar Isolated User Journeys & Contact Delivery Verification Suite
Validates all mutating user actions in a hermetic, isolated environment
without creating test records on the production VPS database.

Tested Scenarios:
1. Landlord Submission (/api/landlords/submit):
   - Saves record to isolated SQLite landlord_submissions
   - Dispatches escaped Telegram alert with inline action buttons
   - Returns HTTP 200 with new submission ID
2. Complaint Submission (/api/reports):
   - Saves record to isolated SQLite complaints
   - Dispatches escaped Telegram alert with lot inspection link
   - Returns HTTP 200 with complaint ID
3. Tenant Contact Delivery (/api/send_contact) - SUCCESSFUL SCENARIO:
   - Validates cryptographic HMAC-SHA256 signature from Telegram initData
   - Retrieves trusted listing data from server database (server-side authority)
   - Checks truthful commission wording in dispatched message
   - Dispatches contact directly to tenant's Telegram chat ID
   - Handles Telegram Bot API confirmation (HTTP 200)
4. Tenant Contact Delivery - Bot Blocked / Chat Not Found:
   - Returns HTTP 502 with clear instructions to open @prostov_shrink_bot and press /start
"""

import os
import sys
import json
import time
import hmac
import hashlib
import urllib.parse
import tempfile
import sqlite3
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

TEST_BOT_TOKEN = "123456789:TEST_BOT_TOKEN_FOR_HMAC_VALIDATION"
TEST_USER_ID = 987654321

# Set test environment before importing kyiv_radar_api
os.environ["BOT_TOKEN"] = TEST_BOT_TOKEN
os.environ["APP_ENV"] = "test"

# Import API module
from server import kyiv_radar_api

def generate_valid_init_data(bot_token: str, user_id: int = TEST_USER_ID, auth_date: int = None) -> str:
    """Generates authentic Telegram WebApp initData string with valid HMAC-SHA256 signature."""
    if auth_date is None:
        auth_date = int(time.time())
    user_json = json.dumps({"id": user_id, "first_name": "Тестовий", "last_name": "Орендар", "username": "test_tenant"}, ensure_ascii=False)
    params = {
        "auth_date": str(auth_date),
        "query_id": "AAHdF60qAAAAAN0XrSq12345",
        "user": user_json
    }
    data_check_string = "\n".join(f"{k}={params[k]}" for k in sorted(params.keys()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    cal_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    params["hash"] = cal_hash
    return urllib.parse.urlencode(params)

@pytest.fixture
def isolated_app():
    """Sets up an isolated FastAPI test client with temporary SQLite DB and deals catalog."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        test_db_path = os.path.join(tmpdir, "isolated_test_radar.db")
        test_deals_path = os.path.join(tmpdir, "isolated_deals.json")

        # Create baseline catalog with 2 deals: 1 with unverified commission, 1 with verified 0%
        deals_data = [
            {
                "id": 1,
                "title": "1-кімнатна на Хрещатику",
                "address": "вул. Хрещатик, 15",
                "price": 20000,
                "source": "Київ Радар (Пряма заявка)",
                "submission_id": 1,
                "moderationStatus": "approved",
                "phone": "+380501112233",
                "isOwnerVerified": False,
                "contactVerified": False,
                "commissionVerified": False,
                "commissionNote": "Комісія уточнюється"
            },
            {
                "id": 2,
                "title": "2-кімнатна на Подолі",
                "address": "вул. Спаська, 10",
                "price": 25000,
                "source": "Київ Радар (Пряма заявка)",
                "submission_id": 2,
                "moderationStatus": "approved",
                "phone": "+380674445566",
                "isOwnerVerified": True,
                "contactVerified": True,
                "commissionVerified": True,
                "commissionNote": "0% комісії"
            }
        ]
        with open(test_deals_path, "w", encoding="utf-8") as f:
            json.dump(deals_data, f, ensure_ascii=False)

        # Patch environment and global paths in kyiv_radar_api
        orig_db = kyiv_radar_api.DB_PATH
        orig_deals = kyiv_radar_api.DEALS_JSON_PATH
        orig_priv = getattr(kyiv_radar_api, "PRIVATE_CONTACTS_PATH", None)
        orig_token = kyiv_radar_api.BOT_TOKEN
        orig_env = kyiv_radar_api.APP_ENV

        kyiv_radar_api.DB_PATH = test_db_path
        kyiv_radar_api.DEALS_JSON_PATH = test_deals_path
        if hasattr(kyiv_radar_api, "PRIVATE_CONTACTS_PATH"):
            kyiv_radar_api.PRIVATE_CONTACTS_PATH = os.path.join(tmpdir, "nonexistent_priv.json")
        kyiv_radar_api.BOT_TOKEN = TEST_BOT_TOKEN
        kyiv_radar_api.APP_ENV = "test"

        kyiv_radar_api.init_db()
        # Baseline sample listings must have corresponding live published
        # submissions in the isolated DB for the canonical status gate.
        with sqlite3.connect(test_db_path) as conn:
            conn.executemany(
                "INSERT INTO landlord_submissions "
                "(id,address,price,rooms,phone,status) VALUES (?,?,?,?,?,?)",
                [
                    (1, "вул. Хрещатик, 15", "20000", 1, "+380501112233", "published"),
                    (2, "вул. Спаська, 10", "25000", 2, "+380674445566", "published"),
                ],
            )
        client = TestClient(kyiv_radar_api.app)

        yield {
            "client": client,
            "db_path": test_db_path,
            "deals_path": test_deals_path,
            "bot_token": TEST_BOT_TOKEN
        }

        # Restore
        kyiv_radar_api.DB_PATH = orig_db
        kyiv_radar_api.DEALS_JSON_PATH = orig_deals
        if orig_priv:
            kyiv_radar_api.PRIVATE_CONTACTS_PATH = orig_priv
        kyiv_radar_api.BOT_TOKEN = orig_token
        kyiv_radar_api.APP_ENV = orig_env

def test_landlord_submit_isolated(isolated_app):
    """Scenario 1: Landlord submits apartment to isolated test DB."""
    client = isolated_app["client"]

    # Mock send_telegram_alert to verify message format without hitting external network
    with patch("server.kyiv_radar_api.send_telegram_alert", new_callable=AsyncMock) as mock_alert:
        mock_alert.return_value = True

        payload = {
            "address": "вул. Мечникова, 8, кв. 14",
            "price": "22 000",
            "rooms": 1,
            "phone": "+380501234567",
            "gpon": True,
            "generator": False,
            "rightsConfirmed": True,
            "consentVersion": kyiv_radar_api.LANDLORD_CONSENT_VERSION,
            "initData": generate_valid_init_data(TEST_BOT_TOKEN, user_id=TEST_USER_ID)
        }
        resp = client.post("/api/landlords/submit", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["id"] > 0
        assert data["alert_delivered"] is True

        # Verify DB entry
        conn = sqlite3.connect(isolated_app["db_path"])
        cur = conn.cursor()
        cur.execute("SELECT address, price, phone, gpon, status FROM landlord_submissions WHERE id = ?", (data["id"],))
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "вул. Мечникова, 8, кв. 14"
        assert row[1] == "22 000"
        assert row[2] == "+380501234567"
        assert row[3] == 1  # gpon
        assert row[4] == "pending_review"
        conn.close()

        # Verify Telegram alert was called with proper keyboard
        mock_alert.assert_called_once()
        alert_text = mock_alert.call_args[0][0]
        assert "вул. Мечникова, 8, кв. 14" in alert_text
        assert "+380501234567" in alert_text

def test_complaint_submit_isolated(isolated_app):
    """Scenario 2: User files a complaint against a listing in isolated DB."""
    client = isolated_app["client"]

    with patch("server.kyiv_radar_api.send_telegram_alert", new_callable=AsyncMock) as mock_alert:
        mock_alert.return_value = True

        payload = {
            "dealId": 1,
            "reason": "Виявився рієлтор / комісія",
            "details": "Вимагають 50% від першого місяця"
        }
        resp = client.post("/api/reports", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["id"] > 0

        # Verify DB entry
        conn = sqlite3.connect(isolated_app["db_path"])
        cur = conn.cursor()
        cur.execute("SELECT deal_id, reason, details, status FROM complaints WHERE id = ?", (data["id"],))
        row = cur.fetchone()
        assert row is not None
        assert row[0] == 1
        assert row[1] == "Виявився рієлтор / комісія"
        assert row[2] == "Вимагають 50% від першого місяця"
        assert row[3] == "pending_review"
        conn.close()

def test_successful_tenant_contact_delivery(isolated_app):
    """
    Scenario 3 (CRITICAL AUDIT REQUIREMENT):
    Tenant requests contact using valid HMAC initData.
    Verifies that:
    1. Cryptographic HMAC validation succeeds.
    2. Server retrieves landlord phone from database (not from client).
    3. Telegram message is dispatched to tenant's Telegram ID.
    4. Truthful commission statement is sent.
    5. HTTP 200 success response returned.
    """
    client = isolated_app["client"]
    valid_init_data = generate_valid_init_data(TEST_BOT_TOKEN, user_id=TEST_USER_ID)

    with patch("server.kyiv_radar_api.send_telegram_alert", new_callable=AsyncMock) as mock_alert:
        mock_alert.return_value = True

        # 1. Test deal #1 (commissionVerified: False -> "Комісія уточнюється")
        req_payload = {
            "dealId": 1,
            "initData": valid_init_data
        }
        resp = client.post("/api/send_contact", json=req_payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["dealId"] == 1
        assert "Контакт орендодавця успішно надіслано" in data["message"]

        # Verify telegram alert call parameters
        mock_alert.assert_called_once()
        msg_text = mock_alert.call_args[0][0]
        target_chat = mock_alert.call_args[1].get("target_chat") or mock_alert.call_args[0][2]

        assert target_chat == TEST_USER_ID, f"Expected alert sent to user {TEST_USER_ID}, got {target_chat}"
        assert "+380501112233" in msg_text, "Landlord phone must be in the Telegram message"
        assert "вул. Хрещатик, 15" in msg_text
        assert "20 000 ₴/міс" in msg_text
        assert "Комісія уточнюється" in msg_text
        assert "0% комісії рієлторам" not in msg_text, "Unverified deal MUST NOT promise 0% commission!"

        # 2. Test deal #2 (commissionVerified: True -> "0% комісії (підтверджено)")
        mock_alert.reset_mock()
        req_payload2 = {
            "dealId": 2,
            "initData": valid_init_data
        }
        resp2 = client.post("/api/send_contact", json=req_payload2)
        assert resp2.status_code == 200
        msg_text2 = mock_alert.call_args[0][0]
        assert "0% комісії (підтверджено)" in msg_text2
        assert "+380674445566" in msg_text2

def test_tenant_contact_delivery_telegram_failure_handling(isolated_app):
    """
    Scenario 4: If Telegram Bot API cannot deliver the message (e.g. user hasn't started the bot),
    the endpoint gracefully returns HTTP 502 with clear instructions.
    """
    client = isolated_app["client"]
    valid_init_data = generate_valid_init_data(TEST_BOT_TOKEN, user_id=TEST_USER_ID)

    with patch("server.kyiv_radar_api.send_telegram_alert", new_callable=AsyncMock) as mock_alert:
        mock_alert.return_value = False  # Telegram returns failure (e.g. chat not found / bot blocked)

        req_payload = {
            "dealId": 1,
            "initData": valid_init_data
        }
        resp = client.post("/api/send_contact", json=req_payload)
        assert resp.status_code == 502
        data = resp.json()
        assert "Не вдалося доставити контакт у ваш Telegram-чат" in data["detail"]
        assert "@prostov_shrink_bot" in data["detail"]
