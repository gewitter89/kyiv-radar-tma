# -*- coding: utf-8 -*-
"""
Kyiv Radar Production HTTPS API
Version: 1.6.0 (Authenticated moderation media)
Production backend service for Kyiv Radar Telegram Mini App and Web Platform.

Endpoints:
- GET  /api/health            - Health check, version & uptime
- GET  /api/deals             - Live verified catalog (strictly sanitized, zero raw phone leaks)
- POST /api/reports           - User complaints with sliding rate limiting & TG alerts
- POST /api/landlords/upload_photos - Secure landlord photos upload with EXIF/GPS stripping
- POST /api/landlords/submit  - Landlord apartment submission for moderation with photo URLs
- POST /api/send_contact      - Secure server-side lookup & dispatch of landlord contact to Telegram user

Security Measures:
- ZERO hardcoded secrets: BOT_TOKEN strictly required via environment.
- Strict separation of public catalog (masked) and private landlord contacts (server-side vault).
- Zero EXIF/GPS leaks: All uploaded photos stripped of metadata and normalized to clean WebP.
- ZERO admin/staging manipulation endpoints exposed in production.
- Cryptographically validated initData with auth_date freshness & hmac.compare_digest.
- Per-user rate limiting on contact dispatch (max 10/hour) to stop scrapers.
- Strict CORS restricted exclusively to official origins (no wildcard '*').
- Non-root unprivileged process execution (kyivradar:kyivradar).
"""

import os
import io
import hmac
import html
import uuid
import re
import ipaddress
import hashlib
import json
import time
import logging
import urllib.parse
from typing import Optional, List, Dict, Any

import sqlite3
import aiohttp
from PIL import Image, ImageOps, UnidentifiedImageError
from fastapi import FastAPI, Request, HTTPException, Depends, Header, UploadFile, File, Form, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

try:
    from .listing_trust import load_private_register, public_listing_view
    from .partner_visibility import enforce_partner_visibility
    from .partner_publication import read_private_export
except ImportError:
    from listing_trust import load_private_register, public_listing_view
    from partner_visibility import enforce_partner_visibility
    from partner_publication import read_private_export
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
            logger.warning("Unable to read environment configuration: %s", type(e).__name__)

_load_env_file()

APP_ENV = os.getenv("APP_ENV", "production")
DB_PATH = os.getenv("KYIV_RADAR_DB_PATH", "/opt/resell-radar-ukraine/data/rent_deals.db")
DEALS_JSON_PATH = os.getenv("KYIV_RADAR_DEALS_PATH", "/opt/kyiv-radar-tma/data/deals.json")
# Private staging source rights: never a public file or client-controlled path.
PARTNER_RIGHTS_DB_PATH = os.getenv("KYIV_RADAR_PRIVATE_PARTNER_DB", "")
PARTNER_EXPORT_PATH = os.getenv("KYIV_RADAR_PRIVATE_PARTNER_EXPORT", "")
PARTNER_PUBLICATION_AUTH_PATH = os.getenv("KYIV_RADAR_PRIVATE_PUBLICATION_AUTH", "")
# An operator-maintained file outside public GitHub Pages; never publish proof.
REVIEW_REGISTER_PATH = os.getenv("KYIV_RADAR_PRIVATE_REVIEW_PATH", "")
PRIVATE_CONTACTS_PATH = os.getenv(
    "KYIV_RADAR_PRIVATE_CONTACTS_PATH",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "data", "private_contacts.json"))
)
if os.path.exists("/opt/kyiv-radar-tma"):
    UPLOADS_BASE_DIR = os.getenv("KYIV_RADAR_UPLOADS_DIR", "/opt/kyiv-radar-tma/uploads/landlords")
    STATIC_UPLOADS_ROOT = os.getenv("KYIV_RADAR_STATIC_UPLOADS", "/opt/kyiv-radar-tma/uploads")
else:
    UPLOADS_BASE_DIR = os.getenv(
        "KYIV_RADAR_UPLOADS_DIR",
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "uploads", "landlords"))
    )
    STATIC_UPLOADS_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "uploads"))

try:
    os.makedirs(UPLOADS_BASE_DIR, exist_ok=True)
except Exception as ud_err:
    logger.warning(f"Notice creating UPLOADS_BASE_DIR: {ud_err}")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "8531839081"))
PUBLIC_API_BASE = os.getenv("KYIV_RADAR_PUBLIC_API_BASE", "https://vmi3445944.contaboserver.net").rstrip("/")
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_BATCH_BYTES = 32 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 20_000_000
PHOTO_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
LANDLORD_CONSENT_VERSION = "owner-rights-2026-11-v1"
LANDLORD_CONSENT_STATEMENT = (
    "Я підтверджую право розміщувати оголошення, передавати контакт і "
    "завантажувати обрані фото для модерації та можливої публікації."
)
LANDLORD_CONSENT_HASH = hashlib.sha256(LANDLORD_CONSENT_STATEMENT.encode("utf-8")).hexdigest()

# MANDATORY SECURITY CHECK: BOT_TOKEN or TELEGRAM_BOT_TOKEN MUST BE SUPPLIED IN ENVIRONMENT
BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN and APP_ENV != "test":
    raise RuntimeError("CRITICAL SECURITY ERROR: BOT_TOKEN (or TELEGRAM_BOT_TOKEN) environment variable is not configured!")

app = FastAPI(
    title="Kyiv Radar API",
    description="Listings and moderation API",
    version="1.8.0"
)

# Photos stay private on disk; /api/media/{id} serves only approved files.

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

# Limit the incoming HTTP body BEFORE FastAPI/Starlette parse multipart forms.
# The endpoint's per-file and batch checks remain a separate line of defense.
# The extra 1 MiB accommodates multipart fields/headers around 32 MiB of images.
MAX_UPLOAD_REQUEST_BYTES = MAX_IMAGE_BATCH_BYTES + 1024 * 1024


class UploadBodyLimitExceeded(Exception):
    """Request stream exceeds the pre-multipart upload cap."""


class UploadBodyLimitMiddleware:
    """A small pure-ASGI gate for photo uploads, including chunked requests.

    Starlette's multipart parser can swallow errors raised by receive() and
    turn them into a 400. In that case rewrite the response to the correct
    413; no route handler or file write is allowed to proceed.
    """

    UPLOAD_PATH = "/api/landlords/upload_photos"
    ERROR_BODY = b'{"detail":"Upload request body exceeds the 33 MiB limit"}'

    def __init__(self, app, max_body_bytes: int = MAX_UPLOAD_REQUEST_BYTES):
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope, receive, send):
        if (scope["type"] != "http"
                or scope.get("method") != "POST"
                or scope.get("path") != self.UPLOAD_PATH):
            return await self.app(scope, receive, send)

        response_headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(self.ERROR_BODY)).encode("ascii")),
        ]

        async def reject():
            await send({
                "type": "http.response.start",
                "status": 413,
                "headers": response_headers,
            })
            await send({
                "type": "http.response.body",
                "body": self.ERROR_BODY,
            })

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        content_length = headers.get(b"content-length", b"")
        if content_length.isdigit() and int(content_length) > self.max_body_bytes:
            return await reject()

        consumed = 0
        over_limit = False
        response_started = False

        async def receive_capped():
            nonlocal consumed, over_limit
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > self.max_body_bytes:
                    over_limit = True
                    raise UploadBodyLimitExceeded()
            return message

        async def send_capped(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                if over_limit:
                    message = {
                        "type": "http.response.start",
                        "status": 413,
                        "headers": response_headers,
                    }
            elif message["type"] == "http.response.body" and over_limit:
                # The multipart parser may have caught UploadBodyLimitExceeded.
                message = {
                    "type": "http.response.body",
                    "body": self.ERROR_BODY,
                    "more_body": False,
                }
            await send(message)

        try:
            await self.app(scope, receive_capped, send_capped)
        except UploadBodyLimitExceeded:
            if response_started:
                # Never attempt a second response after headers were sent.
                raise
            await reject()


app.add_middleware(UploadBodyLimitMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Shared SQLite Rate Limiter (transactional even under concurrent workers).
def check_rate_limit(key: str, max_requests: int, window_seconds: int) -> bool:
    now = time.time()
    cutoff = now - window_seconds
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        cur = conn.cursor()
        # Lock before COUNT: otherwise concurrent requests can all pass before INSERT.
        cur.execute("BEGIN IMMEDIATE")
        cur.execute("DELETE FROM rate_limits WHERE key = ? AND timestamp < ?", (key, cutoff))
        cur.execute("SELECT COUNT(*) FROM rate_limits WHERE key = ? AND timestamp >= ?", (key, cutoff))
        if cur.fetchone()[0] >= max_requests:
            conn.rollback()
            return False
        cur.execute("INSERT INTO rate_limits (key, timestamp) VALUES (?, ?)", (key, now))
        conn.commit()
        return True
    except sqlite3.Error as error:
        if conn:
            conn.rollback()
        logger.error("Rate limiter database failure: %s", type(error).__name__)
        API_METRICS["db_errors"] += 1
        API_METRICS["last_error"] = "Rate limiter database unavailable"
        # Fail closed; do not allow unlimited requests when the database is unavailable.
        return False
    finally:
        if conn:
            conn.close()


def client_ip_for_rate_limit(request: Request) -> str:
    """Trust X-Forwarded-For only from the local Caddy reverse proxy.

    Direct requests cannot spoof this header to evade an IP quota.
    """
    peer = request.client.host if request.client else "unknown"
    if peer in ("127.0.0.1", "::1"):
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        try:
            return str(ipaddress.ip_address(forwarded))
        except ValueError:
            pass
    return peer

# Telegram initData Cryptographic Signature & Expiry Validation
def validate_telegram_init_data(init_data: str, max_age_seconds: int = 86400) -> Optional[dict]:
    if not init_data or not isinstance(init_data, str) or not BOT_TOKEN:
        return None
    try:
        parsed = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        if "hash" not in parsed or "auth_date" not in parsed:
            return None

        received_hash = parsed.pop("hash")

        try:
            auth_date = int(parsed["auth_date"])
        except (ValueError, TypeError):
            return None

        now = time.time()
        if auth_date <= 0:
            return None
        if auth_date > now + 60:
            return None
        if now - auth_date > max_age_seconds:
            return None

        data_check_string = "\n".join(f"{k}={parsed[k]}" for k in sorted(parsed.keys()))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

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
            photos TEXT DEFAULT '[]',
            gpon INTEGER DEFAULT 0,
            generator INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending_review',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            moderator_notes TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS private_deal_contacts (
            deal_id INTEGER PRIMARY KEY,
            phone TEXT NOT NULL,
            owner_name TEXT,
            phone_masked TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rate_limits (
            key TEXT NOT NULL,
            timestamp REAL NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS landlord_uploads (
            photo_id TEXT PRIMARY KEY,
            owner_telegram_id INTEGER NOT NULL,
            submission_id INTEGER,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Only a declaration/acknowledgement receipt, NOT proof of property ownership
    # or photograph copyright. Deliberately no raw phone, name, files or address.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS landlord_consent_receipts (
            submission_id INTEGER PRIMARY KEY,
            consent_version TEXT NOT NULL,
            statement_sha256 TEXT NOT NULL,
            accepted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_landlord_uploads_submission ON landlord_uploads(submission_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rate_limits_key_time ON rate_limits(key, timestamp)")

    # Ensure schema migrations
    for col_def in [
        ("photos", "TEXT DEFAULT '[]'"),
        ("submitter_id", "INTEGER"),
        ("contact_verified", "INTEGER DEFAULT 0"),
        ("verified_at", "TEXT"),
        ("verification_method", "TEXT")
    ]:
        try:
            cur.execute(f"ALTER TABLE landlord_submissions ADD COLUMN {col_def[0]} {col_def[1]}")
        except sqlite3.OperationalError:
            pass

    # Pre-populate private_deal_contacts table from private_contacts.json if empty
    try:
        if os.path.exists(PRIVATE_CONTACTS_PATH):
            with open(PRIVATE_CONTACTS_PATH, "r", encoding="utf-8") as pf:
                priv_dict = json.load(pf)
                for did_str, pinfo in priv_dict.items():
                    cur.execute(
                        "INSERT OR IGNORE INTO private_deal_contacts (deal_id, phone, owner_name, phone_masked) VALUES (?, ?, ?, ?)",
                        (int(did_str), pinfo.get("phone", ""), pinfo.get("ownerName", ""), pinfo.get("phoneMasked", ""))
                    )
    except Exception as mig_err:
        logger.warning(f"private_deal_contacts seed notice: {mig_err}")

    conn.commit()
    conn.close()

if APP_ENV != "test":
    try:
        init_db()
    except Exception as exc:
        logger.critical("Database initialization failed: %s", type(exc).__name__)
        raise RuntimeError("Unable to initialize Kyiv Radar database") from exc

# Image Processing & EXIF / GPS Metadata Stripping
def sanitize_and_save_photo(photo_bytes: bytes, dest_filename: str) -> str:
    """
    Validates image, strips all EXIF metadata (GPS coords, camera model, etc.),
    auto-orients, limits dimensions to 1600px, and saves as clean WebP.
    """
    if len(photo_bytes) < 32:
        raise ValueError("Файл занадто малий для зображення")
    if len(photo_bytes) > MAX_IMAGE_BYTES:
        raise ValueError("Розмір фотографії перевищує 10 МБ")

    in_io = io.BytesIO(photo_bytes)
    with Image.open(in_io) as img:
        fmt = (img.format or "").upper()
        if fmt not in ("JPEG", "JPG", "PNG", "WEBP"):
            raise ValueError(f"Непідтримуваний формат: {fmt}. Дозволено лише JPG, PNG, WEBP.")

        if img.width * img.height > Image.MAX_IMAGE_PIXELS:
            raise ValueError('Зображення має завеликі розміри')
        try:
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass

        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            converted = img.convert("RGBA")
        else:
            converted = img.convert("RGB")

        w, h = converted.size
        max_dim = 1600
        if max(w, h) > max_dim:
            scale = max_dim / float(max(w, h))
            converted = converted.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)

        dest_path = os.path.join(UPLOADS_BASE_DIR, dest_filename)
        converted.save(dest_path, format="WEBP", quality=82, method=4)
        # Return only a private path; the upload API returns an opaque photo ID.
        return dest_path

# Helper: Load trusted catalog
def load_trusted_deals() -> List[Dict[str, Any]]:
    # Legacy catalog preserved for backward compatibility; it is not an
    # independent proof of existence, ownership or rights to republish.
    base: List[Dict[str, Any]] = []
    if os.path.exists(DEALS_JSON_PATH):
        try:
            with open(DEALS_JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    base = data
        except Exception as e:
            logger.error("Unable to load source catalog: %s", type(e).__name__)
            API_METRICS["db_errors"] += 1

    # Private partner publication is fully opt-in and disabled by default.
    # Receipt expiry/changes and independent source-level checks fail closed.
    if not (PARTNER_EXPORT_PATH and PARTNER_PUBLICATION_AUTH_PATH):
        return base
    staged = read_private_export(PARTNER_EXPORT_PATH, PARTNER_PUBLICATION_AUTH_PATH)
    used = {row.get("id") for row in base if isinstance(row, dict)}
    for row in staged:
        if row.get("id") not in used:
            used.add(row["id"])
            base.append(row)
    return base

def _is_public_catalog_eligible(row: Dict[str, Any]) -> bool:
    """Source authorization is distinct from checking availability/ownership.

    Legacy OLX/DIM.RIA imports lack republication rights, so a 200 response or
    even a moderator's availability check cannot make them publishable.
    Partner rows must *also* pass the private revocation/rights gate below.
    """
    if not isinstance(row, dict) or row.get("fixtureOnly") is True:
        return False
    source = str(row.get("source") or "").strip().casefold()
    if source == "київ радар (пряма заявка)":
        submission_id = row.get("submission_id")
        return (
            type(submission_id) is int and submission_id > 0
            and row.get("moderationStatus") == "approved"
        )
    if source.startswith("partner:"):
        return bool(source.removeprefix("partner:").strip())
    return False


def load_effective_deals() -> List[Dict[str, Any]]:
    """Apply moderation, live partner rights and strict source eligibility.

    Shared by public catalog, health and contact routes so a stale data file
    cannot resurrect old imports through an alternate API endpoint.
    """
    reviewed = public_listing_view(
        load_trusted_deals(),
        load_private_register(REVIEW_REGISTER_PATH),
    )
    authorized = enforce_partner_visibility(reviewed, PARTNER_RIGHTS_DB_PATH)
    return [row for row in authorized if _is_public_catalog_eligible(row)]

# Helper: Look up private landlord contact from secure vault
def get_private_contact(deal_id: int) -> Optional[dict]:
    # 1. Check SQLite private_deal_contacts table
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5.0)
        cur = conn.cursor()
        cur.execute("SELECT phone, owner_name, phone_masked FROM private_deal_contacts WHERE deal_id = ?", (deal_id,))
        row = cur.fetchone()
        conn.close()
        if row and row[0]:
            return {"phone": row[0], "ownerName": row[1], "phoneMasked": row[2]}
    except Exception:
        pass

    # 2. Check server-side private_contacts.json file
    if os.path.exists(PRIVATE_CONTACTS_PATH):
        try:
            with open(PRIVATE_CONTACTS_PATH, "r", encoding="utf-8") as f:
                contacts = json.load(f)
                return contacts.get(str(deal_id))
        except Exception as e:
            logger.error(f"Error reading private_contacts.json: {e}")
    return None

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
            async with session.post(api_url, json=payload, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    return True
                else:
                    logger.warning("Telegram message failed with HTTP %s", resp.status)
                    API_METRICS["telegram_errors"] += 1
                    API_METRICS["last_error"] = f"Telegram status {resp.status}"
                    return False
    except Exception as e:
        logger.error("Telegram message dispatch failure: %s", type(e).__name__)
        API_METRICS["telegram_errors"] += 1
        API_METRICS["last_error"] = f"Telegram exception: {type(e).__name__}"
        return False

# Pydantic Schemas
class ReportRequest(BaseModel):
    dealId: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=160)
    details: Optional[str] = Field(default=None, max_length=1500)
    initData: Optional[str] = Field(default=None, max_length=8192)

class LandlordSubmitRequest(BaseModel):
    address: str = Field(min_length=5, max_length=220)
    price: str = Field(min_length=2, max_length=24)
    rooms: int = Field(ge=1, le=15)
    phone: str = Field(min_length=9, max_length=64)
    photos: List[str] = Field(default_factory=list, max_length=10)
    rightsConfirmed: bool = False
    consentVersion: str = Field(default="", max_length=64)
    gpon: bool = False
    generator: bool = False
    initData: Optional[str] = Field(default=None, max_length=8192)

class SendContactRequest(BaseModel):
    dealId: int = Field(ge=1)
    initData: str = Field(min_length=1, max_length=8192)

# ==========================================
# API ROUTES
# ==========================================

@app.api_route("/api/health", methods=["GET", "HEAD"])
async def health():
    deals = load_effective_deals()
    return {
        "status": "healthy",
        "service": "kyiv-radar-api",
        "version": "1.8.0",
        "deals_count": len(deals),
        "timestamp": int(time.time())
    }

@app.api_route("/api/deals", methods=["GET", "HEAD"])
async def get_live_deals(response: Response):
    """
    Live catalog endpoint.
    Serves synchronized listings from the verified catalog.
    Raw landlord phone numbers are strictly stripped for privacy protection.
    """
    # Revocation must not be defeated by HTTP/proxy/browser response caching.
    response.headers["Cache-Control"] = "no-store, max-age=0"
    deals = load_effective_deals()
    sanitized = []
    public_fields = frozenset(["id","title","district","address","metro","walkMin","price","realtorCommissionSaved","area","floor","totalFloors","lat","lng","generator","gpon","gas","lowFloor","pets","url","images","desc","rooms","source","status","verifiedAt","isOwnerVerified","cleanAddress","verificationStatus","statusLabel","reviewedByRadar","contactVerified","actualityConfirmed","commissionVerified","commissionNote","phoneMasked"])
    for d in deals:
        if not isinstance(d, dict):
            continue
        # Explicit public response shape prevents accidental future leaks.
        c = {field: d[field] for field in public_fields if field in d}
        c["phone"] = None
        # Remove obsolete autogenerated advertising claims from older catalogs too.
        # A historic imported description is not evidence of ownership, commission,
        # utilities, furnishings or internet availability.
        if isinstance(c.get("desc"), str):
            c["desc"] = c["desc"].replace(
                "Здається реальна квартира від власника без посередників. ", ""
            ).replace(
                " Повний комплект меблів та техніки, інтернет працює стабільно.", ""
            ).strip()
        # Owners have not opted in to publishing their names through this API.
        sanitized.append(c)
    return {
        "success": True,
        "count": len(sanitized),
        "deals": sanitized,
        "timestamp": int(time.time())
    }

@app.post("/api/reports")
async def submit_report(req: ReportRequest, request: Request):
    client_ip = client_ip_for_rate_limit(request)
    if not check_rate_limit(f"report_{client_ip}", max_requests=10, window_seconds=600):
        raise HTTPException(status_code=429, detail="Забагато скарг. Спробуйте пізніше.")

    if not req.reason or len(req.reason.strip()) < 3:
        raise HTTPException(status_code=400, detail="Вкажіть причину скарги")

    user_data = validate_telegram_init_data(req.initData) if req.initData else None
    user_label = f"Telegram ID: {user_data.get('id')}" if user_data else "Веб"

    comp_id = 0
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO complaints (deal_id, reason, details, reporter_info)
            VALUES (?, ?, ?, ?)
        """, (req.dealId, req.reason.strip(), req.details.strip() if req.details else "", user_label))
        comp_id = cur.lastrowid
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error("Unable to save a report (%s)", type(e).__name__)
        raise HTTPException(status_code=500, detail="Помилка збереження скарги на сервері")

    safe_reason = html.escape(req.reason.strip())
    safe_details = html.escape(req.details.strip()) if req.details else "не вказано"
    safe_user = html.escape(user_label)

    admin_msg = (
        f"🚨 <b>НОВА СКАРГА #{comp_id} НА ЛОТ #{req.dealId}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ <b>Причина:</b> {safe_reason}\n"
        f"📝 <b>Деталі:</b> {safe_details}\n"
        f"👤 <b>Відправник:</b> {safe_user}\n"
    )
    admin_kb = {
        "inline_keyboard": [
            [
                {"text": "🗑 Приховати лот з каталогу", "callback_data": f"rep_hide_{req.dealId}_{comp_id}"},
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

def cleanup_abandoned_uploads(max_age_hours: int = 48) -> None:
    """Remove aged unclaimed files and rejected submissions; never purge approved photos."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5.0)
        # Coordinate cleanup with submissions and moderation in other processes.
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            "SELECT u.photo_id FROM landlord_uploads u "
            "LEFT JOIN landlord_submissions s ON s.id = u.submission_id "
            "WHERE u.status = 'pending' AND ("
            "(u.submission_id IS NULL AND u.created_at < datetime('now', ?)) OR "
            "(u.submission_id IS NOT NULL AND s.status IN ('rejected', 'declined') "
            "AND u.created_at < datetime('now', '-7 days'))"
            ") LIMIT 100",
            (f"-{max_age_hours} hours",)
        ).fetchall()
        for (photo_id,) in rows:
            if not PHOTO_ID_PATTERN.fullmatch(photo_id):
                continue
            path = os.path.join(UPLOADS_BASE_DIR, photo_id + ".webp")
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                continue
            conn.execute(
                "DELETE FROM landlord_uploads WHERE photo_id = ? AND status = 'pending'",
                (photo_id,)
            )
        conn.commit()
    except sqlite3.Error:
        if conn:
            conn.rollback()
        logger.warning("Unable to purge abandoned uploads")
    finally:
        if conn:
            conn.close()


@app.get("/api/media/{photo_id}")
async def get_approved_photo(photo_id: str):
    """Serve a photo only after the corresponding listing has been approved."""
    if not PHOTO_ID_PATTERN.fullmatch(photo_id):
        raise HTTPException(status_code=404, detail="Фото не знайдено")
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    try:
        row = conn.execute(
            "SELECT status FROM landlord_uploads WHERE photo_id = ?",
            (photo_id,)
        ).fetchone()
    finally:
        conn.close()
    if not row or row[0] != "approved":
        raise HTTPException(status_code=404, detail="Фото не знайдено")
    path = os.path.join(UPLOADS_BASE_DIR, photo_id + ".webp")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Фото не знайдено")
    return FileResponse(path, media_type="image/webp",
                        headers={"Cache-Control": "public, max-age=86400",
                                 "X-Content-Type-Options": "nosniff"})


async def send_landlord_photo_previews(photo_ids: List[str], submission_id: int) -> bool:
    """Deliver pending photos privately to the moderator; never publish a preview URL."""
    if not photo_ids:
        return True
    media = []
    form = aiohttp.FormData()
    form.add_field("chat_id", str(ADMIN_CHAT_ID))
    for index, photo_id in enumerate(photo_ids):
        path = os.path.join(UPLOADS_BASE_DIR, photo_id + ".webp")
        try:
            with Image.open(path) as img:
                output = io.BytesIO()
                img.convert("RGB").save(output, "JPEG", quality=78)
                jpeg_bytes = output.getvalue()
        except Exception as exc:
            logger.warning("Failed to prepare moderation preview: %s", type(exc).__name__)
            return False
        key = "photo" + str(index)
        form.add_field(key, jpeg_bytes, filename=key + ".jpg", content_type="image/jpeg")
        media.append({"type": "photo", "media": "attach://" + key,
                      **({"caption": f"Заявка #{submission_id}: фото для модерації"} if index == 0 else {})})
    if len(media) == 1:
        # Telegram sendMediaGroup requires at least two items.
        single_photo_id = photo_ids[0]
        path = os.path.join(UPLOADS_BASE_DIR, single_photo_id + ".webp")
        with Image.open(path) as img:
            output = io.BytesIO()
            img.convert("RGB").save(output, "JPEG", quality=78)
            only_photo = output.getvalue()
        form = aiohttp.FormData()
        form.add_field("chat_id", str(ADMIN_CHAT_ID))
        form.add_field("photo", only_photo, filename="preview.jpg", content_type="image/jpeg")
        form.add_field("caption", f"Заявка #{submission_id}: фото для модерації")
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    else:
        form.add_field("media", json.dumps(media))
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMediaGroup"
    try:
        async with aiohttp.ClientSession() as client:
            async with client.post(url, data=form, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status != 200:
                    logger.warning("Moderation photos could not be delivered (HTTP %s)", response.status)
                    return False
        return True
    except Exception as exc:
        # Never log request URLs because they contain the bot token.
        logger.warning("Moderation photo dispatch failed: %s", type(exc).__name__)
        return False


@app.post("/api/landlords/upload_photos")
async def upload_landlord_photos(
    request: Request,
    photos: List[UploadFile] = File(...),
    initData: str = Form(...),
    rightsConfirmed: bool = Form(False),
    consentVersion: str = Form("")
):
    """Stage private, owner-bound images for moderation. Returns opaque IDs, not URLs."""
    user = validate_telegram_init_data(initData)
    if not user or not isinstance(user.get("id"), int):
        raise HTTPException(status_code=401, detail="Відкрийте форму в Telegram для завантаження фото")
    user_id = user["id"]
    # Require the owner's declaration BEFORE persisting bytes. Verification of
    # legal rights remains a separate human moderation step.
    if not rightsConfirmed or consentVersion != LANDLORD_CONSENT_VERSION:
        raise HTTPException(
            status_code=400,
            detail="Підтвердьте права на фотографії та оновіть форму перед завантаженням"
        )
    request_bytes = request.headers.get("content-length")
    if request_bytes and request_bytes.isdigit() and int(request_bytes) > MAX_IMAGE_BATCH_BYTES + 1024 * 1024:
        raise HTTPException(status_code=413, detail="Перевищено максимальний обсяг завантаження")
    client_ip = client_ip_for_rate_limit(request)
    if not check_rate_limit(f"upload_user_{user_id}", max_requests=5, window_seconds=3600):
        raise HTTPException(status_code=429, detail="Забагато завантажень. Спробуйте пізніше")
    if not check_rate_limit(f"upload_ip_{client_ip}", max_requests=80, window_seconds=3600):
        raise HTTPException(status_code=429, detail="Забагато запитів")
    if not 1 <= len(photos) <= 10:
        raise HTTPException(status_code=400, detail="Оберіть від 1 до 10 фотографій")

    cleanup_abandoned_uploads()
    total_bytes = 0
    created_files = []
    photo_ids = []
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        for photo in photos:
            contents = await photo.read(MAX_IMAGE_BYTES + 1)
            total_bytes += len(contents)
            if total_bytes > MAX_IMAGE_BATCH_BYTES:
                raise HTTPException(status_code=413, detail="Загальний розмір фото перевищує 32 МБ")
            if len(contents) > MAX_IMAGE_BYTES:
                raise HTTPException(status_code=413, detail="Фото не може перевищувати 8 МБ")
            photo_id = uuid.uuid4().hex
            path = sanitize_and_save_photo(contents, photo_id + ".webp")
            created_files.append(path)
            conn.execute(
                "INSERT INTO landlord_uploads (photo_id, owner_telegram_id, status) VALUES (?, ?, 'pending')",
                (photo_id, user_id)
            )
            photo_ids.append(photo_id)
        conn.commit()
    except HTTPException:
        if conn: conn.rollback()
        for path in created_files:
            try: os.remove(path)
            except OSError: pass
        raise
    except (ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        if conn: conn.rollback()
        for path in created_files:
            try: os.remove(path)
            except OSError: pass
        raise HTTPException(status_code=400, detail="Пошкоджене або непідтримуване фото")
    except Exception as exc:
        if conn: conn.rollback()
        for path in created_files:
            try: os.remove(path)
            except OSError: pass
        logger.error("Photo upload failed: %s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Не вдалося зберегти фотографії")
    finally:
        if conn: conn.close()
    return {"success": True, "count": len(photo_ids), "photos": photo_ids}


@app.post("/api/landlords/submit")
async def submit_landlord_deal(req: LandlordSubmitRequest, request: Request):
    client_ip = client_ip_for_rate_limit(request)
    if not check_rate_limit(f"landlord_{client_ip}", max_requests=25, window_seconds=3600):
        raise HTTPException(status_code=429, detail="Забагато заявок з вашої адреси. Спробуйте пізніше.")

    if len(req.address.strip()) < 5:
        raise HTTPException(status_code=400, detail="Вкажіть повну адресу квартири (вулиця, номер будинку)")
    if not req.phone or len(req.phone.strip()) < 9:
        raise HTTPException(status_code=400, detail="Вкажіть коректний номер телефону")
    digits = re.sub(r"\D", "", req.phone)
    if not re.fullmatch(r"\+?[0-9()\s-]{9,20}", req.phone.strip()) or not 9 <= len(digits) <= 15:
        raise HTTPException(status_code=400, detail="Номер телефону має містити від 9 до 15 цифр")
    normalized_price = re.sub(r"\s", "", req.price)
    if not normalized_price.isascii() or not normalized_price.isdigit() or int(normalized_price) <= 0:
        raise HTTPException(status_code=400, detail="Ціна оренди має бути додатним числом у гривнях")
    if not req.rightsConfirmed:
        raise HTTPException(
            status_code=400,
            detail="Підтвердьте право розміщувати оголошення, фотографії та контакт"
        )
    if req.consentVersion != LANDLORD_CONSENT_VERSION:
        raise HTTPException(status_code=400, detail="Оновіть форму та повторно підтвердьте права")

    user_data = validate_telegram_init_data(req.initData) if req.initData else None
    if not user_data or not isinstance(user_data.get("id"), int):
        raise HTTPException(status_code=401, detail="Для подання заявки відкрийте додаток у Telegram")
    user_id = user_data["id"]
    if not check_rate_limit(f"submit_user_{user_id}", max_requests=5, window_seconds=3600):
        raise HTTPException(status_code=429, detail="Забагато заявок. Спробуйте пізніше")
    user_label = f"@{user_data.get('username', 'anon')} (TG ID: {user_id})"

    photo_ids = req.photos or []
    if len(set(photo_ids)) != len(photo_ids) or any(
        not isinstance(photo_id, str) or not PHOTO_ID_PATTERN.fullmatch(photo_id)
        for photo_id in photo_ids
    ):
        raise HTTPException(status_code=400, detail="Некоректні ідентифікатори фотографій")
    photos_json = json.dumps(photo_ids)
    sub_id = 0
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        cur = conn.cursor()
        cur.execute("BEGIN IMMEDIATE")
        if photo_ids:
            markers = ",".join("?" for _ in photo_ids)
            verified = cur.execute(
                f"SELECT photo_id FROM landlord_uploads WHERE photo_id IN ({markers}) "
                "AND owner_telegram_id = ? AND submission_id IS NULL AND status = 'pending'",
                (*photo_ids, user_id)
            ).fetchall()
            if len(verified) != len(photo_ids):
                raise HTTPException(status_code=403, detail="Фото не належать цій заявці або вже використані")
        cur.execute("""
            INSERT INTO landlord_submissions
            (address, price, rooms, phone, photos, submitter_id, gpon, generator, status, moderator_notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending_review', ?)
        """, (req.address.strip(), req.price.strip(), req.rooms, req.phone.strip(), photos_json,
              user_id, 1 if req.gpon else 0, 1 if req.generator else 0, f"Подав: {user_label}"))
        sub_id = cur.lastrowid
        # Same SQLite transaction: a failed receipt must not leave a submission.
        # The receipt records a dated self-declaration, not a completed verification.
        cur.execute(
            "INSERT INTO landlord_consent_receipts "
            "(submission_id, consent_version, statement_sha256) VALUES (?, ?, ?)",
            (sub_id, LANDLORD_CONSENT_VERSION, LANDLORD_CONSENT_HASH)
        )
        if photo_ids:
            cur.execute(
                f"UPDATE landlord_uploads SET submission_id = ? WHERE photo_id IN ({markers}) "
                "AND owner_telegram_id = ? AND submission_id IS NULL AND status = 'pending'",
                (sub_id, *photo_ids, user_id)
            )
            if cur.rowcount != len(photo_ids):
                raise HTTPException(status_code=409, detail="Не вдалося закріпити фотографії за заявкою")
        conn.commit()
    except HTTPException:
        if conn: conn.rollback()
        raise
    except sqlite3.Error as exc:
        if conn: conn.rollback()
        logger.error("Failed to save submission: %s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Помилка збереження заявки")
    finally:
        if conn: conn.close()

    safe_addr = html.escape(req.address.strip())
    safe_price = html.escape(req.price.strip())
    safe_phone = html.escape(req.phone.strip())
    safe_user = html.escape(user_label)
    photos_count = len(req.photos) if req.photos else 0
    photos_desc = f"📸 <b>Фото:</b> {photos_count} шт." if photos_count > 0 else "📸 <b>Фото:</b> без фото"

    admin_lines = [
        f"🏢 <b>НОВА ЗАЯВКА НА ОРЕНДУ #{sub_id}</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"📍 <b>Адреса:</b> {safe_addr}",
        f"💰 <b>Ціна:</b> {safe_price} ₴/міс",
        f"🚪 <b>Кімнат:</b> {req.rooms}",
        f"📞 <b>Контакт:</b> <code>{safe_phone}</code>",
        f"{photos_desc}",
        f"⚡ <b>Генератор:</b> {'Так' if req.generator else 'Ні'} | 🌐 <b>GPON:</b> {'Так' if req.gpon else 'Ні'}",
        "",
        f"👤 <b>Джерело:</b> {safe_user}",
        "📝 Права заявлені автором заявки; документи й права на фото ще не перевірені."
    ]
    admin_kb = {
        "inline_keyboard": [
            [
                {"text": "✅ Опублікувати в каталог", "callback_data": f"ll_approve_{sub_id}"},
                {"text": "❌ Відхилити", "callback_data": f"ll_reject_{sub_id}"}
            ]
        ]
    }
    previews_sent = await send_landlord_photo_previews(photo_ids, sub_id)
    if not previews_sent:
        admin_lines.append("⚠️ Фото не доставлено модератору. Не публікувати без перегляду.")
    alert_sent = await send_telegram_alert(
        "\n".join(admin_lines),
        reply_markup=admin_kb if previews_sent else None
    )

    return {
        "success": True,
        "id": sub_id,
        "alert_delivered": alert_sent,
        "photos_preview_delivered": previews_sent,
        "message": f"Вашу квартиру #{sub_id} прийнято на модерацію. Дякуємо!"
    }

@app.post("/api/send_contact")
async def send_contact(req: SendContactRequest):
    """
    CRITICAL SECURITY HARDENING:
    - Cryptographic authentication of Telegram user.
    - Sliding window rate limiting per user ID (max 10 requests/hour) to defeat scraping.
    - Resolves raw phone from secure private store (never returns raw phone to client payload).
    - Sends direct Telegram message with verified landlord details.
    """
    user_data = validate_telegram_init_data(req.initData)
    if not user_data or "id" not in user_data:
        raise HTTPException(
            status_code=401,
            detail="Помилка авторизації Telegram. Відкрийте додаток у Telegram для надсилання номеру в чат."
        )

    user_id = user_data["id"]

    # Rate limiting on contact requests per Telegram user ID
    if not check_rate_limit(f"send_contact_{user_id}", max_requests=10, window_seconds=3600):
        raise HTTPException(
            status_code=429,
            detail="Перевищено ліміт запитів контактів (максимум 10 на годину). Будь ласка, спробуйте пізніше."
        )

    # Server-side lookup of deal by dealId
    deals = load_effective_deals()
    deal = next((d for d in deals if d.get("id") == req.dealId), None)
    if not deal:
        raise HTTPException(status_code=404, detail=f"Оголошення #{req.dealId} не знайдено у базі даних.")

    priv = get_private_contact(req.dealId)
    raw_phone = priv.get("phone") if priv else deal.get("phone")
    if not raw_phone or not str(raw_phone).strip():
        raise HTTPException(status_code=404, detail="Контакт цього оголошення наразі недоступний")
    trusted_phone = str(raw_phone).strip()

    safe_title = html.escape(deal.get("title", "Квартира"))
    safe_address = html.escape(deal.get("address", "Київ"))
    safe_phone = html.escape(trusted_phone)
    trusted_price = deal.get("price")
    price_text = f"{trusted_price:,}".replace(",", " ") if isinstance(trusted_price, int) and trusted_price > 0 else "Уточнюється"

    commission_label = "0% комісії (підтверджено)" if deal.get("commissionVerified") else "Комісія уточнюється"
    msg_lines = [
        f"📞 <b>Контакт з оголошення (Лот #{req.dealId})</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"🏢 <b>{safe_title}</b>",
        f"📍 {safe_address}",
        f"💰 <b>Ціна:</b> {price_text}{' ₴/міс' if isinstance(trusted_price, int) and trusted_price > 0 else ''} ({commission_label})",
        "",
        f"📱 <b>Контактний номер:</b> <code>{safe_phone}</code>",
        "",
        "<i>Перед дзвінком уточніть актуальність, чи це власник, та умови комісії.</i>"
    ]
    sent = await send_telegram_alert("\n".join(msg_lines), target_chat=user_id)
    if not sent:
        raise HTTPException(
            status_code=502,
            detail="Не вдалося доставити контакт у Telegram. Відкрийте «Київ Радар» у Telegram, натисніть «Старт» (/start) і повторіть запит."
        )

    return {
        "success": True,
        "dealId": req.dealId,
        "phoneMasked": deal.get("phoneMasked"),
        "message": "Контакт орендодавця успішно надіслано у ваш чат Telegram!"
    }
