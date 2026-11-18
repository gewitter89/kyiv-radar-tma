#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""READ-ONLY post-release smoke test for *actually deployed* Kyiv Radar.

Run by the owner/operator after coordinated frontend + backend rollout. This
file makes no production writes and reads no contacts/secrets. It cannot verify
provenance of future partner rights, but blocks obvious archived/PII leaks.
"""
from __future__ import annotations

import json
import re
import urllib.request
from urllib.parse import urljoin

API = "https://vmi3445944.contaboserver.net"
PAGES = "https://gewitter89.github.io/kyiv-radar-tma/"
MAX_BYTES = 6 * 1024 * 1024
TIMEOUT = 12
PRIVATE_FIELDS = {"ownerName", "private_note", "reporter_info", "initData",
                  "evidence_ref", "reviewer", "phoneRaw"}
EMBEDDED = re.compile(r"\bconst\s+KYIV_DEALS_INIT\s*=\s*(\[[^\n]*\]);")
VERSION = re.compile(r"^\d+\.\d+\.\d+$")


def check_pages(html: str, static_data: object) -> None:
    if "<html" not in html.casefold() or "<title>Київ Радар" not in html:
        raise AssertionError("Published HTML is not the expected Kyiv Radar document")
    snapshots = EMBEDDED.findall(html)
    if len(snapshots) != 1 or snapshots[0] != "[]":
        raise AssertionError("Published HTML still contains a non-empty or missing inline catalog")
    if static_data != []:
        raise AssertionError("Published static JSON catalog contains non-empty or invalid data")
    if "ireland.apollo.olxcdn.com" in html:
        raise AssertionError("Historical image source found in current published HTML")


def check_api(health: object, catalog: object) -> int:
    if not isinstance(health, dict) or health.get("status") != "healthy":
        raise AssertionError("Public API health is not healthy")
    if VERSION.fullmatch(str(health.get("version") or "")) is None:
        raise AssertionError("Missing/invalid API version")
    if not isinstance(catalog, dict) or catalog.get("success") is not True:
        raise AssertionError("Catalog returned unsuccessful JSON")
    records = catalog.get("deals")
    if not isinstance(records, list):
        raise AssertionError("Catalog deals must be an array, including an empty array")
    ids = set()
    for item in records:
        if not isinstance(item, dict) or type(item.get("id")) is not int:
            raise AssertionError("Invalid public listing identity")
        id_ = item["id"]
        if id_ in ids:
            raise AssertionError("Duplicate public listing id")
        ids.add(id_)
        source = str(item.get("source") or "").strip().casefold()
        first_party = source == "київ радар (пряма заявка)"
        partner = source.startswith("partner:") and bool(source.removeprefix("partner:"))
        if not (first_party or partner):
            raise AssertionError("Unapproved/legacy source found in public API")
        if item.get("fixtureOnly") or any(key in item for key in PRIVATE_FIELDS):
            raise AssertionError("Test or private fields exposed by public API")
        if item.get("phone") is not None:
            raise AssertionError("Raw phone exposed by public API")
    reported = health.get("deals_count")
    if type(reported) is int and reported != len(records):
        raise AssertionError("API health/catalog counts do not agree")
    return len(records)


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "KyivRadarReleaseVerifier/1.32"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        if response.status != 200:
            raise AssertionError("Public resource returned non-200 status")
        content = response.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise AssertionError("Public resource exceeded safe response limit")
        return content.decode("utf-8", errors="strict")


def main() -> int:
    try:
        # All four requests are GET only; none submit personal data or contacts.
        html = fetch_text(PAGES)
        static_data = json.loads(fetch_text(urljoin(PAGES, "data/deals.json")))
        health = json.loads(fetch_text(API + "/api/health"))
        catalog = json.loads(fetch_text(API + "/api/deals"))
        check_pages(html, static_data)
        count = check_api(health, catalog)
    except (AssertionError, OSError, UnicodeError, ValueError, KeyError) as exc:
        print("FAIL: public deployment is NOT release-verified; problem =", type(exc).__name__)
        # Do not reflect server data, private urls or unexpected response bodies.
        return 2
    print("PASS: published HTML/JSON clean; API source/privacy gate visible; eligible offers =", count)
    if count == 0:
        print("NOTICE: safe zero-offer state; no approved inventory was verified by this check")
    print("LIMIT: this does not prove source licenses, owner identity, current availability or Telegram delivery")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
