# -*- coding: utf-8 -*-
"""Real mobile/desktop browser tests for local smart radar features."""
import os
import pytest
from playwright.async_api import async_playwright

INDEX = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "index.html"))
URL = "file:///" + INDEX.replace("\\", "/")


@pytest.mark.asyncio
async def test_saved_search_persists_and_restores_exact_filters():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        page = await context.new_page()
        await page.goto(URL, wait_until="domcontentloaded")
        await page.wait_for_selector("#smartRadarOpen")
        await page.evaluate("""() => {
            handleSearch('Позняки');
            setFilter('under20k');
        }""")
        await page.locator("#smartRadarOpen").click()
        assert await page.is_visible("#smartRadarPanel")
        await page.fill("#smartRadarName", "Квартира біля метро")
        await page.get_by_role("button", name="Зберегти поточні фільтри").click()
        assert await page.locator("#smartRadarSearches > div").count() == 1
        assert "Квартира біля метро" in await page.inner_text("#smartRadarSearches")
        await page.reload(wait_until="domcontentloaded")
        await page.wait_for_selector("#smartRadarOpen")
        await page.locator("#smartRadarOpen").click()
        assert await page.locator("#smartRadarSearches > div").count() == 1
        await page.get_by_role("button", name="Показати").click()
        assert await page.evaluate("searchQuery") == "Позняки"
        assert await page.evaluate("ACTIVE_FILTERS.maxPrice") == 20000
        assert await page.input_value("#searchInput") == "Позняки"
        assert not await page.is_visible("#smartRadarPanel")
        await context.close()
        await browser.close()


@pytest.mark.asyncio
async def test_new_matches_count_is_truthful_and_resettable():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(URL, wait_until="domcontentloaded")
        await page.wait_for_selector("#smartRadarOpen")
        await page.locator("#smartRadarOpen").click()
        await page.get_by_role("button", name="Зберегти поточні фільтри").click()
        assert "0 нових" in await page.inner_text("#smartRadarSearches")
        await page.evaluate("""() => LISTINGS.push({
            id: 99887711, title: 'Нова тестова квартира', district: 'Дарницький',
            address: 'Київ', metro: 'Позняки', price: 10000, rooms: 1,
            images: [], generator: false, gpon: false, pets: false,
            isOwnerVerified: false, source: 'Тест', phone: null
        })""")
        await page.keyboard.press("Escape")
        await page.locator("#smartRadarOpen").click()
        assert "1 нових" in await page.inner_text("#smartRadarSearches")
        await page.get_by_role("button", name="Переглянуто").click()
        assert "0 нових" in await page.inner_text("#smartRadarSearches")
        await browser.close()


@pytest.mark.asyncio
async def test_comparison_does_not_claim_unverified_features_or_expose_contacts():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 800})
        await page.goto(URL, wait_until="domcontentloaded")
        await page.wait_for_selector("#smartRadarOpen")
        await page.evaluate("""() => {
            LISTINGS[0].phone = '+380671234567';
            LISTINGS[0].isOwnerVerified = false;
            LISTINGS[0].generator = false;
            LISTINGS[0].gpon = false;
        }""")
        await page.locator("#smartRadarOpen").click()
        await page.locator("#smartRadarCompareSelect").select_option("1")
        await page.get_by_role("button", name="Додати", exact=True).click()
        content = await page.inner_text("#smartRadarComparison")
        assert "Генератор у будинку: не вказано" in content
        assert "Інтернет під час відключень: не вказано" in content
        assert "Власника не перевірено" in content
        assert "+380671234567" not in content
        assert await page.locator("#smartRadarComparison > div").count() == 1
        await page.keyboard.press("Escape")
        assert not await page.is_visible("#smartRadarPanel")
        await browser.close()


@pytest.mark.asyncio
async def test_corrupted_storage_does_not_break_panel():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(URL, wait_until="domcontentloaded")
        await page.evaluate("""() => {
            localStorage.setItem('kr_saved_searches_v1', '{bad-json');
            localStorage.setItem('kr_compare_ids_v1', 'null');
        }""")
        await page.reload(wait_until="domcontentloaded")
        await page.locator("#smartRadarOpen").click()
        assert "Поки що немає" in await page.inner_text("#smartRadarSearches")
        assert await page.is_visible("#smartRadarPanel")
        await browser.close()


@pytest.mark.asyncio
async def test_older_api_claims_are_cleaned_before_rendering():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        async def older_api(route):
            await route.fulfill(
                status=200,
                content_type="application/json",
                headers={"access-control-allow-origin": "*"},
                body='{"success":true,"deals":[{"id":999,"title":"Тестове житло",'
                     '"price":10000,"rooms":1,"source":"Київ Радар (Пряма заявка)","phone":null,'
                     '"images":[],"lat":null,"lng":null,'
                     '"desc":"Здається реальна квартира від власника без посередників. '
                     'Лише інформація з джерела. '
                     'Повний комплект меблів та техніки, інтернет працює стабільно."}]}'
            )
        await page.route("**/api/deals*", older_api)
        await page.goto(URL, wait_until="domcontentloaded")
        await page.wait_for_function("LISTINGS.length === 1 && LISTINGS[0].id === 999")
        desc = await page.evaluate("LISTINGS[0].desc")
        assert desc == "Лише інформація з джерела."
        await browser.close()
