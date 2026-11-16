# -*- coding: utf-8 -*-
"""
Kyiv Radar Canonical Moderation Logic
Used by bot.py on VPS and validated by test_isolated_staging.py.
"""

import json
import logging
import sqlite3
from typing import Dict, Any, Optional

def process_landlord_approval(
    sub_id: int,
    caller_id: int,
    admin_id: int,
    db_path: str,
    deals_path: str,
    moderator_notes: str = "Схвалено модератором"
) -> Dict[str, Any]:
    """
    Executes the complete moderation approval workflow with strict authorization
    and zero fictitious defaults.
    """
    # 1. Strict Moderator Authorization Check
    if caller_id != admin_id:
        return {
            "success": False,
            "error": "Доступ заборонено: дія дозволена лише головному модератору."
        }

    # 2. Database update
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("UPDATE landlord_submissions SET status = 'published', moderator_notes = ? WHERE id = ?", (moderator_notes, sub_id))
    cur.execute("SELECT address, price, rooms, phone, gpon, generator FROM landlord_submissions WHERE id = ?", (sub_id,))
    row = cur.fetchone()
    conn.commit()
    conn.close()

    if not row:
        return {
            "success": False,
            "error": f"Заявку #{sub_id} не знайдено в базі даних."
        }

    # 3. Clean deal creation with ZERO fictitious attributes
    deals_list = []
    try:
        with open(deals_path, 'r', encoding='utf-8') as df:
            deals_list = json.load(df)
    except Exception:
        deals_list = []

    new_id = max([d.get('id', 0) for d in deals_list] + [0]) + 1
    raw_price = str(row[1]).replace(" ", "").strip()
    price_val = int(raw_price) if raw_price.isdigit() else None
    saved_val = round(price_val / 2) if price_val else None

    new_deal = {
        "id": new_id,
        "title": f"Квартира від власника: {row[0]}",
        "district": "Київ",
        "address": row[0],
        "cleanAddress": row[0],
        "metro": None,            # Truthful: None unless determined by geocoding
        "walkMin": None,          # Truthful: None
        "price": price_val,
        "realtorCommissionSaved": saved_val,
        "area": None,             # Truthful: None
        "floor": None,            # Truthful: None
        "totalFloors": None,      # Truthful: None
        "rooms": row[2] or 1,
        "lat": None,              # Truthful: None (safeguarded on map)
        "lng": None,
        "generator": bool(row[5]) if row[5] is not None else None,
        "gpon": bool(row[4]) if row[4] is not None else None,
        "gas": None,
        "lowFloor": None,
        "pets": None,
        "ownerName": "Орендодавець",
        "phone": row[3],
        "phoneMasked": row[3][:6] + "***" if len(row[3]) >= 6 else row[3],
        "images": [],             # Truthful: Empty array without stock photos
        "desc": "Оголошення додано власником через Київ Радар.",
        "source": "Київ Радар (Власник)",
        "status": "Опубліковано",
        "isOwnerVerified": False, # Truthful: False without title deeds
        "contactVerified": False, # Truthful: False until physical phone verification
        "moderationStatus": "approved",
        "verifiedAt": None
    }

    deals_list.insert(0, new_deal)
    with open(deals_path, 'w', encoding='utf-8') as df:
        json.dump(deals_list, df, ensure_ascii=False, indent=2)

    return {
        "success": True,
        "message": "✅ Оголошення успішно схвалено та додано в каталог!",
        "published_deal": new_deal
    }
