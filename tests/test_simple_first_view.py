# -*- coding: utf-8 -*-
"""First 30 seconds UX: quiet list-first catalog and plain-language help."""
import os
import pytest
from playwright.async_api import async_playwright

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
URL = "file:///" + os.path.join(ROOT, "index.html").replace("\\", "/")


async def ready(page):
    await page.goto(URL, wait_until="domcontentloaded")
    await page.wait_for_selector("#krRoomsTrigger")
    await page.wait_for_function("LISTINGS.length > 0 && CURRENT_VIEW_MODE === 'list'")
    await page.locator("#listViewContainer > div[onclick]").first.wait_for()


@pytest.mark.asyncio
async def test_phone_first_view_shows_photos_not_full_screen_map():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844},
                                      is_mobile=True, has_touch=True)
        await ready(page)
        assert await page.get_by_role("heading", name="Знайти квартиру").is_visible()
        assert await page.locator("#map").is_hidden()
        assert await page.locator("#listViewContainer").is_visible()
        assert await page.locator("#smartRadarOpen").is_visible()
        assert await page.locator("#krRoomsTrigger").is_visible()
        assert await page.locator("#filterPower").is_hidden()
        assert await page.locator("#filterRooms3").is_hidden()
        assert await page.locator("#listViewContainer img").first.is_visible()
        assert await page.locator("#listViewContainer img").first.bounding_box() is not None
        assert await page.locator("#listViewContainer > div[onclick]").count() >= 10
        first_card = await page.locator("#listViewContainer > div[onclick]").nth(0).bounding_box()
        second_card = await page.locator("#listViewContainer > div[onclick]").nth(1).bounding_box()
        assert first_card and second_card
        assert second_card["y"] >= first_card["y"] + first_card["height"] + 6, "Apartment cards must never overlap"
        # Body itself must not scroll horizontally (filter strip scrolls within itself).
        over = await page.evaluate(
            "() => Math.max(document.body.scrollWidth, document.documentElement.scrollWidth)-window.innerWidth"
        )
        assert over <= 4
        await browser.close()


@pytest.mark.asyncio
async def test_card_has_no_source_or_false_verification_but_detail_has_attribution():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        await ready(page)
        first = page.locator("#listViewContainer > div[onclick]").first
        card = await first.inner_text()
        assert "Джерело:" not in card
        assert "GPON" not in card
        assert "OLX" not in card
        assert "DOM.RIA" not in card
        await first.locator(".kr-open-detail").click()
        assert await page.locator("#dealModal").is_visible()
        assert await page.locator("#modalSourceDetails").is_visible()
        assert await page.locator("#modalOriginalLink").is_visible()
        text = await page.locator("#modalEquipment").inner_text()
        assert "Інтернет під час відключень" in text
        assert "оптичного термінала" in text
        assert "живлення роутера" in text
        assert "Генератор" not in card or "GPON" not in card
        await browser.close()


@pytest.mark.asyncio
async def test_advanced_filters_split_generator_and_fiber_correctly():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        await ready(page)
        await page.locator("#krConditionsTrigger").click()
        internet = page.locator('#krConditionOptions input[data-key="gpon"]')
        generator = page.locator('#krConditionOptions input[data-key="generator"]')
        assert await internet.is_visible()
        assert await generator.is_visible()
        await internet.check()
        await page.locator("#krFiltersApply").click()
        assert await page.evaluate("ACTIVE_FILTERS.gpon === true && ACTIVE_FILTERS.generator === false")
        await page.locator("#krConditionsTrigger").click()
        await generator.check()
        await page.locator("#krFiltersApply").click()
        assert await page.evaluate("ACTIVE_FILTERS.gpon === true && ACTIVE_FILTERS.generator === true")
        assert "2" in await page.locator("#krConditionsTrigger").inner_text()
        await page.locator("#krSimpleInfo").click()
        dialog = page.locator("#krSimpleHelp")
        assert await dialog.is_visible()
        assert "резервне живлення" in await dialog.inner_text()
        await dialog.get_by_role("button", name="Зрозуміло").click()
        assert await dialog.is_hidden()
        await browser.close()


@pytest.mark.asyncio
async def test_explicit_map_choice_can_be_restored_without_defaulting_all_visitors_to_map():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 800})
        await ready(page)
        await page.locator("#viewModeMapBtn").click()
        assert await page.evaluate("CURRENT_VIEW_MODE") == "map"
        await page.reload(wait_until="domcontentloaded")
        await page.wait_for_function("LISTINGS.length > 0 && CURRENT_VIEW_MODE === 'map'")
        assert await page.locator("#map").is_visible()
        await page.locator("#viewModeListBtn").click()
        assert await page.evaluate("CURRENT_VIEW_MODE") == "list"
        await browser.close()


@pytest.mark.asyncio
async def test_card_comparison_is_still_available_from_simple_view():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844},is_mobile=True,has_touch=True)
        await ready(page)
        await page.locator("#listViewContainer .kr-compare-button").first.click()
        assert await page.evaluate("window.KyivRadarSmart.compareCount()") == 1
        await page.locator("#listViewContainer .kr-compare-button").nth(1).click()
        assert await page.evaluate("window.KyivRadarSmart.compareCount()") == 2
        assert await page.locator("#smartRadarPanel").is_visible()
        await browser.close()
