# -*- coding: utf-8 -*-
"""
Kyiv Radar Canonical Moderation Logic
Used by bot.py on VPS and validated by isolated test suites.

Features:
- Concurrency Control: threading.Lock prevents race conditions during simultaneous moderation approvals.
- True Two-Phase Publishing with Compensating Rollback:
    1. Pre-execution snapshot of deals.json.
    2. Atomic file write via temporary file (.tmp -> .json).
    3. SQLite status update & commit.
    4. If SQLite commit fails at step 3, automatic compensating rollback restores deals.json to snapshot,
       rolls back DB transaction, and returns success=False (no false success or desynced catalog).
- Decoupled Contact Verification: approval publishes listing with contactVerified=False ("Контакт не перевірено").
- Explicit process_contact_verification method to record physical contact confirmation with timestamp & method,
  also protected by lock and compensating rollback.
- Idempotency & self-healing: handles repeat approvals gracefully, heals missing deals in catalog.
"""

import os
import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Concurrency lock to prevent simultaneous write race conditions on catalog
_moderation_lock = threading.Lock()

def process_landlord_approval(
    sub_id: int,
    caller_id: int,
    admin_id: int,
    db_path: str,
    deals_path: str,
    moderator_notes: str = "Схвалено модератором (Контакт очікує перевірки)"
) -> Dict[str, Any]:
    """
    Executes the canonical moderation approval workflow with strict authorization,
    concurrency locking, atomic catalog writing, and compensating rollback if SQLite fails.
    """
    # 1. Strict Moderator Authorization Check
    if caller_id != admin_id:
        return {
            "success": False,
            "error": "Доступ заборонено: дія дозволена лише головному модератору."
        }

    with _moderation_lock:
        # 2. Database inspection
        try:
            conn = sqlite3.connect(db_path, timeout=10.0)
            cur = conn.cursor()
            cur.execute("PRAGMA table_info(landlord_submissions)")
            sub_cols = [c[1] for c in cur.fetchall()]
            has_photos = "photos" in sub_cols
            if has_photos:
                cur.execute(
                    "SELECT status, address, price, rooms, phone, gpon, generator, photos FROM landlord_submissions WHERE id = ?",
                    (sub_id,)
                )
            else:
                cur.execute(
                    "SELECT status, address, price, rooms, phone, gpon, generator FROM landlord_submissions WHERE id = ?",
                    (sub_id,)
                )
            row = cur.fetchone()
        except Exception as db_init_err:
            return {
                "success": False,
                "error": f"Помилка доступу до бази даних: {db_init_err}"
            }

        if not row:
            conn.close()
            return {
                "success": False,
                "error": f"Заявку #{sub_id} не знайдено в базі даних."
            }

        current_status = row[0]
        address = row[1]
        price_raw = row[2]
        rooms_val = row[3]
        phone_val = row[4]
        gpon_val = row[5]
        gen_val = row[6]
        photos_val = []
        if has_photos and len(row) > 7 and row[7]:
            try:
                photos_val = json.loads(row[7])
            except Exception:
                photos_val = []

        # 3. Read current deals catalog and take pre-update byte snapshot for rollback
        deals_list = []
        pre_deals_bytes: Optional[bytes] = None
        if os.path.exists(deals_path):
            try:
                with open(deals_path, 'rb') as df_b:
                    pre_deals_bytes = df_b.read()
                deals_list = json.loads(pre_deals_bytes.decode('utf-8'))
            except Exception as e:
                conn.close()
                logger.error(f"Error reading {deals_path}: {e}")
                return {
                    "success": False,
                    "error": f"Помилка читання каталогу {deals_path}: {e}"
                }

        deal_in_catalog = next((d for d in deals_list if d.get("submission_id") == sub_id), None)

        # Idempotency check: only if published in DB AND already present in catalog
        if current_status == "published" and deal_in_catalog is not None:
            conn.close()
            return {
                "success": True,
                "already_approved": True,
                "message": f"ℹ️ Заявку #{sub_id} вже було схвалено раніше. Повторна публікація відхилена."
            }

        # 4. Construct truthful deal
        if deal_in_catalog is None:
            new_id = max([d.get('id', 0) for d in deals_list] + [0]) + 1
            raw_price = str(price_raw or "").replace(" ", "").strip()
            price_val = int(raw_price) if raw_price.isdigit() else None

            new_deal = {
                "id": new_id,
                "submission_id": sub_id,
                "title": f"Квартира від орендодавця: {address}",
                "district": "Київ",
                "address": address,
                "cleanAddress": address,
                "metro": None,
                "walkMin": None,
                "price": price_val,
                "realtorCommissionSaved": None, # TRUTHFUL: No fake savings
                "commissionVerified": False,    # TRUTHFUL: False without verified 0%
                "commissionNote": "Комісія уточнюється",
                "area": None,
                "floor": None,
                "totalFloors": None,
                "rooms": rooms_val or 1,
                "lat": None,
                "lng": None,
                "generator": bool(gen_val) if gen_val is not None else None,
                "gpon": bool(gpon_val) if gpon_val is not None else None,
                "gas": None,
                "lowFloor": None,
                "pets": None,
                "ownerName": "Орендодавець",
                "phone": None,  # PRIVACY: Raw phone stripped from public catalog
                "phoneMasked": phone_val[:6] + "***" if len(phone_val) >= 6 else phone_val,
                "images": photos_val if isinstance(photos_val, list) else [],
                "desc": "Оголошення додано орендодавцем через Київ Радар.",
                "source": "Київ Радар (Пряма заявка)",
                "status": "Опубліковано",
                "verificationStatus": "published_unverified",
                "statusLabel": "Контакт не перевірено",
                "isOwnerVerified": False, # Truthful: False without title deeds
                "contactVerified": False, # Truthful: False until explicit verification
                "actualityConfirmed": False,
                "moderationStatus": "approved",
                "verifiedAt": None,
                "phoneVerifiedAt": None,
                "phoneVerificationMethod": None
            }
            deals_list.insert(0, new_deal)
        else:
            new_deal = deal_in_catalog

        # 5. Phase 1: Atomic write to deals_path via temporary file
        tmp_path = f"{deals_path}.tmp"
        try:
            with open(tmp_path, 'w', encoding='utf-8') as df:
                json.dump(deals_list, df, ensure_ascii=False, indent=2)
            os.replace(tmp_path, deals_path)
        except Exception as e:
            conn.close()
            logger.error(f"Failed atomic write to {deals_path}: {e}")
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            return {
                "success": False,
                "error": f"Помилка збереження у файл каталогу: {e}"
            }

        # 6. Phase 2: Commit SQLite status.
        # CRITICAL FIX: If commit fails, execute compensating rollback of deals.json!
        try:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS private_deal_contacts (
                    deal_id INTEGER PRIMARY KEY,
                    phone TEXT NOT NULL,
                    owner_name TEXT,
                    phone_masked TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            masked_phone = phone_val[:6] + "***" if len(phone_val) >= 6 else phone_val
            cur.execute(
                "INSERT OR REPLACE INTO private_deal_contacts (deal_id, phone, owner_name, phone_masked) VALUES (?, ?, ?, ?)",
                (new_deal["id"], phone_val, "Орендодавець", masked_phone)
            )
            cur.execute(
                "UPDATE landlord_submissions SET status = 'published', moderator_notes = ? WHERE id = ?",
                (moderator_notes, sub_id)
            )
            conn.commit()
        except Exception as db_err:
            logger.error(f"DB update failed after catalog write: {db_err}. Rolling back catalog...")
            conn.rollback()
            # COMPENSATING TRANSACTION: Restore pre-update deals.json state
            try:
                if pre_deals_bytes is not None:
                    with open(tmp_path, 'wb') as df_rb:
                        df_rb.write(pre_deals_bytes)
                    os.replace(tmp_path, deals_path)
                elif os.path.exists(deals_path):
                    os.remove(deals_path)
                logger.info(f"Successfully rolled back catalog {deals_path} to pre-update snapshot.")
            except Exception as rb_err:
                logger.critical(f"FATAL: Compensating rollback of catalog failed: {rb_err}")
            finally:
                conn.close()

            return {
                "success": False,
                "error": f"Помилка фіксації статусу в SQLite: {db_err}. Каталог повернуто до початкового стану."
            }
        finally:
            try:
                conn.close()
            except Exception:
                pass

        return {
            "success": True,
            "already_approved": False,
            "message": f"✅ Оголошення #{sub_id} опубліковано в каталозі! (Контакт очікує перевірки)",
            "published_deal": new_deal
        }

def process_contact_verification(
    sub_id: int,
    caller_id: int,
    admin_id: int,
    db_path: str,
    deals_path: str,
    method: str = "phone"
) -> Dict[str, Any]:
    """
    Executes explicit moderator contact verification (e.g. after phone call).
    Marks contactVerified=True with timestamp and method in both SQLite and deals.json,
    protected by concurrency lock and compensating rollback.
    """
    # 1. Authorization
    if caller_id != admin_id:
        return {
            "success": False,
            "error": "Доступ заборонено: дія дозволена лише головному модератору."
        }

    with _moderation_lock:
        try:
            conn = sqlite3.connect(db_path, timeout=10.0)
            cur = conn.cursor()
            cur.execute("SELECT status, address, phone FROM landlord_submissions WHERE id = ?", (sub_id,))
            row = cur.fetchone()
        except Exception as db_err:
            return {"success": False, "error": f"Помилка бази даних: {db_err}"}

        if not row:
            conn.close()
            return {
                "success": False,
                "error": f"Заявку #{sub_id} не знайдено."
            }

        now_iso = datetime.now(timezone.utc).isoformat()
        moderator_notes = f"Контакт перевірено ({method}) о {now_iso[:19]}"

        # Read deals.json and take snapshot for rollback
        deals_list = []
        pre_deals_bytes: Optional[bytes] = None
        if os.path.exists(deals_path):
            try:
                with open(deals_path, 'rb') as df_b:
                    pre_deals_bytes = df_b.read()
                deals_list = json.loads(pre_deals_bytes.decode('utf-8'))
            except Exception as e:
                conn.close()
                return {"success": False, "error": f"Помилка читання {deals_path}: {e}"}

        deal = next((d for d in deals_list if d.get("submission_id") == sub_id), None)
        if not deal:
            conn.close()
            return {"success": False, "error": f"Оголошення #{sub_id} не знайдено в каталозі."}

        deal["contactVerified"] = True
        deal["verificationStatus"] = "contact_verified"
        deal["statusLabel"] = "Контакт перевірено"
        deal["phoneVerifiedAt"] = now_iso
        deal["phoneVerificationMethod"] = method

        # Phase 1: Atomic write to deals_path
        tmp_path = f"{deals_path}.tmp"
        try:
            with open(tmp_path, 'w', encoding='utf-8') as df:
                json.dump(deals_list, df, ensure_ascii=False, indent=2)
            os.replace(tmp_path, deals_path)
        except Exception as e:
            conn.close()
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            return {"success": False, "error": f"Помилка збереження каталогу: {e}"}

        # Phase 2: Update SQLite with strict full verification metadata and compensating rollback
        try:
            cur.execute(
                """UPDATE landlord_submissions 
                   SET moderator_notes = ?,
                       contact_verified = 1,
                       verified_at = ?,
                       verification_method = ?
                   WHERE id = ?""",
                (moderator_notes, now_iso, method, sub_id)
            )
            if cur.rowcount == 0:
                raise sqlite3.OperationalError(f"Заявку #{sub_id} не оновлено в SQLite (rowcount=0)")
            conn.commit()
        except Exception as e:
            logger.error(f"Error updating landlord_submissions verification in SQLite: {e}. Rolling back catalog...")
            conn.rollback()
            if pre_deals_bytes is not None:
                with open(tmp_path, 'wb') as df_rb:
                    df_rb.write(pre_deals_bytes)
                os.replace(tmp_path, deals_path)
            return {
                "success": False,
                "error": f"Помилка фіксації повних даних верифікації в базі даних: {e}. Каталог відновлено."
            }
        finally:
            try:
                conn.close()
            except Exception:
                pass

        return {
            "success": True,
            "message": f"✅ Контакт заявки #{sub_id} успішно підтверджено ({method})!",
            "updated_deal": deal
        }
