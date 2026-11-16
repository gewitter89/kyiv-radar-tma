# -*- coding: utf-8 -*-
"""
Kyiv Radar Canonical Moderation Logic
Used by bot.py on VPS and validated by isolated test suites.

Features:
- Two-phase atomic publishing: writes deals.json first, then commits SQLite status.
- Decoupled Contact Verification: approval publishes listing with contactVerified=False ("Контакт не перевірено").
- Separate process_contact_verification method to record physical contact confirmation with timestamp & method.
- Idempotency & self-healing: handles repeat approvals gracefully, heals missing deals in catalog.
"""

import os
import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

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
    two-phase atomic catalog writing, and decoupled contact verification.
    """
    # 1. Strict Moderator Authorization Check
    if caller_id != admin_id:
        return {
            "success": False,
            "error": "Доступ заборонено: дія дозволена лише головному модератору."
        }

    # 2. Database inspection
    conn = sqlite3.connect(db_path, timeout=10.0)
    cur = conn.cursor()
    cur.execute(
        "SELECT status, address, price, rooms, phone, gpon, generator FROM landlord_submissions WHERE id = ?",
        (sub_id,)
    )
    row = cur.fetchone()

    if not row:
        conn.close()
        return {
            "success": False,
            "error": f"Заявку #{sub_id} не знайдено в базі даних."
        }

    current_status, address, price_raw, rooms_val, phone_val, gpon_val, gen_val = row

    # 3. Read current deals catalog
    deals_list = []
    if os.path.exists(deals_path):
        try:
            with open(deals_path, 'r', encoding='utf-8') as df:
                deals_list = json.load(df)
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
            "phone": phone_val,
            "phoneMasked": phone_val[:6] + "***" if len(phone_val) >= 6 else phone_val,
            "images": [],
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

    # 5. Two-phase commit: Atomic write to deals_path via temporary file
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
            "error": f"Помилка атомарного збереження у файл каталогу: {e}"
        }

    # 6. Commit SQLite status only AFTER successful deals.json write
    try:
        cur.execute(
            "UPDATE landlord_submissions SET status = 'published', moderator_notes = ? WHERE id = ?",
            (moderator_notes, sub_id)
        )
        conn.commit()
    except Exception as e:
        logger.error(f"DB update error after deals.json write: {e}")
    finally:
        conn.close()

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
    Marks contactVerified=True with timestamp and method in both SQLite and deals.json.
    """
    # 1. Authorization
    if caller_id != admin_id:
        return {
            "success": False,
            "error": "Доступ заборонено: дія дозволена лише головному модератору."
        }

    conn = sqlite3.connect(db_path, timeout=10.0)
    cur = conn.cursor()
    cur.execute("SELECT status, address, phone FROM landlord_submissions WHERE id = ?", (sub_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return {
            "success": False,
            "error": f"Заявку #{sub_id} не знайдено."
        }

    now_iso = datetime.now(timezone.utc).isoformat()
    moderator_notes = f"Контакт перевірено ({method}) о {now_iso[:19]}"

    # Update deals.json
    deals_list = []
    if os.path.exists(deals_path):
        try:
            with open(deals_path, 'r', encoding='utf-8') as df:
                deals_list = json.load(df)
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

    # Atomic write to deals_path
    tmp_path = f"{deals_path}.tmp"
    try:
        with open(tmp_path, 'w', encoding='utf-8') as df:
            json.dump(deals_list, df, ensure_ascii=False, indent=2)
        os.replace(tmp_path, deals_path)
    except Exception as e:
        conn.close()
        return {"success": False, "error": f"Помилка збереження каталогу: {e}"}

    # Update SQLite
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
        conn.commit()
    except sqlite3.OperationalError:
        # Fallback if columns don't exist yet
        try:
            cur.execute(
                "UPDATE landlord_submissions SET moderator_notes = ? WHERE id = ?",
                (moderator_notes, sub_id)
            )
            conn.commit()
        except Exception as e2:
            logger.error(f"Fallback DB update error: {e2}")
    except Exception as e:
        logger.error(f"Error updating landlord_submissions verification: {e}")
    finally:
        conn.close()

    return {
        "success": True,
        "message": f"✅ Контакт заявки #{sub_id} успішно підтверджено ({method})!",
        "updated_deal": deal
    }
