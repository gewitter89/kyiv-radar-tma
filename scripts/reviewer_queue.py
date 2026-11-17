#!/usr/bin/env python3
"""Create a private, non-publishing human review worklist from the rental catalog.

No scraping, external network calls, automatic verification, de-duplication,
fraud verdicts, contact exposure, or writes to the public catalog.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path

if __package__:
    from .catalog_integrity import analyze_integrity
else:
    from catalog_integrity import analyze_integrity

ROOT = Path(__file__).resolve().parents[1]
SOURCE_NAMES = {"OLX", "DOM.RIA"}
CHECKS = (
    "source_still_active",
    "source_publication_date",
    "text_republication_rights",
    "photo_republication_rights",
    "owner_publication_consent",
    "ownership_identity",
    "availability",
    "contact_reachability",
    "commission",
    "address_and_location",
    "room_count",
    "generator",
    "gpon",
)


def build_review_queue(catalog: object) -> dict:
    """Build a minimal, privacy-safe worklist. No status represents verification."""
    if not isinstance(catalog, list):
        raise ValueError("Catalog must be a list")
    ids = [record.get("id") for record in catalog if isinstance(record, dict)]
    if len(ids) != len(catalog) or any(type(i) is not int or i <= 0 for i in ids):
        raise ValueError("Every catalog row needs a positive integer ID")
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate listing IDs must be resolved before triage")

    audit = analyze_integrity(catalog)
    paired: dict[int, set[int]] = defaultdict(set)
    priority: dict[int, str] = {}

    for candidate in audit["candidate_pairs"]:
        first, second = candidate["ids"]
        paired[first].add(second)
        paired[second].add(first)
        if candidate["priority"] == "high_review":
            priority[first] = priority[second] = "high_review"
        else:
            priority.setdefault(first, "review")
            priority.setdefault(second, "review")

    queue = []
    for record in catalog:
        listing_id = record["id"]
        source = str(record.get("source", "")).strip().upper()
        queue.append({
            "listing_id": listing_id,
            "source": source if source in SOURCE_NAMES else "OTHER",
            "priority": priority.get(listing_id, "routine"),
            "possible_duplicate_ids": sorted(paired[listing_id]),
            "checks": {check: "not_reviewed" for check in CHECKS},
            "moderation_decision": "pending_manual_review",
            # No reviewer identity, personal details, proof, source/media URL,
            # title, address, free-text description or raw phone are exported.
        })

    weight = {"high_review": 0, "review": 1, "routine": 2}
    queue.sort(key=lambda item: (weight[item["priority"]], item["listing_id"]))
    return {
        "schema_version": 1,
        "purpose": "PRIVATE_OFFLINE_MANUAL_REVIEW_ONLY",
        "not_a_approval_or_publication_record": True,
        "total_listings": len(queue),
        "candidate_pair_count": audit["candidate_pair_count"],
        "high_review_listing_count": sum(item["priority"] == "high_review" for item in queue),
        "entries": queue,
    }


def write_private_queue(queue: dict, output: Path) -> None:
    """Fail closed: refuse public-repo targets and existing files; mode 0600."""
    destination = output.expanduser().resolve()
    if destination.is_relative_to(ROOT):
        raise ValueError("Review files must be outside the public repository")
    if not destination.parent.is_dir():
        raise ValueError("Output parent directory must already exist")
    encoded = (json.dumps(queue, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    fd = os.open(str(destination), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(encoded)


def main() -> int:
    parser = argparse.ArgumentParser(description="Private Kyiv Radar reviewer worklist")
    parser.add_argument("--catalog", type=Path, default=ROOT / "data" / "deals.json")
    parser.add_argument("--output", type=Path, required=True,
                        help="New path outside the public Git repository (no overwrite)")
    args = parser.parse_args()
    try:
        records = json.loads(args.catalog.read_text(encoding="utf-8"))
        queue = build_review_queue(records)
        write_private_queue(queue, args.output)
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__}))
        return 2
    print(json.dumps({
        "ok": True,
        "total": queue["total_listings"],
        "candidate_pair_count": queue["candidate_pair_count"],
        "high_review_listings": queue["high_review_listing_count"],
        "verification_granted": False,
        "public_catalog_changed": False,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
