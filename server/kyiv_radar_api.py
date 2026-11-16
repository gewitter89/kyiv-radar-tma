# -*- coding: utf-8 -*-
"""
Kyiv Radar Production HTTPS API
Version: 1.3.0 (Security Hardened)
Production backend service for Kyiv Radar Telegram Mini App and Web Platform.

Endpoints:
- GET  /api/health            - Health check, version & uptime
- GET  /api/deals             - Live verified catalog (serves synchronized listings)
- POST /api/reports           - User complaints with sliding rate limiting & TG alerts
- POST /api/landlords/submit  - Landlord apartment submission for moderation
- POST /api/send_contact      - Secure server-side lookup & dispatch of landlord contact to Telegram user

Security Measures:
- ZERO hardcoded secrets: BOT_TOKEN strictly required via environment.
- ZERO admin/staging manipulation endpoints exposed in production.
- Cryptographically validated initData with auth_date freshness & hmac.compare_digest.
- Strict CORS restricted exclusively to official origins (no wildcard '*').
- Non-root unprivileged process execution (kyivradar:kyivradar).
"""

import os
import hmac
import hashlib
import json
import time
import logging
import urllib.parse
from typing import Optional, List, Dict, Any

import sqlite3
import aiohttp
from fastapi import FastAPI, Request, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] [kyiv_radar_api] %(message)s'
)
logger = logging.getLogger("kyiv_radar_api")

# In-memory metrics for health monitoring
API_METRICS = {
    "requests_total": 0,
    "telegram_errors": 0,
    "db_errors": 0,
    "last_error": None
}

# Load environment configuration from .env if present
def _load_env_file(filepath: str = "/opt/agent-bot/.env"):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip().strip("'\""))
        except Exception as e:
            print(f"Warning: could not read {filepath}: {e}")

_load_env_file()

APP_ENV = os.getenv("APP_ENV", "production")
DB_PATH = os.getenv("KYIV_RADAR_DB_PATH", "/opt/resell-radar-ukraine/data/rent_deals.db")
DEALS_JSON_PATH = os.getenv("KYIV_RADAR_DEALS_PATH", "/opt/kyiv-radar-tma/data/deals.json")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "8531839081"))

# MANDATORY SECURITY CHECK: BOT_TOKEN or TELEGRAM_BOT_TOKEN MUST BE SUPPLIED IN ENVIRONMENT
BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN and APP_ENV != "test":
    raise RuntimeError("CRITICAL SECURITY ERROR: BOT_TOKEN (or TELEGRAM_BOT_TOKEN) environment variable is not configured!")

app = FastAPI(
    title="Kyiv Radar Production API",
    description="Secure Production HTTPS Backend for Kyiv Radar Rent Aggregator",
    version="1.3.1"
)

# STRICT CORS CONFIGURATION: Wildcard '*' is strictly forbidden
ALLOWED_ORIGINS = [
    "https://gewitter89.github.io",
]
if APP_ENV == "development":
    ALLOWED_ORIGINS.extend([
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000"
    ])

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Shared SQLite Rate Limiter (consistent across multiple Uvicorn workers, zero in-memory desync)
def check_rate_limit(key: str, max_requests: int, window_seconds: int) -> bool:
    now = time.time()
    cutoff = now - window_seconds
    try:
        with sqlite3.connect(DB_PATH, timeout=10.0) as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM rate_limits WHERE key = ? AND timestamp < ?", (key, cutoff))
            cur.execute("SELECT COUNT(*) FROM rate_limits WHERE key = ? AND timestamp >= ?", (key, cutoff))
            count = cur.fetchone()[0]
            if count >= max_requests:
                return False
            cur.execute("INSERT INTO rate_limits (key, timestamp) VALUES (?, ?)", (key, now))
            conn.commit()
            return True
    except sqlite3.Error as e:
        logger.error(f"Rate limiter database error for key '{key}': {e}")
        API_METRICS["db_errors"] += 1
        API_METRICS["last_error"] = f"DB Rate Limit Error: {str(e)}"
        # Safe fail-closed: reject requests rather than unmetered bypass across workers
        return False

# Telegram initData Cryptographic Signature & Expiry Validation
def validate_telegram_init_data(init_data: str, max_age_seconds: int = 86400) -> Optional[dict]:
    if not init_data or not isinstance(init_data, str) or not BOT_TOKEN:
        return None
    try:
        parsed = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        if "hash" not in parsed or "auth_date" not in parsed:
            # auth_date is strictly required
            return None

        received_hash = parsed.pop("hash")

        # Parse and validate auth_date strictly
        try:
            auth_date = int(parsed["auth_date"])
        except (ValueError, TypeError):
            return None

        now = time.time()
        if auth_date <= 0:
            return None
        # Reject future timestamps (+60s tolerance for network/NTP clock drift)
        if auth_date > now + 60:
            return None
        # Reject expired signatures
        if now - auth_date > max_age_seconds:
            return None

        # Sort parameters alphabetically
        data_check_string = "\n".join(f"{k}={parsed[k]}" for k in sorted(parsed.keys()))

        # Secret key = HMAC_SHA256("WebAppData", bot_token)
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

        # Constant-time comparison to prevent timing attacks
        if not hmac.compare_digest(calculated_hash, received_hash):
            return None

        user_raw = parsed.get("user")
        if user_raw:
            return json.loads(user_raw)
        return parsed
    except Exception as e:
        return None

# Database Initialization
def init_db():
    if not os.path.exists(os.path.dirname(DB_PATH)):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL;")
    cur.execute("PRAGMA busy_timeout=5000;")
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
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rate_limits (
            key TEXT NOT NULL,
            timestamp REAL NOT NULL
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rate_limits_key_time ON rate_limits(key, timestamp)")

    # Ensure verification metadata columns exist in landlord_submissions
    for col_def in [
        ("contact_verified", "INTEGER DEFAULT 0"),
        ("verified_at", "TEXT"),
        ("verification_method", "TEXT")
    ]:
        try:
            cur.execute(f"ALTER TABLE landlord_submissions ADD COLUMN {col_def[0]} {col_def[1]}")
        except sqlite3.OperationalError:
            pass # already exists

    conn.commit()
    conn.close()

if APP_ENV != "test":
    try:
        init_db()
    except Exception as e:
        logger.error(f"init_db notice: {e}")

# Telegram Bot Message Dispatcher
async def send_telegram_alert(text: str, reply_markup: Optional[dict] = None, target_chat: int = ADMIN_CHAT_ID) -> bool:
    if not BOT_TOKEN:
        logger.warning("Telegram alert skipped: BOT_TOKEN is empty.")
        return False
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
                if resp.status == 200:
                    data = await resp.json()
                    return bool(data.get("ok"))
                else:
                    err_txt = await resp.text()
                    logger.warning(f"Telegram alert error (status {resp.status}) to chat {target_chat}: {err_txt}")
                    API_METRICS["telegram_errors"] += 1
                    API_METRICS["last_error"] = f"Telegram status {resp.status}: {err_txt[:100]}"
                    return False
    except Exception as e:
        logger.error(f"Failed to dispatch Telegram message to chat {target_chat}: {e}")
        API_METRICS["telegram_errors"] += 1
        API_METRICS["last_error"] = f"Telegram exception: {str(e)}"
        return False

# Helper: Load trusted catalog
def load_trusted_deals() -> List[Dict[str, Any]]:
    if os.path.exists(DEALS_JSON_PATH):
        try:
            with open(DEALS_JSON_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading deals.json: {e}")
            API_METRICS["db_errors"] += 1
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
        "version": "1.3.1",
        "deals_count": len(deals),
        "bot_token_configured": bool(BOT_TOKEN),
        "metrics": API_METRICS,
        "timestamp": int(time.time())
    }

@app.get("/api/deals")
async def get_live_deals():
    """
    Live catalog endpoint.
    Serves synchronized listings from the verified catalog.
    """
    deals = load_trusted_deals()
    return {
        "success": True,
        "count": len(deals),
        "deals": deals,
        "timestamp": int(time.time())
    }

@app.post("/api/reports")
async def submit_report(req: ReportRequest, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    if not check_rate_limit(f"report_{client_ip}", max_requests=10, window_seconds=600):
        raise HTTPException(status_code=429, detail="Забагато скарг. Спробуйте пізніше.")

    if not req.reason or len(req.reason.strip()) < 3:
        raise HTTPException(status_code=400, detail="Вкажіть причину скарги")

    user_data = validate_telegram_init_data(req.initData) if req.initData else None
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

    # Notify Admin via Telegram Bot (with HTML escaping)
    import html
    safe_reason = html.escape(req.reason.strip())
    safe_details = html.escape(req.details.strip()) if req.details else "немає"
    safe_reporter = html.escape(reporter)

    admin_msg = (
        f"🚩 <b>СКАРГА НА ОГОЛОШЕННЯ #{req.dealId} (ID Скарги: #{comp_id})</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Причина: <b>{safe_reason}</b>\n"
        f"Деталі: {safe_details}\n"
        f"Відправник: {safe_reporter}"
    )
    admin_kb = {
        "inline_keyboard": [
            [
                {"text": f"🔍 Переглянути лот #{req.dealId}", "url": f"https://gewitter89.github.io/kyiv-radar-tma/?deal={req.dealId}"},
                {"text": "❌ Відхилити", "callback_data": f"rep_dismiss_{comp_id}"}
            ]
        ]
    }
    alert_sent = await send_telegram_alert(admin_msg, reply_markup=admin_kb)

    return {
        "success": True,
        "id": comp_id,
        "alert_delivered": alert_sent,
        "message": f"Скаргу #{comp_id} прийнято на розгляд модератором"
    }

@app.post("/api/landlords/submit")
async def submit_landlord_deal(req: LandlordSubmitRequest, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    if not check_rate_limit(f"landlord_{client_ip}", max_requests=5, window_seconds=3600):
        raise HTTPException(status_code=429, detail="Забагато заявок з вашої адреси. Спробуйте пізніше.")

    if len(req.address.strip()) < 5:
        raise HTTPException(status_code=400, detail="Вкажіть повну адресу квартири (вулиця, номер будинку)")
    if not req.phone or len(req.phone.strip()) < 9:
        raise HTTPException(status_code=400, detail="Вкажіть коректний номер телефону")

    user_data = validate_telegram_init_data(req.initData) if req.initData else None
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

    # Notify Admin with Action Buttons (with HTML escaping)
    import html
    safe_addr = html.escape(req.address.strip())
    safe_price = html.escape(req.price.strip())
    safe_phone = html.escape(req.phone.strip())
    safe_user = html.escape(user_label)

    admin_lines = [
        f"🏢 <b>НОВА КВАРТИРА ВІД ВЛАСНИКА #{sub_id}</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"📍 <b>Адреса:</b> {safe_addr}",
        f"💰 <b>Ціна:</b> {safe_price} ₴/міс",
        f"🚪 <b>Кімнат:</b> {req.rooms}",
        f"📞 <b>Контакт:</b> <code>{safe_phone}</code>",
        f"⚡ <b>Генератор:</b> {'Так' if req.generator else 'Ні'} | 🌐 <b>GPON:</b> {'Так' if req.gpon else 'Ні'}",
        "",
        f"👤 <b>Джерело:</b> {safe_user}"
    ]
    admin_kb = {
        "inline_keyboard": [
            [
                {"text": "✅ Опублікувати в каталог", "callback_data": f"ll_approve_{sub_id}"},
                {"text": "❌ Відхилити", "callback_data": f"ll_reject_{sub_id}"}
            ]
        ]
    }
    alert_sent = await send_telegram_alert("\n".join(admin_lines), reply_markup=admin_kb)

    return {
        "success": True,
        "id": sub_id,
        "alert_delivered": alert_sent,
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
    sent = await send_telegram_alert("\n".join(msg_lines), target_chat=user_id)
    if not sent:
        raise HTTPException(
            status_code=502,
            detail="Не вдалося доставити контакт у ваш Telegram-чат. Будь ласка, відкрийте діалог з нашим ботом (@prostov_shrink_bot) та натисніть /start."
        )

    return {
        "success": True,
        "dealId": req.dealId,
        "message": "Контакт орендодавця успішно надіслано у ваш чат Telegram!"
    }
