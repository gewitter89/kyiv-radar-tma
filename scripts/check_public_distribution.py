#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0 publication gate: zero unlicensed/invented catalog bytes in public assets.

Run on the exact checkout BEFORE creating temporary QA fixtures. This checks
CURRENT publishable source, not historical git commits or third-party caches.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EMBEDDED = re.compile(r"const KYIV_DEALS_INIT\s*=\s*(\[[^\n]*\]);")
FINGERPRINTS = (
    "ireland.apollo.olxcdn.com",
    '"verifiedAt":"Імпортовано з OLX',
    '"verifiedAt":"Імпортовано з DOM.RIA',
    "synthetic-test-only-IDQATEST",
    '"fixtureOnly":true',
)


def verify(root: Path) -> None:
    html = (root / "index.html").read_text(encoding="utf-8")
    raw = (root / "data" / "deals.json").read_text(encoding="utf-8")
    match = EMBEDDED.findall(html)
    if len(match) != 1 or match[0] != "[]":
        raise AssertionError("BLOCK: public HTML must embed exactly zero inventory records")
    if json.loads(raw) != []:
        raise AssertionError("BLOCK: public static catalog must contain exactly []")
    if any(fingerprint in html or fingerprint in raw for fingerprint in FINGERPRINTS):
        raise AssertionError("BLOCK: historical or synthetic listing fingerprint in public asset")
    if "function approvedHostedListing(item)" not in html or (
        "item.actualityConfirmed === true && item.reviewedByRadar === true" not in html
    ):
        raise AssertionError("BLOCK: hosted source/evidence eligibility gate missing")
    if "window.KR_CATALOG_MODE = \"unavailable\"" not in html:
        raise AssertionError("BLOCK: public API outage must fail closed")

    for path in root.glob("*.js"):
        text = path.read_text(encoding="utf-8")
        if any(fingerprint in text for fingerprint in FINGERPRINTS):
            raise AssertionError("BLOCK: archived or synthetic record leaked to JavaScript bundle")


if __name__ == "__main__":
    verify(ROOT)
    print("PASS: publishable HTML/JSON/JS exclude legacy and synthetic listing inventory")
