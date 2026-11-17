# -*- coding: utf-8 -*-
"""Kyiv Radar v1.7: real browser journey and failure-mode regression tests.

These tests use the shipped HTML/JS in desktop and phone viewports.
They do not require access to protected Telegram accounts, paid providers,
or production writes.
"""
import os

import pytest
from playwright.async_api import async_playwright

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
URL = "file:///" + os.path.join(ROOT, "index.html").replace("\\", "/")


async def open_app(page):
    await page.goto(URL, wait_until="domcontentloaded")
    await page.wait_for_selector("#krHero")
    await page.wait_for_function("LISTINGS.length > 0 && typeof window.KyivRadarSmart === 'object'")
    await page.wait_for_selector(".kr-compare-button")


@pytest.mark.asyncio
async def test_first_visit_explains_product_and_has_visible_search():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844},
                                      is_mobile=True, has_touch=True)
        await open_app(page)
        assert await page.get_by_role("heading", name="Квартири в Києві — легко знайти").is_visible()
        assert await page.locator("#krDataStatus").count() == 1
        assert await page.locator("#krResultsCount").count() == 1
        assert await page.locator("#smartRadarOpen").is_visible()
        assert await page.locator("#listViewContainer").is_visible()
        assert await page.evaluate("currentSort") == "price_asc"
        await page.locator("#searchInput").click()
        assert await page.evaluate("document.activeElement.id") == "searchInput"
        assert await page.locator("#searchInput").evaluate(
            "(node) => Number.parseFloat(getComputedStyle(node).fontSize)") >= 16
        assert await page.locator("#searchInput").evaluate("(node) => node.getBoundingClientRect().height") >= 44
        await browser.close()


@pytest.mark.asyncio
async def test_filter_count_reset_and_source_uncertainty():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        await open_app(page)
        await page.locator("#filterRooms1").click()
        assert "оголошень" in await page.inner_text("#krResultsCount")
        assert await page.locator("#krReset").is_visible()
        assert await page.evaluate("ACTIVE_FILTERS.rooms") == 1
        await page.locator("#krReset").click()
        assert await page.evaluate("ACTIVE_FILTERS.rooms") is None
        assert await page.locator("#krReset").is_hidden()
        assert "не перевірено" in (await page.inner_text("#krDataStatus"))
        await browser.close()


@pytest.mark.asyncio
async def test_browser_to_telegram_contact_is_persistent_and_actionable():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        await open_app(page)
        await page.evaluate("() => openDealModalById(LISTINGS[0].id)")
        assert await page.locator("#modalCallLabel").inner_text() == "Відкрити Telegram"
        await page.locator("#modalCallBtn").click()
        dialog = page.get_by_role("dialog", name="Відкрийте квартиру в Telegram")
        assert await dialog.is_visible()
        assert "/start" in await dialog.inner_text()
        assert await dialog.locator('a[href="https://t.me/prostov_shrink_bot"]').is_visible()
        assert await page.locator("#modalChatBtn").is_hidden()
        assert not any("+380" in x for x in (await dialog.inner_text(),))
        await page.keyboard.press("Escape")
        assert not await dialog.is_visible()
        await browser.close()


@pytest.mark.asyncio
async def test_result_card_can_be_compared_without_scrolling_long_select():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844},
                                      is_mobile=True, has_touch=True)
        await open_app(page)
        await page.locator("#listViewContainer .kr-compare-button").first.click()
        assert await page.evaluate("window.KyivRadarSmart.compareCount()") == 1
        await page.locator("#listViewContainer .kr-compare-button").nth(1).click()
        assert await page.evaluate("window.KyivRadarSmart.compareCount()") == 2
        assert await page.locator("#smartRadarPanel").is_visible()
        assert await page.locator("#smartRadarComparison > div").count() == 2
        await browser.close()


@pytest.mark.asyncio
async def test_unverified_coordinates_are_not_presented_as_exact_pins():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        await open_app(page)
        assert "не точні адреси" in await page.locator("#krMapNote").inner_text()
        assert await page.locator(".bird-pin").count() == 0
        if await page.evaluate("window.KR_MAP_AVAILABLE"):
            assert await page.locator(".kr-district-pin").count() >= 1
        assert await page.evaluate("LISTINGS.some(x => x.locationVerified === true)") is False
        await page.evaluate("() => applySort('distance')")
        assert await page.evaluate("currentSort") == "price_asc"
        await browser.close()


@pytest.mark.asyncio
async def test_no_leaflet_still_opens_list_and_search():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        await page.route("https://unpkg.com/**", lambda route: route.abort())
        await open_app(page)
        assert await page.evaluate("window.KR_MAP_AVAILABLE") is False
        assert await page.evaluate("CURRENT_VIEW_MODE") == "list"
        assert await page.locator("#listViewContainer").is_visible()
        assert await page.locator(".kr-compare-button").count() > 0
        await browser.close()


@pytest.mark.asyncio
async def test_landlord_browser_entry_guides_before_long_form():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        await open_app(page)
        await page.evaluate("() => openLandlordModal()")
        dialog = page.get_by_role("dialog", name="Оголошення надсилаються через Telegram")
        assert await dialog.is_visible()
        assert not await page.locator("#landlordModal").is_visible()
        assert await dialog.locator('a[href="https://t.me/prostov_shrink_bot"]').is_visible()
        await browser.close()


@pytest.mark.asyncio
async def test_mobile_photo_preparation_preserves_jpg_and_rejects_bad_heic():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await open_app(page)
        outcome = await page.evaluate("""async () => {
            const jpg = new File([new Uint8Array([1,2,3])], 'photo.jpg',
                {type:'image/jpeg'});
            const regular = await window.krPrepareUploadPhotos([jpg]);
            let invalidError = '';
            try {
                const broken = new File(['not an image'], 'broken.heic', {type:'image/heic'});
                await window.krPrepareUploadPhotos([broken]);
            } catch (err) { invalidError = String(err.message || err); }
            return {same: regular[0] === jpg, invalidError};
        }""")
        assert outcome["same"] is True
        assert "HEIC" in outcome["invalidError"]
        await browser.close()


@pytest.mark.asyncio
async def test_catalog_quality_suppresses_obviously_corrupted_fields():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.route("**/api/deals*", lambda route: route.abort())
        await open_app(page)
        await page.wait_for_function("LISTINGS.some(x => x.addressConflict === true)")
        flags = await page.evaluate("""() => ({
            badAddress: LISTINGS.filter(x => x.addressConflict === true).length,
            roomConflict: LISTINGS.filter(x => x.roomConflict === true).length,
            rawCorruptedAddress: LISTINGS.some(x => String(x.address || '').includes('Додати в обране')),
            unverifiedPin: LISTINGS.some(x => x.locationVerified === true)
        })""")
        assert flags["badAddress"] == 8
        assert flags["roomConflict"] >= 10
        assert flags["rawCorruptedAddress"] is False
        assert flags["unverifiedPin"] is False
        await page.evaluate("() => setFilter('rooms2')")
        incorrectly_matched = await page.evaluate(
            "getFilteredListings().some(d => d.roomConflict === true)"
        )
        assert incorrectly_matched is False
        await browser.close()


@pytest.mark.asyncio
async def test_offline_catalog_has_refresh_and_no_mobile_horizontal_overflow():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844},
                                      is_mobile=True, has_touch=True)
        await page.route("**/api/deals*", lambda route: route.abort())
        await open_app(page)
        assert await page.locator("#krRetry").is_visible()
        overflow = await page.evaluate(
            "() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - window.innerWidth"
        )
        assert overflow <= 4, "Mobile viewport must not require horizontal page scrolling"
        await page.locator("#krRetry").click()
        await page.wait_for_function("document.getElementById('krRetry').disabled === false")
        assert await page.locator("#krDataStatus").count() == 1
        await browser.close()


@pytest.mark.asyncio
async def test_linked_listing_opens_and_user_can_find_by_numeric_id():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        await page.goto(URL + "?deal=1", wait_until="domcontentloaded")
        await page.wait_for_function("LISTINGS.length > 0")
        await page.locator("#dealModal").wait_for(state="visible")
        assert await page.locator("#krShareListing").is_visible()
        await page.evaluate("() => closeDealModal()")
        await page.evaluate("() => handleSearch('#7')")
        assert await page.evaluate("getFilteredListings().length") == 1
        assert await page.evaluate("getFilteredListings()[0].id") == 7
        await browser.close()


@pytest.mark.asyncio
async def test_corrupt_favorites_storage_does_not_crash_entire_app():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.add_init_script("""() => {
            try { localStorage.setItem('kr_favs', '{broken-json'); } catch (e) {}
        }""")
        await open_app(page)
        assert await page.evaluate("LISTINGS.length") > 0
        assert await page.locator("#krResultsCount").is_visible()
        assert await page.locator("#searchInput").is_visible()
        await browser.close()
