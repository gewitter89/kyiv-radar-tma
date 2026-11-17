# -*- coding: utf-8 -*-
"""Browser regression for safe hosted catalog errors and local-only fixtures.

Uses an ephemeral loopback HTTP server and fully synthetic, intercepted API
responses. No production contacts, external feed access or backend mutation.
"""
import asyncio
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


@pytest.mark.asyncio
async def test_legacy_imports_are_not_reanimated_by_successful_old_api(hosted_catalog):
    """HTTP 200 alone is not legal provenance or current availability."""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        rows = [
            {"id": 7001, "title": "OLD UNLICENSED OLX ROW", "source": "OLX",
             "price": 11000, "rooms": 1, "images": [],
             "district": "Тестовий", "address": "Тест"},
            {"id": 7002, "title": "OLD UNLICENSED DIM ROW", "source": "DOM.RIA",
             "price": 11000, "rooms": 1, "images": [],
             "district": "Тестовий", "address": "Тест"},
            {"id": 7003, "title": "SYNTHETIC FIXTURE ONLY", "source": "Київ Радар",
             "fixtureOnly": True, "price": 11000, "rooms": 1,
             "district": "Тестовий", "address": "Тест", "images": []},
            {"id": 7005, "title": "UNAPPROVED FIRST-PARTY LABEL", "source": "Київ Радар",
             "price": 11000, "rooms": 1, "images": [],
             "district": "Тестовий", "address": "Тест"},
            {"id": 7004, "title": "FIRST-PARTY TEST APPROVED", "source": "Київ Радар (Пряма заявка)",
             "price": 11000, "rooms": 1, "images": [],
             "district": "Тестовий", "address": "Тест", "moderationStatus": "approved"}
        ]
        async def api_handler(route):
            await route.fulfill(status=200, content_type="application/json",
                                body=json.dumps({"success": True, "deals": rows}))
        await page.route(API_PATTERN, api_handler)
        await page.goto(hosted_catalog, wait_until="domcontentloaded")
        await page.wait_for_function(
            "window.KR_CATALOG_MODE === 'live' && LISTINGS.length === 1",
            timeout=15000)
        assert await page.evaluate("LISTINGS.map(item => item.id)") == [7004]
        assert await page.locator("#listViewContainer > div[onclick]").count() == 1
        assert await page.get_by_text("OLD UNLICENSED OLX ROW").count() == 0
        assert await page.get_by_text("SYNTHETIC FIXTURE ONLY").count() == 0
        await browser.close()


@pytest.mark.asyncio
async def test_old_api_with_only_unlicensed_rows_is_legitimately_empty(hosted_catalog):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        async def api_handler(route):
            await route.fulfill(status=200, content_type="application/json",
                                body='{"success":true,"deals":[{"id":42,"source":"OLX","title":"OLD","price":20000}]}')
        await page.route(API_PATTERN, api_handler)
        await page.goto(hosted_catalog, wait_until="domcontentloaded")
        await page.wait_for_function("window.KR_CATALOG_MODE === 'live'", timeout=15000)
        assert await page.evaluate("LISTINGS.length") == 0
        assert await page.get_by_text("Зараз немає доступних оголошень").is_visible()
        await browser.close()


@pytest.mark.asyncio
async def test_live_refresh_hides_previous_cards_before_api_finishes(hosted_catalog):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        count = [0]
        first = {"id": 7001, "source": "Київ Радар (Пряма заявка)",
                 "title": "EPHEMERAL FIRST PARTY FIXTURE", "rooms": 1,
                 "price": 12500, "images": [], "district": "Тест", "address": "Тест"}

        async def api_handler(route):
            count[0] += 1
            if count[0] == 1:
                await route.fulfill(status=200, content_type="application/json",
                                    body=json.dumps({"success": True, "deals": [first]}))
            else:
                await asyncio.sleep(1)
                await route.fulfill(status=200, content_type="application/json",
                                    body='{"success":true,"deals":[]}')

        await page.route(API_PATTERN, api_handler)
        await page.goto(hosted_catalog, wait_until="domcontentloaded")
        await page.wait_for_function("LISTINGS.length === 1 && window.KR_CATALOG_MODE === 'live'")
        assert await page.locator("#listViewContainer > div[onclick]").count() == 1

        task = asyncio.create_task(page.evaluate("loadDeals()"))
        await page.wait_for_function("window.KR_CATALOG_MODE === 'loading'")
        assert await page.evaluate("LISTINGS.length") == 0
        assert await page.locator("#listViewContainer > div[onclick]").count() == 0
        assert await page.get_by_text("Завантажуємо оголошення…").is_visible()
        await task
        assert await page.evaluate("window.KR_CATALOG_MODE") == "live"
        assert await page.get_by_text("Зараз немає доступних оголошень").is_visible()
        await browser.close()


@pytest.mark.asyncio
async def test_http_200_with_legacy_imports_does_not_resurrect_them(hosted_catalog):
    """A successful but stale API must not bypass the frontend rights gate."""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        async def api_handler(route):
            await route.fulfill(status=200, content_type="application/json",
                body=json.dumps({"success": True, "deals": [
                    {"id": 5, "source": "OLX", "title": "Historical-only synthetic offer", "price": 12345},
                    {"id": 6, "source": "DOM.RIA", "title": "Historical-only synthetic offer", "price": 13456}
                ]}))
        await page.route(API_PATTERN, api_handler)
        await page.goto(hosted_catalog, wait_until="domcontentloaded")
        await page.wait_for_function("window.KR_CATALOG_MODE === 'live'", timeout=15000)
        assert await page.evaluate("LISTINGS.length") == 0
        assert await page.get_by_text("Зараз немає доступних оголошень").is_visible()
        await browser.close()


@pytest.mark.asyncio
async def test_http_200_moderated_first_party_keeps_real_catalog_path(hosted_catalog):
    """One mock approved direct submission remains visible; no stale fallback."""
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        async def api_handler(route):
            await route.fulfill(status=200, content_type="application/json",
                body=json.dumps({"success": True, "deals": [
                    {"id": 7, "source": "Київ Радар (Пряма заявка)",
                     "submission_id": 707, "moderationStatus": "approved",
                     "title": "Synthetic allowed item", "price": 10000,
                     "district": "Тестовий район", "images": [], "rooms": 1}
                ]}))
        await page.route(API_PATTERN, api_handler)
        await page.goto(hosted_catalog, wait_until="domcontentloaded")
        await page.wait_for_function("window.KR_CATALOG_MODE === 'live' && LISTINGS.length === 1",
                                     timeout=15000)
        assert await page.evaluate("LISTINGS[0].id") == 7
        assert await page.locator("#listViewContainer > div[onclick]").count() == 1
        await browser.close()
