# -*- coding: utf-8 -*-
"""
Kyiv Radar Canonical Moderation Logic
Used by bot.py on VPS and validated by test_isolated_staging.py.
"""

import os
import json
import logging
import sqlite3
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

def process_landlord_approval(
    sub_id: int,
    caller_id: int,
    admin_id: int,
    db_path: str,
    deals_path: str,
    moderator_notes: str = "Схвалено модератором"
) -> Dict[str, Any]:
    """
    Executes the canonical moderation approval workflow with strict authorization,
    idempotency protection against duplicate publishes, and truthful attribute handling.
    """
    # 1. Strict Moderator Authorization Check
    if caller_id != admin_id:
        return {
            "success": False,
            "error": "Доступ заборонено: дія дозволена лише головному модератору."
        }

    # 2. Database inspection & idempotency guard
    conn = sqlite3.connect(db_path, timeout=10.0)
    cur = conn.cursor()
    cur.execute("SELECT status, address, price, rooms, phone, gpon, generator FROM landlord_submissions WHERE id = ?", (sub_id,))
    row = cur.fetchone()

    if not row:
        conn.close()
        return {
            "success": False,
            "error": f"Заявку #{sub_id} не знайдено в базі даних."
        }

    current_status, address, price_raw, rooms_val, phone_val, gpon_val, gen_val = row
    if current_status == "published":
        conn.close()
        return {
            "success": True,
            "already_approved": True,
            "message": f"ℹ️ Заявку #{sub_id} вже було схвалено раніше. Повторна публікація відхилена."
        }

    # Update database status atomically
    cur.execute("UPDATE landlord_submissions SET status = 'published', moderator_notes = ? WHERE id = ?", (moderator_notes, sub_id))
    conn.commit()
    conn.close()

    # 3. Clean deal creation with ZERO fictitious attributes
    deals_list = []
    if os.path.exists(deals_path):
        try:
            with open(deals_path, 'r', encoding='utf-8') as df:
                deals_list = json.load(df)
        except Exception as e:
            logger.error(f"Error reading {deals_path}: {e}")
            deals_list = []

    # Idempotency check in deals_list
    if any(d.get("submission_id") == sub_id for d in deals_list):
        return {
            "success": True,
            "already_approved": True,
            "message": f"ℹ️ Оголошення для заявки #{sub_id} вже присутнє в каталозі."
        }

    new_id = max([d.get('id', 0) for d in deals_list] + [0]) + 1
    raw_price = str(price_raw).replace(" ", "").strip()
    price_val = int(raw_price) if raw_price.isdigit() else None
    saved_val = round(price_val / 2) if price_val else None

    new_deal = {
        "id": new_id,
        "submission_id": sub_id,
        "title": f"Квартира від орендодавця: {address}",
        "district": "Київ",
        "address": address,
        "cleanAddress": address,
        "metro": None,            # Truthful: None unless determined by geocoding
        "walkMin": None,          # Truthful: None
        "price": price_val,
        "realtorCommissionSaved": saved_val,
        "area": None,             # Truthful: None
        "floor": None,            # Truthful: None
        "totalFloors": None,      # Truthful: None
        "rooms": rooms_val or 1,
        "lat": None,              # Truthful: None (safeguarded on map)
        "lng": None,
        "generator": bool(gen_val) if gen_val is not None else None,
        "gpon": bool(gpon_val) if gpon_val is not None else None,
        "gas": None,
        "lowFloor": None,
        "pets": None,
        "ownerName": "Орендодавець",
        "phone": phone_val,
        "phoneMasked": phone_val[:6] + "***" if len(phone_val) >= 6 else phone_val,
        "images": [],             # Truthful: Empty array without stock photos
        "desc": "Оголошення додано орендодавцем через Київ Радар.",
        "source": "Київ Радар (Пряма заявка)",
        "status": "Опубліковано",
        "verificationStatus": "contact_verified",
        "statusLabel": "Контакт перевірено",
        "isOwnerVerified": False, # Truthful: False without title deeds
        "contactVerified": True,  # True because phone was verified by moderator
        "actualityConfirmed": True,
        "moderationStatus": "approved",
        "verifiedAt": None
    }

    deals_list.insert(0, new_deal)

    # Atomic write to deals_path via temporary file
    tmp_path = f"{deals_path}.tmp"
    with open(tmp_path, 'w', encoding='utf-8') as df:
        json.dump(deals_list, df, ensure_ascii=False, indent=2)
    os.replace(tmp_path, deals_path)

    return {
        "success": True,
        "already_approved": False,
        "message": "✅ Оголошення успішно схвалено та додано в каталог!",
        "published_deal": new_deal
    }
