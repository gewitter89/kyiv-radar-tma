#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hard gate for public, tracked distribution sources.

Use BEFORE CI-only fixture generation. It deliberately makes the checkout fail
if historical, unlicensed, synthetic or developer-only listings are packaged.
A passing gate is NOT proof that old Git commits or third-party caches vanished.
"""
from __future__ import annotations
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EMBEDDED = re.compile(r"const KYIV_DEALS_INIT\s*=\s*(\[[^\n]*\]);")
# This intentionally accepts only literal [] rather than a benign-looking
# constructed expression: fixture data must not be present in public HTML.
HISTORICAL_HINTS = (
    "ireland.apollo.olxcdn.com",
    '"verifiedAt":"Імпортовано з OLX',
    '"verifiedAt":"Імпортовано з DOM.RIA'
)

def verify(root: Path) -> None:
    html = (root / "index.html").read_text(encoding="utf-8")
    raw = (root / "data" / "deals.json").read_text(encoding="utf-8")
    match = EMBEDDED.findall(html)
    if len(match) != 1 or match[0] != "[]":
        raise AssertionError("BLOCK: public HTML must embed exactly zero inventory records")
    if json.loads(raw) != []:
        raise AssertionError("BLOCK: public data/deals.json must be []")
    if any(hint in html or hint in raw for hint in HISTORICAL_HINTS):
        raise AssertionError("BLOCK: original imported photo/data fingerprints in public payload")
    if "KYIV_DEALS_INIT" not in html:
        raise AssertionError("BLOCK: missing fail-closed client fixture contract")
    # Do not accept a checkout whose live API path silently revives
    # historical OLX/DIM.RIA imports as available inventory.
    if "source.startsWith(\"partner:\")" not in html or \
       "source === \"київ радар (пряма заявка)\"" not in html:
        raise AssertionError("BLOCK: live API source eligibility gate missing")
    print("PASS: repository HEAD distributes no catalog records in static HTML/JSON")


if __name__ == "__main__":
    verify(ROOT)
