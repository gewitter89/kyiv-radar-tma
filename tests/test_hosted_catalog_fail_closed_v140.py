# -*- coding: utf-8 -*-
"""Host-mode regression: never resurrect unreviewed imports when API fails."""
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def hosted_url():
    class QuietHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(ROOT), **kwargs)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/index.html"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.asyncio
async def test_hosted_http_errors_never_load_archived_static_deals(hosted_url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        static_requests = []
        async def archived(route):
            static_requests.append(route.request.url)
            await route.fulfill(status=200, content_type="application/json",
                                body='[{"id":1,"source":"OLX","price":100}]')
        await page.route("**/data/deals.json*", archived)
        await page.route("https://vmi3445944.contaboserver.net/api/deals*",
                         lambda route: route.fulfill(status=503, body="unavailable",
                                                     headers={"Access-Control-Allow-Origin": "*"}))
        await page.goto(hosted_url, wait_until="domcontentloaded")
        await page.wait_for_function("window.KR_CATALOG_MODE === 'unavailable'", timeout=15000)
        assert await page.evaluate("LISTINGS.length") == 0
        assert not static_requests
        await page.evaluate("setViewMode('list')")
        assert await page.get_by_text("Каталог тимчасово недоступний").is_visible()
        assert await page.get_by_role("button", name="Спробувати ще раз").is_visible()
        assert await page.locator("#activeListingsCount").inner_text() == "Оголошення: —"
        await browser.close()


@pytest.mark.asyncio
async def test_hosted_api_filters_legacy_even_with_forged_verified_flags(hosted_url):
    legacy = {"id": 1, "title": "Historical", "source": "OLX", "price": 10000,
              "actualityConfirmed": True, "reviewedByRadar": True}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        async def source(route):
            await route.fulfill(status=200, content_type="application/json",
                                headers={"Access-Control-Allow-Origin": "*"},
                                body=json.dumps({"success": True, "deals": [legacy]}))
        await page.route("https://vmi3445944.contaboserver.net/api/deals*", source)
        await page.goto(hosted_url, wait_until="domcontentloaded")
        await page.wait_for_function("window.KR_CATALOG_MODE === 'live'", timeout=15000)
        assert await page.evaluate("LISTINGS.length") == 0
        await page.evaluate("setViewMode('list')")
        assert await page.get_by_text("Зараз немає доступних оголошень").is_visible()
        await browser.close()


@pytest.mark.asyncio
async def test_hosted_catalog_renders_server_evidence_backed_owner_listing(hosted_url):
    eligible = {"id": 999999, "title": "Тестове житло", "district": "Дарницький",
                "source": "Київ Радар (Пряма заявка)", "price": 12500, "area": 42, "rooms": 1,
                "actualityConfirmed": True, "reviewedByRadar": True}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        async def source(route):
            await route.fulfill(status=200, content_type="application/json",
                                headers={"Access-Control-Allow-Origin": "*"},
                                body=json.dumps({"success": True, "deals": [eligible]}))
        await page.route("https://vmi3445944.contaboserver.net/api/deals*", source)
        await page.goto(hosted_url, wait_until="domcontentloaded")
        await page.wait_for_function("window.KR_CATALOG_MODE === 'live'", timeout=15000)
        assert await page.evaluate("LISTINGS.length") == 1
        assert await page.evaluate("LISTINGS[0].id") == 999999
        await browser.close()


@pytest.mark.asyncio
async def test_hosted_client_rejects_old_server_unlicensed_and_private_rows(hosted_url):
    # All of these responses are synthetic and intercepted in the browser.
    # A third-party source cannot become "verified" by setting two booleans.
    base = {"title": "Тест", "price": 12500, "actualityConfirmed": True,
            "reviewedByRadar": True}
    owner = dict(base, id=9001, source="Київ Радар (Пряма заявка)")
    bad = [
        dict(base, id=9002, source="owner"),
        dict(base, id=9003, source="OLX"),
        dict(base, id=9004, source="unlicensed_market"),
        dict(owner, id=9005, phone="+380501112233"),
        dict(owner, id=9006, ownerName="Private"),
        dict(owner, id=9007, fixtureOnly=True),
        dict(owner, id=9008, images=["https://thirdparty.example/test.jpg"]),
        dict(base, id=9009, source="partner:agency", url="http://example.test/p/9", images=[]),
        dict(base, id=9010, source="partner:agency", url="https://example.test/p/10",
             images=["https://example.test/10.jpg"]),
        dict(base, id=9011, source="partner:agency", url="https://example.test/p/11",
             phoneMasked="+38050***", images=[]),
    ]
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        async def source(route):
            await route.fulfill(status=200, content_type="application/json",
                headers={"Access-Control-Allow-Origin": "*"},
                body=json.dumps({"success": True, "deals": bad + [owner]}))
        await page.route("https://vmi3445944.contaboserver.net/api/deals*", source)
        await page.goto(hosted_url, wait_until="domcontentloaded")
        await page.wait_for_function("window.KR_CATALOG_MODE === 'live'", timeout=15000)
        assert await page.evaluate("LISTINGS.length") == 1
        assert await page.evaluate("LISTINGS[0].id") == 9001
        await browser.close()
