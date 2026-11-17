# -*- coding: utf-8 -*-
"""v1.19: a source-first next step for imported, unverified rental listings.

No real owner or live API is simulated outside isolated browser fixtures.
"""
import json
import os
import re
import urllib.parse

import pytest
from playwright.async_api import async_playwright

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
URL = "file:///" + os.path.join(ROOT, "index.html").replace("\\", "/")
INIT = "user=%7B%22id%22%3A12345%7D&auth_date=1700000000&hash=mockhash"
TG_URL = URL + "#tgWebAppData=" + urllib.parse.quote(INIT)


async def ready(page, telegram=False):
    await page.goto(TG_URL if telegram else URL, wait_until="domcontentloaded")
    await page.wait_for_selector("#listViewContainer .kr-open-detail")
    await page.locator("#listViewContainer .kr-open-detail").first.click()
    await page.locator("#dealModal").wait_for(state="visible")


def test_all_150_imported_records_have_source_url_but_no_verified_contact():
    with open(os.path.join(ROOT, "data", "deals.json"), encoding="utf-8") as stream:
        records = json.load(stream)
    assert len(records) == 150
    assert all(str(d.get("source", "")).upper() in ("OLX", "DOM.RIA") for d in records)
    assert all(d.get("contactVerified") is not True and not d.get("phone") for d in records)
    assert all(re.match(r"^https://(?:www\.)?(?:olx\.ua|dom\.ria\.com)/", d.get("url", "")) for d in records)


@pytest.mark.asyncio
@pytest.mark.parametrize("width,height", [(320,640), (390,844)])
async def test_imported_card_has_prominent_real_original_link(width, height):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width":width,"height":height},is_mobile=True,has_touch=True)
        await ready(page)
        source = await page.evaluate("currentModalDeal.url")
        link = page.locator("#krOriginalAction")
        assert await link.is_visible()
        assert await link.get_attribute("href") == source
        assert await link.get_attribute("target") == "_blank"
        rel = await link.get_attribute("rel")
        assert {"noopener", "noreferrer", "nofollow"}.issubset(set(rel.split()))
        assert "Перевірити на " in await link.inner_text()
        assert await page.locator("#modalCallBtn").is_hidden()
        assert await page.locator("#modalChatBtn").is_hidden()
        assert await page.locator("#freeTrialPill").is_hidden()
        assert await page.locator("#modalMaskedPhone").inner_text() == "Контакт не підтверджено"
        assert await page.locator("#modalPhoneHeaderTitle").inner_text() == "Контакт у джерелі"
        bbox = await link.bounding_box()
        assert bbox and bbox["height"] >= 44
        assert 0 <= bbox["x"] and bbox["x"] + bbox["width"] <= width + 2
        await browser.close()


@pytest.mark.asyncio
async def test_imported_telegram_card_never_promises_server_contact():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width":390,"height":844})
        calls = []

        async def unexpected(route):
            calls.append(route.request.url)
            await route.abort()

        await page.route("**/api/send_contact", unexpected)
        await ready(page, telegram=True)
        assert await page.locator("#krOriginalAction").is_visible()
        assert await page.locator("#modalCallBtn").is_hidden()
        await page.evaluate("sendContactToBotChat()")
        assert not calls
        assert await page.locator("#krContactStatus").get_attribute("data-state") == "info"
        assert "джерела" in await page.locator("#krContactStatus").inner_text()
        await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_url", [
    "javascript:alert(1)",
    "https://olx.ua.attacker.example/fake",
    "https://fake-dom.ria.com/123",
    "https://example.com/123",
    "http://example.com/path",
    "http://www.olx.ua/d/uk/obyavlenie/test.html",
])
async def test_suspicious_original_url_fails_closed(bad_url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width":390,"height":844})
        await page.goto(URL, wait_until="domcontentloaded")
        await page.wait_for_selector("#listViewContainer .kr-open-detail")
        await page.evaluate("""url => {
            const item = getFilteredListings()[0];
            item.url = url;
            openDealModalById(item.id);
        }""", bad_url)
        assert await page.locator("#krOriginalAction").is_hidden()
        assert await page.locator("#krOriginalAction").get_attribute("href") is None
        assert await page.locator("#modalOriginalLink").is_hidden()
        assert await page.locator("#modalCallBtn").is_hidden()
        assert await page.locator("#krShareListing").is_visible()
        await browser.close()


@pytest.mark.asyncio
async def test_provider_label_must_match_link_domain():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width":390,"height":844})
        await page.goto(URL, wait_until="domcontentloaded")
        await page.wait_for_selector("#listViewContainer .kr-open-detail")
        await page.evaluate("""() => {
            const item = getFilteredListings()[0];
            item.source = "OLX";
            item.url = "https://dom.ria.com/uk/realty-123.html";
            openDealModalById(item.id);
        }""")
        assert await page.locator("#modalOriginalLink").is_visible()
        assert await page.locator("#krOriginalAction").is_hidden()
        assert await page.locator("#krOriginalAction").get_attribute("href") is None
        assert await page.locator("#modalCallBtn").is_hidden()
        await browser.close()


@pytest.mark.asyncio
async def test_isolated_verified_first_party_retains_contact_request():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width":390,"height":844})
        calls = []

        async def success(route):
            calls.append(route.request.post_data_json)
            await route.fulfill(status=200,content_type="application/json",
                                body=json.dumps({"success":True}))

        await page.route("**/api/send_contact", success)
        await page.goto(TG_URL, wait_until="domcontentloaded")
        await page.wait_for_selector("#listViewContainer .kr-open-detail")
        await page.evaluate("""() => {
            // Browser-only first-party fixture, never stored or counted as verified.
            const item = getFilteredListings()[0];
            item.source = "Київ Радар";
            item.contactVerified = true;
            openDealModalById(item.id);
        }""")
        assert await page.locator("#modalCallBtn").is_visible()
        assert await page.locator("#krOriginalAction").is_hidden()
        await page.locator("#modalCallBtn").click()
        await page.wait_for_function("""() =>
          document.querySelector('#krContactStatus').dataset.state === 'success'""")
        assert len(calls) == 1
        assert "Перевірте приватний чат" in await page.locator("#krContactStatus").inner_text()
        await browser.close()


@pytest.mark.asyncio
async def test_imported_with_verified_contact_does_not_lose_contact_path():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width":390,"height":844})
        await page.goto(TG_URL, wait_until="domcontentloaded")
        await page.wait_for_selector("#listViewContainer .kr-open-detail")
        await page.evaluate("""() => {
            const item = getFilteredListings()[0];
            item.contactVerified = true; // test fixture only
            openDealModalById(item.id);
        }""")
        assert await page.locator("#modalCallBtn").is_visible()
        assert await page.locator("#krOriginalAction").is_hidden()
        assert await page.locator("#modalOriginalLink").is_visible()
        await browser.close()
