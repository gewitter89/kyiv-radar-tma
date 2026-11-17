#!/usr/bin/env python3
"""Offline partner-feed preflight before any private database writes.

This is a structural safety check, NOT a license review, publication grant,
listing verification, staging import, or live-provider API interaction.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from .market_inventory import (
        MAX_RECORDS, checked_input, load_agreement, normalise, read_rows
    )
except ImportError:
    from market_inventory import (
        MAX_RECORDS, checked_input, load_agreement, normalise, read_rows
    )


def preflight(feed_path: Path, agreement_path: Path, *,
              feed_format: str = "auto", now: datetime | None = None) -> dict:
    """Validate file and allowed metadata without network or DB I/O.

    No source URL, address, price, contact, or raw feed item is printed or
    returned. Aggregate duplicates are candidates, never auto-merged.
    """
    if feed_format not in ("auto", "yrl"):
        raise ValueError("Unsupported feed format")
    now = now or datetime.now(timezone.utc)
    feed = checked_input(feed_path)
    agreement = load_agreement(agreement_path, now)
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    duplicate_url_candidates = 0
    count = 0
    for original in read_rows(feed, feed_format=feed_format):
        row = normalise(original, agreement)
        count += 1
        if count > MAX_RECORDS:
            raise ValueError("Too many feed records")
        external_id = row["external_id"]
        if external_id in seen_ids:
            raise ValueError("Duplicate source external ID")
        seen_ids.add(external_id)
        url = row["source_url"]
        if url in seen_urls:
            duplicate_url_candidates += 1
        seen_urls.add(url)
    if count == 0:
        raise ValueError("Empty feed cannot establish a valid pilot")
    return {
        "ok": True,
        "mode": "read_only_preflight",
        "records_checked": count,
        "duplicate_url_candidates": duplicate_url_candidates,
        "private_database_writes": 0,
        "publications": 0,
        "requires_contract_and_reviewer_checks": True,
        "requires_private_ingest_and_snapshot_gate": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline structural preflight of an authorized partner feed; no DB writes"
    )
    parser.add_argument("--feed", type=Path, required=True)
    parser.add_argument("--agreement", type=Path, required=True)
    parser.add_argument("--format", choices=("auto", "yrl"), default="auto")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(preflight(args.feed, args.agreement,
                                   feed_format=args.format), ensure_ascii=False))
        return 0
    except (ValueError, OSError, UnicodeError, csv.Error,
            json.JSONDecodeError, TypeError, KeyError) as error:
        # Errors must NOT contain raw private data or file paths.
        print(json.dumps({"ok": False, "mode": "read_only_preflight",
                          "error_type": type(error).__name__, "private_database_writes": 0,
                          "publications": 0}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
