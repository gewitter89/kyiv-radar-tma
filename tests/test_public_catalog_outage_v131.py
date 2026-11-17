# -*- coding: utf-8 -*-
"""Browser regression for safe hosted catalog errors and local-only fixtures.

Uses an ephemeral loopback HTTP server and fully synthetic, intercepted API
responses. No production contacts, external feed access or backend mutation.
"""
import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
API_PATTERN = "https://vmi3445944.contaboserver.net/api/deals*"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


@pytest.fixture
def hosted_catalog():
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(QuietHandler, directory=str(ROOT))
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/index.html"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,response",
    [(503, "unavailable"), (200, "not json"),
     (200, '{"success": true, "deals": null}'),
     (200, '{"success": false, "deals": []}')],
)
async def test_hosted_site_fails_closed_not_historical_listings(hosted_catalog, status, response):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844},
                                      is_mobile=True, has_touch=True)
        static_calls = []

        async def static_handler(route):
            static_calls.append(route.request.url)
            await route.fulfill(status=500, body="should never be requested")

        async def api_handler(route):
            await route.fulfill(status=status, content_type="application/json",
                                body=response)

        await page.route("**/data/deals.json*", static_handler)
        await page.route(API_PATTERN, api_handler)
        await page.goto(hosted_catalog, wait_until="domcontentloaded")
        await page.wait_for_function("window.KR_CATALOG_MODE === 'error'", timeout=15000)
        assert await page.evaluate("LISTINGS.length") == 0
        assert await page.locator("#listViewContainer > div[onclick]").count() == 0
        assert await page.get_by_text("Не вдалося завантажити оголошення").is_visible()
        assert await page.get_by_text("Архівні оголошення не показуємо", exact=False).is_visible()
        assert await page.locator("#krCatalogRetry").is_visible()
        assert not static_calls
        await browser.close()


@pytest.mark.asyncio
async def test_valid_empty_200_is_not_an_outage(hosted_catalog):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        async def api_handler(route):
            await route.fulfill(status=200, content_type="application/json",
                                body=json.dumps({"success": True, "deals": []}))
        await page.route(API_PATTERN, api_handler)
        await page.goto(hosted_catalog, wait_until="domcontentloaded")
        await page.wait_for_function("window.KR_CATALOG_MODE === 'live'", timeout=15000)
        assert await page.evaluate("LISTINGS.length") == 0
        assert await page.get_by_text("Зараз немає доступних оголошень").is_visible()
        assert await page.locator("#krCatalogRetry").count() == 0
        await browser.close()


@pytest.mark.asyncio
async def test_retry_can_recover_without_archival_revival(hosted_catalog):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        calls = [0]

        async def api_handler(route):
            calls[0] += 1
            if calls[0] == 1:
                await route.fulfill(status=502, body="unavailable")
            else:
                await route.fulfill(status=200, content_type="application/json",
                                    body='{"success": true, "deals": []}')

        await page.route(API_PATTERN, api_handler)
        await page.goto(hosted_catalog, wait_until="domcontentloaded")
        await page.wait_for_function("window.KR_CATALOG_MODE === 'error'", timeout=15000)
        await page.locator("#krCatalogRetry").click()
        await page.wait_for_function("window.KR_CATALOG_MODE === 'live'", timeout=15000)
        assert calls[0] == 2
        assert await page.get_by_text("Зараз немає доступних оголошень").is_visible()
        assert await page.locator("#krCatalogRetry").count() == 0
        await browser.close()


@pytest.mark.asyncio
async def test_file_scheme_retains_only_local_test_fixtures():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844})

        async def api_handler(route):
            await route.abort()

        await page.route(API_PATTERN, api_handler)
        await page.goto(ROOT.joinpath("index.html").as_uri(), wait_until="domcontentloaded")
        await page.wait_for_function(
            "LISTINGS.length > 10 && ['static','cached'].includes(window.KR_CATALOG_MODE)",
            timeout=15000
        )
        assert await page.locator("#listViewContainer > div[onclick]").count() > 10
        await browser.close()
