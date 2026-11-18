#!/usr/bin/env python3
"""Read-only public health monitor; no production writes, secrets or contacts."""
import json
import re
import urllib.request
from html.parser import HTMLParser

API = "https://vmi3445944.contaboserver.net"
PAGES = "https://gewitter89.github.io/kyiv-radar-tma/"
TIMEOUT = 12
MAX_JSON_BYTES = 12 * 1024 * 1024


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
    req = urllib.request.Request(url, headers={"User-Agent": "KyivRadarPublicHealth/1.8"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Unexpected HTTP {resp.status}")
        body = resp.read(limit + 1)
        if len(body) > limit:
            raise RuntimeError("Response exceeds maximum expected audit size")
        return body


def verify_pages_html(page_html: str) -> None:
    parser = TitleParser()
    parser.feed(page_html)
    title = " ".join(parser.title.split())
    if not (title == "Київ Радар" or title.startswith("Київ Радар —")):
        raise AssertionError("The published page is missing the expected Kyiv Radar title")
    if "<html" not in page_html.lower():
        raise AssertionError("Published page is not recognizable HTML")


def verify_public_api(health: dict, catalog: dict) -> int:
    if not isinstance(health, dict) or health.get("status") != "healthy":
        raise AssertionError("Public API is not healthy")
    version = str(health.get("version") or "")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise AssertionError("Public API has an invalid version response")

    if not isinstance(catalog, dict) or catalog.get("success") is not True:
        raise AssertionError("Catalog API returned an unsuccessful response")
    listings = catalog.get("deals")
    if not isinstance(listings, list):
        raise AssertionError("Catalog API must contain a deals array, even when legitimately empty")
    ids = set()
    for row in listings:
        if not isinstance(row, dict) or type(row.get("id")) is not int:
            raise AssertionError("Public listing has invalid data")
        if row["id"] in ids:
            raise AssertionError("Public listing IDs are duplicated")
        ids.add(row["id"])
        if row.get("phone") is not None or "ownerName" in row:
            raise AssertionError("Public catalog exposes a landlord contact or owner identity")
        if any(key in row for key in ("reporter_info", "private_note", "evidence_ref",
                                     "reviewer", "initData")):
            raise AssertionError("Public catalog exposes private moderation data")
    return len(listings)


def main() -> int:
    health = json.loads(fetch(API + "/api/health"))
    catalog = json.loads(fetch(API + "/api/deals"))
    count = verify_public_api(health, catalog)
    page = fetch(PAGES, limit=6 * 1024 * 1024).decode("utf-8", errors="replace")
    verify_pages_html(page)
    print("PASS: public API, private fields, published HTML; listings =", count,
          "; api_version =", health["version"])
    if count == 0:
        print("WARNING: zero public listings. API may be functioning in safe empty mode; "
              "review feed rights, ingestion and moderation before claiming a healthy inventory.")
    # The health endpoint doesn't certify freshness, origin or contact delivery.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
