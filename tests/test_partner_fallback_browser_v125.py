# -*- coding: utf-8 -*-
"""Real browser regression for partner-only static/offline fallback isolation."""
import json
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
URL = (ROOT / "index.html").as_uri()


@pytest.mark.asyncio
async def test_mobile_static_partner_filter_disallows_reintroduced_records():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844},
                                      is_mobile=True, has_touch=True)
        await page.route("**/api/deals*", lambda route: route.abort())
        await page.goto(URL, wait_until="domcontentloaded")
        await page.wait_for_function("typeof staticCatalogWithoutPartners === 'function'")
        rows = await page.evaluate("""() => staticCatalogWithoutPartners([
          {id:1,source:"partner:agency_one",partnerSourceKey:"agency_one",partnerExternalId:"P-1"},
          {id:2,source:"OLX",title:"Legacy example"},
          {id:3,source:"Київ Радар",title:"First-party example"},
          {id:4,source:"partner:agency_two"},
          {id:5,source:"Київ Радар",partnerExternalId:"P-5"}
        ]).map(x => x.id)""")
        assert rows == [2, 3]
        await browser.close()


@pytest.mark.asyncio
async def test_api_outage_does_not_resurrect_partner_from_static_json():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        fixture = [
            {"id": 9101, "source": "partner:agency_one",
             "partnerSourceKey": "agency_one", "partnerExternalId": "P-1",
             "title": "Must be hidden", "district": "Дарницький",
             "price": 18000, "rooms": 2},
            {"id": 9102, "source": "OLX", "title": "Legacy test only",
             "district": "Дарницький", "price": 15000, "rooms": 1}
        ]
        # Intercept JS fetch itself, including file:// URLs (browser network
        # routing may not intercept local file requests).
        script = (
            "(() => { const original = window.fetch.bind(window); "
            "const rows = " + json.dumps(fixture, ensure_ascii=False) + "; "
            "window.fetch = async (input, options) => { "
            " const url = String(input); "
            " if (url.includes('/api/deals')) throw new Error('API unavailable'); "
            " if (url.startsWith('data/deals.json')) "
            "   return { ok: true, json: async () => rows }; "
            " return original(input, options); "
            "}; })();"
        )
        await page.add_init_script(script=script)
        await page.goto(URL, wait_until="domcontentloaded")
        await page.wait_for_function("window.KR_CATALOG_MODE === 'static'", timeout=15000)
        ids = await page.evaluate("LISTINGS.map(x => x.id)")
        assert ids == [9102]
        await browser.close()
