#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate only synthetic test catalog inside disposable CI checkout.

Never includes original listing, photo, contact, or private feed. Repository
index.html and data/deals.json must contain ONLY empty arrays at checkout.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "index.html"
DATA = ROOT / "data" / "deals.json"
PATTERN = re.compile(r"const KYIV_DEALS_INIT = \[\];")


def synthetic_records():
    records = []
    for i in range(1, 151):
        is_olx = i <= 89
        source = "OLX" if is_olx else "DOM.RIA"
        rooms = (i % 3) + 1
        # Deliberate SYNTHETIC conflicts exercise conservative UX.
        title_rooms = 5 if 30 <= i <= 43 else rooms
        title = f"ТЕСТ: {title_rooms} кімн, вигадана квартира №{i}; НЕ ПУБЛІКУВАТИ"
        address = ("Київ, тестовий район, грн Додати в обране" if 100 <= i <= 107
                   else "Київ, умовна адреса для QA, Позняки")
        url = (f"https://www.olx.ua/d/uk/obyavlenie/synthetic-test-only-IDQATEST{i:05}.html"
               if is_olx else f"https://dom.ria.com/uk/realty-synthetic-test-only-{i:05}.html")
        if i == 149:
            url = "https://dom.ria.com/uk/realty-synthetic-test-only-00148.html"
        photos = [f"https://images.example.invalid/kyiv-radar-test-only/{i:04}-{n}.jpg"
                  for n in (1, 2, 3)]
        records.append({
            "id": i, "title": title,
            "district": "Дарницький" if i % 3 else "Печерський",
            "address": address, "cleanAddress": "Тестовий район",
            "metro": None, "walkMin": None,
            "price": 9000 + (i % 24) * 500,
            "realtorCommissionSaved": None,
            "area": 32 + i % 50, "floor": 1 + i % 11, "totalFloors": 16,
            "lat": round(50.39 + (i % 20) / 1000, 6),
            "lng": round(30.60 + (i % 20) / 1000, 6),
            "locationVerified": False, "rooms": rooms,
            "generator": i % 4 == 0, "gpon": i % 5 == 0,
            "gas": False, "lowFloor": i % 4 == 0,
            "pets": i % 3 == 0, "phone": None,
            "phoneMasked": None,
            "url": url, "images": photos,
            "desc": "ЛИШЕ СИНТЕТИЧНИЙ ТЕСТ. Не реальна нерухомість.",
            "source": source, "status": "Тестове",
            "isOwnerVerified": False, "contactVerified": False,
            "actualityConfirmed": False, "commissionVerified": False,
            "commissionNote": "Комісія уточнюється",
            "verificationStatus": "imported", "statusLabel": "Тестовий запис",
            "fixtureOnly": True
        })
    return records


def main():
    if os.environ.get("CI") != "true" or os.environ.get("APP_ENV") != "test":
        raise SystemExit("DENIED: generation is permitted only in isolated CI test checkout")
    assert json.loads(DATA.read_text(encoding="utf-8")) == [], "Public JSON must stay empty"
    html = HTML.read_text(encoding="utf-8")
    assert len(PATTERN.findall(html)) == 1, "Public HTML must have exactly one empty fixture slot"
    records = synthetic_records()
    assert len(records) == 150 and all(row["fixtureOnly"] for row in records)
    encoded = json.dumps(records, ensure_ascii=False, separators=(",", ":"))
    HTML.write_text(PATTERN.sub(lambda _: "const KYIV_DEALS_INIT = " + encoded + ";", html),
                    encoding="utf-8")
    DATA.write_text(encoded + "\n", encoding="utf-8")
    print("CI ONLY: generated 150 synthetic fixture records (not actual apartments)")


if __name__ == "__main__":
    main()
