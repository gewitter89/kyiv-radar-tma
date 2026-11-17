# -*- coding: utf-8 -*-
"""v1.18: users see only evidenced features and correct contact outcomes."""
import json
import os
import urllib.parse

import pytest
from playwright.async_api import async_playwright

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
URL = "file:///" + os.path.join(ROOT, "index.html").replace("\\", "/")
INIT = "user=%7B%22id%22%3A12345%7D&auth_date=1700000000&hash=mockhash"
TG_URL = URL + "#tgWebAppData=" + urllib.parse.quote(INIT)


async def open_app(page, telegram=False):
    await page.goto(TG_URL if telegram else URL, wait_until="domcontentloaded")
    await page.wait_for_selector("#listViewContainer .kr-open-detail")


@pytest.mark.asyncio
async def test_gpon_without_generator_is_never_advertised_as_generator():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        await open_app(page)
        listing_id = await page.evaluate("""() => {
            const item = getFilteredListings()[0];
            item.gpon = true;
            item.generator = false;
            renderAll();
            return item.id;
        }""")
        card = page.locator(f"#card-{listing_id}")
        await card.wait_for()
        card_text = await card.inner_text()
        assert "Інтернет · заявлено" in card_text
        assert "Генератор" not in card_text
        await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("ownership,availability,expected", [
    (True, False, "Власника підтверджено · наявність не перевірено"),
    (False, True, "Наявність підтверджено · власника не перевірено"),
    (False, False, "Власника та наявність не перевірено"),
])
async def test_ownership_status_never_implies_availability(ownership, availability, expected):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        await open_app(page)
        listing_id = await page.evaluate("""flags => {
            const item = getFilteredListings()[0];
            item.isOwnerVerified = flags.ownership;
            item.actualityConfirmed = flags.availability;
            renderAll();
            return item.id;
        }""", {"ownership": ownership, "availability": availability})
        assert expected in await page.locator(f"#card-{listing_id}").inner_text()
        await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,message,title", [
    (404, "Контакт цього оголошення поки недоступний", "Контакт поки недоступний"),
    (429, "Ліміт запитів вичерпано", "Ліміт запитів вичерпано"),
    (401, "Сесія Telegram недійсна", "Відкрийте застосунок у Telegram"),
    (502, "Не вдалося доставити повідомлення", "Спробуйте ще раз через Telegram"),
])
async def test_server_contact_failure_has_specific_truthful_recovery(status, message, title):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        calls = []

        async def send_contact(route):
            calls.append(route.request.post_data_json)
            await route.fulfill(status=status, content_type="application/json",
                                body=json.dumps({"detail": "Контакт цього оголошення наразі недоступний"
                                                     if status == 404 else "Запустіть бота /start"}))

        await page.route("**/api/send_contact", send_contact)
        await open_app(page, telegram=True)
        await page.locator("#listViewContainer .kr-open-detail").first.click()
        await page.locator("#modalCallBtn").click()
        await page.wait_for_function(
            "() => document.querySelector('#krContactStatus').dataset.state === 'error'"
        )
        assert message in await page.locator("#krContactStatus").inner_text()
        dialog = page.get_by_role("dialog", name=title)
        assert await dialog.is_visible()
        text = (await dialog.inner_text()).lower()
        assert "контакт не надіслано" in text
        assert "скопійовано" not in text
        if status in (404, 429):
            assert await dialog.locator('a[href^="https://t.me/"]').count() == 0
        assert await page.locator("#modalCallBtn").is_enabled()
        assert len(calls) == 1
        await browser.close()



@pytest.mark.asyncio
async def test_distance_sort_uses_only_verified_coordinates():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        await page.route("**/api/deals*", lambda route: route.abort())
        await open_app(page)
        result = await page.evaluate("""() => {
            const first = LISTINGS[0], second = LISTINGS[1];
            first.locationVerified = false;
            first.lat = 50.4501;
            first.lng = 30.5234; // unverified coordinates, even if "very close"
            first.price = 1;
            second.locationVerified = true;
            second.lat = 50.455;
            second.lng = 30.529;
            userCoords = [50.4501, 30.5234];
            applySort('distance');
            const sorted = getFilteredListings();
            return {
                sort: currentSort,
                unknownHasDistance: Number.isFinite(first._dist),
                confirmedHasDistance: Number.isFinite(second._dist),
                firstId: sorted[0].id,
                confirmedId: second.id,
            };
        }""")
        assert result["sort"] == "distance"
        assert result["unknownHasDistance"] is False
        assert result["confirmedHasDistance"] is True
        assert result["firstId"] == result["confirmedId"]
        await browser.close()


@pytest.mark.asyncio
async def test_distance_sort_without_evidence_refuses_false_precision():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        await page.route("**/api/deals*", lambda route: route.abort())
        await open_app(page)
        result = await page.evaluate("""() => {
            LISTINGS.forEach(x => x.locationVerified = false);
            userCoords = [50.4501, 30.5234];
            applySort('distance');
            return {sort:currentSort, anyDistances:LISTINGS.some(x => Number.isFinite(x._dist))};
        }""")
        assert result["sort"] == "price_asc"
        assert result["anyDistances"] is False
        await browser.close()

def test_text_never_pretends_imported_listings_were_posted_by_owner():
    html = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
    assert "Оголошення подано власником через Київ Радар" not in html
    assert "Прямий номер" not in html
    assert "Прямий контакт з орендодавцем" not in html
    assert "Ціна та актуальність об'єкта підтверджені" not in html
    assert "запускається найближчим часом" not in html
    assert "⚡ Генератор · заявлено" in html
