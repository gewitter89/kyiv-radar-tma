# -*- coding: utf-8 -*-
"""v1.20: no guessed metro station or exact foot travel time in unverified imports."""
import json
import os

import pytest
from playwright.async_api import async_playwright

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
URL = "file:///" + os.path.join(ROOT, "index.html").replace("\\", "/")


def test_source_catalog_has_no_unsourced_stations_or_minutes():
    with open(os.path.join(ROOT, "data", "deals.json"), encoding="utf-8") as stream:
        data = json.load(stream)
    assert len(data) == 150
    assert all(str(x.get("source", "")).upper() in ("OLX", "DOM.RIA") for x in data)
    assert all(x.get("locationVerified") is not True for x in data)
    assert all(x.get("metro") is None and x.get("walkMin") is None for x in data)


@pytest.mark.asyncio
async def test_embedded_fallback_renders_district_without_station_or_travel_minutes():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width":390,"height":844},is_mobile=True,has_touch=True)
        await page.route("**/api/deals*", lambda route: route.abort())
        await page.goto(URL,wait_until="domcontentloaded")
        await page.wait_for_selector("#listViewContainer .kr-open-detail")
        stats = await page.evaluate("""() => ({
            n: LISTINGS.length,
            anyStation: LISTINGS.some(x => String(x.source||'').toUpperCase() === 'OLX'
                   && Boolean(x.metro)),
            anyMinutes: LISTINGS.some(x => x.walkMin !== null && x.walkMin !== undefined),
            id: LISTINGS[0].id,
            district: LISTINGS[0].district
        })""")
        assert stats["n"] == 150
        assert stats["anyStation"] is False
        assert stats["anyMinutes"] is False
        await page.evaluate("id => openDealModalById(id)",stats["id"])
        assert await page.locator("#modalMetro").inner_text() == stats["district"]
        await browser.close()


@pytest.mark.asyncio
async def test_api_sanitizer_drops_unverified_metro_but_preserves_verified_and_first_party_data():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(URL,wait_until="domcontentloaded")
        await page.wait_for_function("typeof krQualityCatalog === 'function'")
        values = await page.evaluate("""() => {
            const imported = {
                id:1001,source:'OLX',locationVerified:false,title:'Пропозиція',
                metro:'Метро Позняки',walkMin:4
            };
            const verified = {...imported,id:1002,locationVerified:true};
            const own = {...imported,id:1003,source:'Київ Радар'};
            const [a,b,c] = krQualityCatalog([imported,verified,own]);
            return {unknown:[a.metro,a.walkMin],verified:[b.metro,b.walkMin],own:[c.metro,c.walkMin]};
        }""")
        assert values["unknown"] == [None,None]
        assert values["verified"] == ["Метро Позняки",4]
        assert values["own"] == ["Метро Позняки",4]
        await browser.close()


def test_unsourced_metro_fields_do_not_reappear_in_public_fallback():
    html = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
    # Imported image URLs contain semicolons inside quoted JSON values.
    # Read the whole assignment line, not the first semicolon in a URL.
    start = html.index("const KYIV_DEALS_INIT = ")
    assignment = html[start:].splitlines()[0]
    catalog = json.loads(assignment.split(" = ", 1)[1].removesuffix(";"))
    assert len(catalog) == 150
    assert all(item.get("metro") is None and item.get("walkMin") is None for item in catalog)
