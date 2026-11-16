# -*- coding: utf-8 -*-
"""
Kyiv Radar Production HTTPS API
Version: 1.2.0
Backend service for Kyiv Radar Telegram Mini App and Web Platform.

Endpoints:
- GET    /api/health            - Health check, version & uptime
- GET    /api/deals             - Live verified catalog (serves synchronized listings)
- POST   /api/reports           - User complaints with sliding rate limiting & TG alerts
- POST   /api/landlords/submit  - Landlord apartment submission for moderation
- POST   /api/send_contact      - Secure server-side lookup & dispatch of landlord contact to Telegram user
- POST   /api/staging/approve   - Staging/E2E moderation approval pipeline (protected by X-Test-Secret)
- DELETE /api/staging/cleanup   - Automated test cleanup (protected by X-Test-Secret)
"""

import os
import hmac
import hashlib
import json
import time
import urllib.parse
from collections import defaultdict
from typing import Optional, List, Dict, Any

import sqlite3
import aiohttp
from fastapi import FastAPI, Request, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Configuration via environment variables (with safe defaults)
APP_ENV = os.getenv("APP_ENV", "production")
DB_PATH = os.getenv("KYIV_RADAR_DB_PATH", "/opt/resell-radar-ukraine/data/rent_deals.db")
DEALS_JSON_PATH = os.getenv("KYIV_RADAR_DEALS_PATH", "/opt/kyiv-radar-tma/data/deals.json")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "8531839081"))
BOT_TOKEN = os.getenv("BOT_TOKEN", "8976290222:AAF7LnHQ9FTEV3gI4Ap1F8Cz6ATsycbq22U")
TEST_SECRET_KEY = os.getenv("TEST_SECRET_KEY", "kyiv-radar-staging-internal-secret-2026")

app = FastAPI(
    title="Kyiv Radar API",
    description="Production HTTPS Backend for Kyiv Radar Rent Aggregator",
    version="1.2.0"
)

# CORS: Allow GitHub Pages, Telegram WebApps, and development origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://gewitter89.github.io",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "*"
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Sliding Window Rate Limiter
RATE_LIMITS = defaultdict(list)

def check_rate_limit(key: str, max_requests: int, window_seconds: int) -> bool:
    now = time.time()
    RATE_LIMITS[key] = [t for t in RATE_LIMITS[key] if now - t < window_seconds]
    if len(RATE_LIMITS[key]) >= max_requests:
        return False
    RATE_LIMITS[key].append(now)
    return True

# Telegram initData Cryptographic Signature & Expiry Validation
def validate_telegram_init_data(init_data: str, max_age_seconds: int = 86400) -> Optional[dict]:
    if not init_data:
        return None
    try:
        parsed = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        if "hash" not in parsed:
            return None
        received_hash = parsed.pop("hash")

        # Validate auth_date freshness to prevent replay attacks
        auth_date = int(parsed.get("auth_date", 0))
        if auth_date > 0 and (time.time() - auth_date > max_age_seconds):
            print(f"initData expired: auth_date={auth_date}, now={time.time()}")
            return None

        # Sort parameters alphabetically
        data_check_string = "\n".join(f"{k}={parsed[k]}" for k in sorted(parsed.keys()))

        # Secret key = HMAC_SHA256("WebAppData", bot_token)
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

        if calculated_hash != received_hash:
            print("initData HMAC signature mismatch")
            return None

        user_raw = parsed.get("user")
        if user_raw:
            return json.loads(user_raw)
        return parsed
    except Exception as e:
        print(f"Error validating initData: {e}")
        return None

# Database Initialization
def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS complaints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            deal_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            details TEXT,
            reporter_info TEXT,
            status TEXT DEFAULT 'pending_review',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS landlord_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            address TEXT NOT NULL,
            price TEXT NOT NULL,
            rooms INTEGER NOT NULL,
            phone TEXT NOT NULL,
            gpon INTEGER DEFAULT 0,
            generator INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending_review',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            moderator_notes TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# Telegram Bot Message Dispatcher
async def send_telegram_alert(text: str, reply_markup: Optional[dict] = None, target_chat: int = ADMIN_CHAT_ID):
    api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": target_chat,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, json=payload, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    err_txt = await resp.text()
                    print(f"Telegram alert error ({resp.status}): {err_txt}")
    except Exception as e:
        print(f"Failed to dispatch Telegram message: {e}")

# Helper: Load trusted catalog
def load_trusted_deals() -> List[Dict[str, Any]]:
    if os.path.exists(DEALS_JSON_PATH):
        try:
            with open(DEALS_JSON_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading deals.json: {e}")
    return []

# Pydantic Schemas
class ReportRequest(BaseModel):
    dealId: int
    reason: str
    details: Optional[str] = None
    initData: Optional[str] = None

class LandlordSubmitRequest(BaseModel):
    address: str
    price: str
    rooms: int
    phone: str
    gpon: bool = False
    generator: bool = False
    initData: Optional[str] = None

class SendContactRequest(BaseModel):
    dealId: int
    initData: str

class StagingApproveRequest(BaseModel):
    submission_id: int
    notes: Optional[str] = "Схвалено модератором (Тест)"

# ==========================================
# API ROUTES
# ==========================================

@app.get("/api/health")
async def health():
    deals = load_trusted_deals()
    return {
        "status": "healthy",
        "service": "kyiv-radar-api",
        "env": APP_ENV,
        "version": "1.2.0",
        "deals_count": len(deals),
        "timestamp": int(time.time())
    }

@app.get("/api/deals")
async def get_live_deals():
    """
    Live catalog endpoint.
    Guarantees that approved landlord listings appear immediately for all users worldwide.
    """
    deals = load_trusted_deals()
    return {
        "success": True,
        "count": len(deals),
        "deals": deals,
        "timestamp": int(time.time())
    }

@app.post("/api/reports")
async def submit_report(req: ReportRequest, request: Request, x_test_secret: Optional[str] = Header(None)):
    client_ip = request.client.host if request.client else "unknown"
    if x_test_secret != TEST_SECRET_KEY:
        if not check_rate_limit(f"report_{client_ip}", max_requests=10, window_seconds=600):
            raise HTTPException(status_code=429, detail="Забагато скарг. Спробуйте пізніше.")

    if not req.reason or len(req.reason.strip()) < 3:
        raise HTTPException(status_code=400, detail="Вкажіть причину скарги")

    user_data = validate_telegram_init_data(req.initData)
    if user_data:
        reporter = f"@{user_data.get('username', 'anon')} (TG ID: {user_data.get('id')})"
    else:
        reporter = f"Веб-користувач (IP: {client_ip})"

    comp_id = 0
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO complaints (deal_id, reason, details, reporter_info, status)
            VALUES (?, ?, ?, ?, 'pending_review')
        """, (req.dealId, req.reason.strip(), req.details or "", reporter))
        comp_id = cur.lastrowid
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"DB Error saving complaint: {e}")
        raise HTTPException(status_code=500, detail="Помилка збереження у базі даних")

    # Notify Admin via Telegram Bot
    admin_msg = (
        f"🚩 <b>СКАРГА НА ОГОЛОШЕННЯ #{req.dealId} (ID Скарги: #{comp_id})</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Причина: <b>{req.reason}</b>\n"
        f"Деталі: {req.details or 'немає'}\n"
        f"Відправник: {reporter}"
    )
    admin_kb = {
        "inline_keyboard": [
            [
                {"text": f"🔍 Переглянути лот #{req.dealId}", "url": f"https://gewitter89.github.io/kyiv-radar-tma/?deal={req.dealId}"},
                {"text": "❌ Відхилити", "callback_data": f"rep_dismiss_{comp_id}"}
            ]
        ]
    }
    await send_telegram_alert(admin_msg, reply_markup=admin_kb)

    return {
        "success": True,
        "id": comp_id,
        "message": f"Скаргу #{comp_id} прийнято на розгляд модератором"
    }

@app.post("/api/landlords/submit")
async def submit_landlord_deal(req: LandlordSubmitRequest, request: Request, x_test_secret: Optional[str] = Header(None)):
    client_ip = request.client.host if request.client else "unknown"
    if x_test_secret != TEST_SECRET_KEY:
        if not check_rate_limit(f"landlord_{client_ip}", max_requests=5, window_seconds=3600):
            raise HTTPException(status_code=429, detail="Забагато заявок з вашої адреси. Спробуйте пізніше.")

    if len(req.address.strip()) < 5:
        raise HTTPException(status_code=400, detail="Вкажіть повну адресу квартири (вулиця, номер будинку)")
    if not req.phone or len(req.phone.strip()) < 9:
        raise HTTPException(status_code=400, detail="Вкажіть коректний номер телефону")

    user_data = validate_telegram_init_data(req.initData)
    user_label = f"@{user_data.get('username', 'anon')} (TG ID: {user_data.get('id')})" if user_data else f"Веб (IP: {client_ip})"

    sub_id = 0
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO landlord_submissions (address, price, rooms, phone, gpon, generator, status, moderator_notes)
            VALUES (?, ?, ?, ?, ?, ?, 'pending_review', ?)
        """, (req.address.strip(), req.price.strip(), req.rooms, req.phone.strip(), 1 if req.gpon else 0, 1 if req.generator else 0, f"Подав: {user_label}"))
        sub_id = cur.lastrowid
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"DB Error saving submission: {e}")
        raise HTTPException(status_code=500, detail="Помилка збереження заявки")

    # Notify Admin with Action Buttons
    admin_lines = [
        f"🏢 <b>НОВА КВАРТИРА ВІД ВЛАСНИКА #{sub_id}</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"📍 <b>Адреса:</b> {req.address.strip()}",
        f"💰 <b>Ціна:</b> {req.price.strip()} ₴/міс",
        f"🚪 <b>Кімнат:</b> {req.rooms}",
        f"📞 <b>Контакт:</b> <code>{req.phone.strip()}</code>",
        f"⚡ <b>Генератор:</b> {'Так' if req.generator else 'Ні'} | 🌐 <b>GPON:</b> {'Так' if req.gpon else 'Ні'}",
        "",
        f"👤 <b>Джерело:</b> {user_label}"
    ]
    admin_kb = {
        "inline_keyboard": [
            [
                {"text": "✅ Схвалити в базу (0%)", "callback_data": f"ll_approve_{sub_id}"},
                {"text": "❌ Відхилити", "callback_data": f"ll_reject_{sub_id}"}
            ]
        ]
    }
    await send_telegram_alert("\n".join(admin_lines), reply_markup=admin_kb)

    return {
        "success": True,
        "id": sub_id,
        "message": f"Вашу квартиру #{sub_id} прийнято на модерацію. Дякуємо!"
    }

@app.post("/api/send_contact")
async def send_contact(req: SendContactRequest):
    """
    CRITICAL SECURITY HARDENING:
    The server fetches all deal parameters (title, price, phone, address) from the trusted server database.
    It NEVER accepts or trusts client-supplied phone/price/address values!
    """
    user_data = validate_telegram_init_data(req.initData)
    if not user_data or "id" not in user_data:
        raise HTTPException(
            status_code=401,
            detail="Помилка авторизації Telegram. Відкрийте додаток у Telegram для надсилання номеру в чат."
        )

    # Server-side lookup of deal by dealId
    deals = load_trusted_deals()
    deal = next((d for d in deals if d.get("id") == req.dealId), None)
    if not deal:
        raise HTTPException(status_code=404, detail=f"Оголошення #{req.dealId} не знайдено у базі даних.")

    trusted_title = deal.get("title", "Квартира")
    trusted_address = deal.get("address", "Київ")
    trusted_price = deal.get("price", 0)
    trusted_phone = deal.get("phone", "Не вказано")

    user_id = user_data["id"]
    msg_lines = [
        f"📞 <b>Контакт орендодавця (Лот #{req.dealId})</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"🏢 <b>{trusted_title}</b>",
        f"📍 {trusted_address}",
        f"💰 <b>Ціна:</b> {trusted_price:,} ₴/міс (0% комісії рієлторам)",
        "",
        f"📱 <b>Телефон власника:</b> <code>{trusted_phone}</code>",
        "",
        "<i>Зв'яжіться з орендодавцем безпосередньо. Вдалих переглядів!</i>"
    ]
    await send_telegram_alert("\n".join(msg_lines), target_chat=user_id)

    return {
        "success": True,
        "dealId": req.dealId,
        "message": "Контакт орендодавця успішно надіслано у ваш чат Telegram!"
    }

@app.post("/api/staging/approve")
async def staging_approve(req: StagingApproveRequest, x_test_secret: Optional[str] = Header(None)):
    """
    Real moderation pipeline execution endpoint.
    Executes the exact same logic as Telegram bot callback `handle_ll_approve`.
    Decoupled verification flags:
      contactVerified: True
      isOwnerVerified: False
      moderationStatus: 'approved'
    """
    if x_test_secret != TEST_SECRET_KEY:
        raise HTTPException(status_code=403, detail="Forbidden: Invalid test secret key")

    sub_id = req.submission_id
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE landlord_submissions SET status = 'published', moderator_notes = ? WHERE id = ?", (req.notes, sub_id))
    cur.execute("SELECT address, price, rooms, phone, gpon, generator FROM landlord_submissions WHERE id = ?", (sub_id,))
    row = cur.fetchone()
    conn.commit()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail=f"Submission #{sub_id} not found in database")

    # Load and update deals.json
    deals_list = load_trusted_deals()
    new_id = max([d.get("id", 0) for d in deals_list] + [0]) + 1
    new_deal = {
        "id": new_id,
        "title": f"Квартира від власника: {row[0]}",
        "district": "Київ",
        "address": row[0],
        "cleanAddress": row[0],
        "metro": "Київ",
        "walkMin": 5,
        "price": int(row[1]) if str(row[1]).isdigit() else 20000,
        "realtorCommissionSaved": round(int(row[1]) / 2) if str(row[1]).isdigit() else 10000,
        "area": 45,
        "floor": 4,
        "totalFloors": 9,
        "rooms": row[2] or 1,
        "lat": 50.4501,
        "lng": 30.5234,
        "generator": bool(row[5]),
        "gpon": bool(row[4]),
        "gas": False,
        "lowFloor": True,
        "pets": False,
        "ownerName": "Власник житла",
        "phone": row[3],
        "phoneMasked": row[3][:6] + "***",
        "images": [
            "https://images.unsplash.com/photo-1522708323590-d24dbb6b0267?auto=format&fit=crop&w=1000&q=80"
        ],
        "desc": "Перевірена квартира від власника через Київ Радар. Контакт дійсний. 0% комісії рієлторам.",
        "source": "Київ Радар (Власник)",
        "status": "Опубліковано",
        "isOwnerVerified": False,
        "contactVerified": True,
        "moderationStatus": "approved",
        "verifiedAt": "Контакт підтверджено модератором сьогодні"
    }
    deals_list.insert(0, new_deal)
    with open(DEALS_JSON_PATH, "w", encoding="utf-8") as df:
        json.dump(deals_list, df, ensure_ascii=False, indent=2)

    return {
        "success": True,
        "submission_id": sub_id,
        "published_deal": new_deal
    }

@app.delete("/api/staging/cleanup")
async def cleanup_test_data(
    submission_id: Optional[int] = None,
    complaint_id: Optional[int] = None,
    deal_id: Optional[int] = None,
    x_test_secret: Optional[str] = Header(None)
):
    """
    Staging / E2E Automated Cleanup endpoint.
    Restricted by secret key to ensure test data does not pollute production SQLite or catalog.
    """
    if x_test_secret != TEST_SECRET_KEY:
        raise HTTPException(status_code=403, detail="Forbidden: Invalid test secret key")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    deleted_records = {}

    if submission_id:
        cur.execute("DELETE FROM landlord_submissions WHERE id = ?", (submission_id,))
        deleted_records["submission_id"] = submission_id
    if complaint_id:
        cur.execute("DELETE FROM complaints WHERE id = ?", (complaint_id,))
        deleted_records["complaint_id"] = complaint_id

    conn.commit()
    conn.close()

    if deal_id:
        deals = load_trusted_deals()
        orig_len = len(deals)
        deals = [d for d in deals if d.get("id") != deal_id]
        if len(deals) != orig_len:
            with open(DEALS_JSON_PATH, "w", encoding="utf-8") as f:
                json.dump(deals, f, ensure_ascii=False, indent=2)
            deleted_records["deal_id"] = deal_id

    # Reset in-memory rate limits for test client
    RATE_LIMITS.clear()

    return {
        "success": True,
        "cleaned": deleted_records
    }
