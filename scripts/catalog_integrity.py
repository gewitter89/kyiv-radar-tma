#!/usr/bin/env python3
"""Privacy-safe, read-only candidate duplicate audit of the Kyiv Radar catalog.

This is NOT a fraud classifier, freshness verifier or proof of publication rights.
It generates review suggestions; it never removes/merges records or edits sources.
It deliberately does not download or hash third-party photos.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
IMPORTED = {"OLX", "DOM.RIA"}
SOURCE_ID = re.compile(r"(?:-|/)(ID[A-Z0-9]{4,})(?:[./]|$)", re.I)
OLX_IMAGE_ID = re.compile(r"/v1/files/([a-z0-9-]{8,})", re.I)
ALLOWED_SCHEMES = {"http", "https"}


def canonical_url(raw: object) -> str | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        url = urlsplit(raw.strip())
        if url.scheme.lower() not in ALLOWED_SCHEMES or not url.hostname:
            return None
        # Ignore tracking queries and visual CDN transformations, but not
        # the path itself. No attempt to fetch or verify these URLs.
        host = url.hostname.lower().removeprefix("www.")
        path = unquote(url.path).strip().lower().rstrip("/")
        return host + path if path else None
    except ValueError:
        return None


def photo_key(raw: object) -> str | None:
    key = canonical_url(raw)
    if not key:
        return None
    match = OLX_IMAGE_ID.search(key)
    if match:
        return "olx-image:" + match.group(1).lower()
    # Strip OLX's encoded transform fragment, not the actual media ID.
    return "url:" + key.split(";s=")[0]


def source_key(row: dict) -> str | None:
    url = canonical_url(row.get("url"))
    if not url:
        return None
    match = SOURCE_ID.search(url)
    if match and "olx.ua/" in url:
        return "olx:" + match.group(1).lower()
    return "source-url:" + url


def has_publication_time(row: dict) -> bool:
    """Importer-local dates and text marked 'verifiedAt' are not publication dates."""
    for key in ("publishedAt", "published_at", "sourcePublishedAt"):
        value = row.get(key)
        if isinstance(value, str) and re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value
        ):
            return True
    return False


def has_last_seen(row: dict) -> bool:
    for key in ("lastSeenAt", "sourceLastSeenAt", "last_seen_at"):
        value = row.get(key)
        if isinstance(value, str) and re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value
        ):
            return True
    return False


def analyze_integrity(records: object) -> dict:
    if not isinstance(records, list):
        raise ValueError("Каталог має бути списком")
    photo_groups: dict[str, set[int]] = defaultdict(set)
    source_groups: dict[str, set[int]] = defaultdict(set)
    valid: list[dict] = []
    seen: set[int] = set()

    for item in records:
        if not isinstance(item, dict):
            continue
        lid = item.get("id")
        if type(lid) is not int or lid <= 0 or lid in seen:
            continue
        seen.add(lid)
        valid.append(item)
        sk = source_key(item)
        if sk:
            source_groups[sk].add(lid)
        for image in set(photo_key(raw) for raw in item.get("images", [])
                         if isinstance(raw, str)) if isinstance(item.get("images"), list) else set():
            if image:
                photo_groups[image].add(lid)

    # Pairwise evidence: high when two identical photo assets or same source
    # identity; review otherwise. One shared photo is never a fraud verdict.
    evidence: dict[tuple[int, int], dict[str, object]] = {}
    def mark(ids: set[int], kind: str, key: str) -> None:
        if len(ids) <= 1:
            return
        ordered = sorted(ids)
        for i, first in enumerate(ordered):
            for other in ordered[i+1:]:
                pair = (first, other)
                record = evidence.setdefault(pair, {"sources": set(), "shared_photos": set()})
                record[kind].add(key)

    for k, ids in source_groups.items():
        mark(ids, "sources", k)
    for k, ids in photo_groups.items():
        mark(ids, "shared_photos", k)

    candidates = []
    for (a,b), facts in sorted(evidence.items()):
        sources = facts["sources"]
        photos = facts["shared_photos"]
        high = bool(sources) or len(photos) >= 2
        why = []
        if sources:
            why.append("Повторна ідентичність джерела")
        if photos:
            why.append("Спільних фото: " + str(len(photos)))
        candidates.append({
            "ids": [a,b],
            "priority": "high_review" if high else "review",
            "signals": why,
            "shared_photo_count": len(photos),
            "same_source_identity": bool(sources),
            # No image URLs, personal phone, full description or private data.
            "is_duplicate": None,
            "is_fraud": None,
        })
    candidates.sort(key=lambda x: (
        x["priority"] != "high_review",
        -x["shared_photo_count"], x["ids"]
    ))
    imported = [r for r in valid if str(r.get("source", "")).strip().upper() in IMPORTED]
    return {
        "schema_version": 1,
        "total": len(valid),
        "source_distribution": {name: sum(str(r.get("source", "")).strip().upper() == name
                                          for r in valid) for name in sorted(IMPORTED)},
        "imported_without_evidence_of_republish_rights": len(imported),
        "unconfirmed_availability": sum(r.get("actualityConfirmed") is not True for r in valid),
        "unconfirmed_owner": sum(r.get("isOwnerVerified") is not True for r in valid),
        "unconfirmed_zero_commission": sum(r.get("commissionVerified") is not True for r in valid),
        "missing_source_publication_timestamp": sum(not has_publication_time(r) for r in valid),
        "missing_source_last_seen_timestamp": sum(not has_last_seen(r) for r in valid),
        "candidate_pairs": candidates,
        "candidate_pair_count": len(candidates),
        "high_review_count": sum(c["priority"] == "high_review" for c in candidates),
        "limitations": [
            "Спільне фото чи посилання не доводить, що пропозиція є шахрайською.",
            "Наявність фото, URL або дати імпорту не доводить актуальність квартири.",
            "Права на повторне використання фото та описів треба перевіряти окремо.",
            "Повторне використання фото з іншою CDN-адресою цей аудит може не знайти.",
            "Жодні записи не видаляються та не отримують мітки «перевірено» автоматично.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only rental catalog quality report")
    parser.add_argument("--catalog", default=str(ROOT / "data" / "deals.json"))
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    try:
        data = json.loads(Path(args.catalog).read_text(encoding="utf-8"))
        report = analyze_integrity(data)
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
        print(json.dumps({
            "total": report["total"],
            "candidate_pairs": report["candidate_pair_count"],
            "high_review_count": report["high_review_count"],
            "unknown_publication": report["missing_source_publication_timestamp"],
            "unknown_last_seen": report["missing_source_last_seen_timestamp"],
            "rights_needing_review": report["imported_without_evidence_of_republish_rights"],
        }, ensure_ascii=False))
        return 0
    except (OSError, UnicodeError, ValueError, TypeError) as error:
        print(json.dumps({"error": type(error).__name__}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
