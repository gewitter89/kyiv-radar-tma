#!/usr/bin/env python3
"""Read-only production smoke monitor. No personal data or secrets are logged.

Runs from GitHub Actions daily and can be invoked manually.
A failure produces a failed workflow run; it does not auto-modify production.
"""
import json
import urllib.request

API = "https://vmi3445944.contaboserver.net"
PAGES = "https://gewitter89.github.io/kyiv-radar-tma/"
TIMEOUT = 12
MAX_JSON_BYTES = 12 * 1024 * 1024


def fetch(url: str, limit: int = MAX_JSON_BYTES) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "KyivRadarReadOnlyHealth/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Unexpected HTTP {resp.status}")
        body = resp.read(limit + 1)
        if len(body) > limit:
            raise RuntimeError("Response exceeds maximum safe audit size")
        return body


def main():
    health = json.loads(fetch(API + "/api/health"))
    assert health.get("status") == "healthy", "API not healthy"
    assert str(health.get("version") or "").startswith(("1.5.", "1.6.")), "Unexpected API version"

    catalog = json.loads(fetch(API + "/api/deals"))
    assert catalog.get("success") is True and isinstance(catalog.get("deals"), list)
    deals = catalog["deals"]
    assert len(deals) > 0, "Catalog is unexpectedly empty"
    for item in deals:
        assert item.get("phone") is None, "Public catalog exposes an unmasked phone"
        assert "ownerName" not in item, "Public catalog exposes an owner name"
        assert "private_note" not in item, "Public catalog exposes private notes"
    page = fetch(PAGES, limit=6 * 1024 * 1024).decode("utf-8", errors="replace")
    assert "<title>Київ Радар</title>" in page, "GitHub Pages HTML title not found"
    print(f"PASS: public API healthy, {len(deals)} listings private, Pages accessible")
    # No user identifiers, secrets, payloads, or contact values are printed.


if __name__ == "__main__":
    main()
