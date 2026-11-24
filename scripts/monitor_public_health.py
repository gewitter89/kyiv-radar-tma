#!/usr/bin/env python3
"""Read-only production monitor. Truthful empty catalog is NOT a failure.

No production writes, accounts, paid-provider calls or private credentials.
The served HTML/JSON and public API must ALL pass; a green API HTTP status
is not by itself evidence of source rights or up-to-date inventory.
"""
from __future__ import annotations

import json
import re
import urllib.request
from html.parser import HTMLParser

API = "https://vmi3445944.contaboserver.net"
PAGES = "https://gewitter89.github.io/kyiv-radar-tma/"
TIMEOUT = 12
MAX_JSON_BYTES = 12 * 1024 * 1024
INLINE = re.compile(r"const KYIV_DEALS_INIT\s*=\s*(\[[^\n]*\]);")
VERSION = re.compile(r"\d+\.\d+\.\d+")
PRIVATE_KEYS = {
    "ownerName", "phoneRaw", "reporter_info", "private_note", "evidence_ref",
    "reviewer", "initData", "adminNotes", "ownerTg",
}


class TitleParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inside_title = False
        self.title = ""

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "title":
            self.inside_title = True

    def handle_endtag(self, tag):
        if tag.lower() == "title":
            self.inside_title = False

    def handle_data(self, data):
        if self.inside_title:
            self.title += data


def fetch(url: str, limit: int = MAX_JSON_BYTES) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "KyivRadarPublicHealth/1.41"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        if resp.status != 200:
            raise RuntimeError("Public resource HTTP status is not 200")
        body = resp.read(limit + 1)
        if len(body) > limit:
            raise RuntimeError("Public audit response exceeds safe bound")
        return body


def verify_pages_html(page_html: str) -> None:
    parser = TitleParser()
    parser.feed(page_html)
    title = " ".join(parser.title.split())
    if not (title == "Київ Радар" or title.startswith("Київ Радар —")):
        raise AssertionError("Expected published page title missing")
    if "<html" not in page_html.lower():
        raise AssertionError("Published response is not recognizable HTML")
    embedded = INLINE.findall(page_html)
    if len(embedded) != 1 or embedded[0] != "[]":
        raise AssertionError("Public page embeds outdated or unapproved listings")
    if "ireland.apollo.olxcdn.com" in page_html:
        raise AssertionError("Historical third-party image fingerprints remain in HTML")
    if "function approvedHostedListing(item)" not in page_html:
        raise AssertionError("Frontend source-trust gate missing")


def verify_public_static_catalog(rows: object) -> None:
    if rows != []:
        raise AssertionError("Public static listing feed still contains unreviewed inventory")


def verify_public_api(health: object, catalog: object) -> int:
    if not isinstance(health, dict) or health.get("status") != "healthy":
        raise AssertionError("Public API is not healthy")
    if VERSION.fullmatch(str(health.get("version") or "")) is None:
        raise AssertionError("Public API version malformed")
    if not isinstance(catalog, dict) or catalog.get("success") is not True:
        raise AssertionError("Public API catalog is unsuccessful")
    deals = catalog.get("deals")
    if not isinstance(deals, list):
        raise AssertionError("Public catalog must be an array, including when empty")

    ids = set()
    for item in deals:
        if not isinstance(item, dict) or type(item.get("id")) is not int:
            raise AssertionError("Public listing identity malformed")
        if item["id"] <= 0 or item["id"] in ids:
            raise AssertionError("Public listing has duplicate/invalid ID")
        ids.add(item["id"])
        source = str(item.get("source") or "").strip().casefold()
        first_party = source == "київ радар (пряма заявка)"
        authorized_partner = source.startswith("partner:") and bool(source[8:])
        if not (first_party or authorized_partner):
            raise AssertionError("Unlicensed/archived source exposed by public API")
        if item.get("fixtureOnly") is True:
            raise AssertionError("Synthetic test row leaked through public API")
        if item.get("phone") is not None or any(key in item for key in PRIVATE_KEYS):
            raise AssertionError("Sensitive contact/review fields exposed in public API")
        if authorized_partner and not str(item.get("url") or "").startswith("https://"):
            raise AssertionError("Partner listing missing HTTPS original permalink")

    if type(health.get("deals_count")) is not int or health["deals_count"] != len(deals):
        raise AssertionError("Public API health and catalog disagree")
    return len(deals)


def main() -> int:
    try:
        page_html = fetch(PAGES, limit=6 * 1024 * 1024).decode("utf-8", errors="strict")
        verify_pages_html(page_html)
        static = json.loads(fetch(PAGES + "data/deals.json"))
        verify_public_static_catalog(static)
        health = json.loads(fetch(API + "/api/health"))
        catalog = json.loads(fetch(API + "/api/deals"))
        count = verify_public_api(health, catalog)
    except (AssertionError, OSError, RuntimeError, ValueError, UnicodeError, TypeError) as exc:
        # Do not leak URLs, contact values, response bodies, credentials in CI.
        print("FAIL: release verification incomplete; issue_type =", type(exc).__name__)
        return 2
    print("PASS: actual public HTML/JSON and API source/privacy checks; eligible_count =", count)
    if count == 0:
        print("NOTE: empty verified catalog is a valid state, not an outage")
    print("LIMIT: this monitor cannot independently verify partner contracts or landlords")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
