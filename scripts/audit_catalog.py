#!/usr/bin/env python3
"""Read-only publication quality audit for Kyiv Radar.

This script cannot verify a real landlord, live source link, occupancy or
permission to reproduce photos. Those require a human review with evidence.
It records concrete data problems, never fabricates verification decisions.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {"OLX", "DOM.RIA"}
TEXT_DEBRIS = re.compile(r"(грн\s*Додати в обране|Додати в обране)", re.IGNORECASE)
STREET = re.compile(r"(вул\.|вулиц|просп|провул|бульвар|шосе|набереж)", re.IGNORECASE)
PRIVATE_KEYS = {"phone", "ownerName", "ownerTg", "reporter_info", "initData", "adminNotes"}


def audit_catalog(records: list) -> dict:
    problems: dict[str, list[int]] = defaultdict(list)
    fatal = []
    seen: set[int] = set()
    counts = Counter()
    if not isinstance(records, list):
        return {"total": 0, "fatal": ["Каталог має бути масивом"], "counts": {},
                "flagged_ids": {}, "ready_for_public_claims": False}
    for idx, row in enumerate(records):
        if not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] <= 0:
            fatal.append(f"Некоректна структура елемента {idx}")
            continue
        id_ = row["id"]
        if id_ in seen:
            fatal.append(f"Повторений ID {id_}")
        seen.add(id_)
        counts["total"] += 1

        if any(key in row and row[key] not in (None, "", False) for key in PRIVATE_KEYS):
            fatal.append(f"Публічні особисті дані в оголошенні {id_}")
        if row.get("source") in SOURCES:
            counts["imported"] += 1
            if row.get("isOwnerVerified") is not True:
                counts["imported_unverified_owner"] += 1
            if row.get("actualityConfirmed") is not True:
                counts["imported_unverified_actuality"] += 1
            problems["source_rights_need_review"].append(id_)
        else:
            counts["first_party_or_unknown_source"] += 1

        address = str(row.get("address") or "")
        if TEXT_DEBRIS.search(address):
            problems["scraped_address_noise"].append(id_)
        if not STREET.search(address):
            problems["not_exact_street_address"].append(id_)
        if row.get("locationVerified") is not True and row.get("lat") is not None:
            problems["unverified_exact_coordinates"].append(id_)
        title = str(row.get("title") or "")
        if not title.strip() or len(title) > 500:
            problems["missing_or_unreadable_title"].append(id_)
        if not isinstance(row.get("price"), (int, float)) or row.get("price", 0) <= 0:
            problems["invalid_price"].append(id_)
        if not isinstance(row.get("images"), list) or not row["images"]:
            problems["photos_missing"].append(id_)
        url = row.get("url")
        if isinstance(url, str) and url:
            try:
                parsed = urlparse(url)
                if parsed.scheme != "https" or not parsed.hostname:
                    problems["source_link_invalid"].append(id_)
            except ValueError:
                problems["source_link_invalid"].append(id_)
        else:
            problems["source_link_missing"].append(id_)

        if row.get("isOwnerVerified") is True:
            counts["owner_verified_claims"] += 1
        if row.get("actualityConfirmed") is True:
            counts["actuality_verified_claims"] += 1

    flagged = {key: sorted(set(ids)) for key, ids in sorted(problems.items())}
    counts["eligible_for_verified_new_listing_alerts"] = 0
    # No trusted publication timestamp/source rights are established by the
    # imported catalog. A feed count alone never proves eligibility.
    counts["eligible_for_sponsored_placement"] = 0
    ready = bool(counts["total"]) and not fatal and not problems.get("source_rights_need_review") \
            and not problems.get("unverified_exact_coordinates")
    return {
        "total": counts["total"],
        "fatal": fatal,
        "counts": dict(counts),
        "flagged_ids": flagged,
        "ready_for_public_claims": ready,
        "limitations": (
            "Відсутність попереджень не означає перевірку актуальності, власності чи прав на фото. "
            "Посилання на джерела та стан житла перевіряє людина."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", default=str(ROOT / "data/deals.json"))
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    try:
        rows = json.loads(Path(args.catalog).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        print(json.dumps({"fatal": ["Каталог неможливо прочитати"], "kind": type(error).__name__},
                         ensure_ascii=False))
        return 2
    result = audit_catalog(rows)
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        dest = Path(args.output)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text + "\n", encoding="utf-8")
    print(json.dumps({
        "total": result["total"], "fatal_count": len(result["fatal"]),
        "imported_unverified": result["counts"].get("imported_unverified_actuality", 0),
        "manual_checks": {kind: len(ids) for kind, ids in result["flagged_ids"].items()},
        "ready_for_public_claims": result["ready_for_public_claims"],
    }, ensure_ascii=False, sort_keys=True))
    return 2 if result["fatal"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
