# -*- coding: utf-8 -*-
"""v1.29: visible one-tap favorites destination in the actual mobile toolbar."""
from pathlib import Path
import pytest
from playwright.async_api import async_playwright

URL = (Path(__file__).resolve().parents[1] / "index.html").as_uri()


async def open_catalog(page):
    # The offline fixture is the checked-in historical catalog only.
    await page.route("**/api/deals*", lambda route: route.abort())
    await page.goto(URL, wait_until="domcontentloaded")
    await page.wait_for_function(
        "LISTINGS.length > 2 && document.querySelector('#krFavoritesShortcut') !== null")
    await page.evaluate("setViewMode('list')")


@pytest.mark.asyncio
@pytest.mark.parametrize("width,height", [(320,640), (390,844), (768,1024), (1280,800)])
async def test_favorites_entry_is_visible_and_one_tap(width,height):
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        page=await browser.new_page(viewport={"width":width,"height":height},
                                    is_mobile=width<500,has_touch=width<500)
        await open_catalog(page)
        shortcut=page.locator("#krFavoritesShortcut")
        await shortcut.wait_for(state="visible")
        box=await shortcut.bounding_box()
        assert box is not None and box["width"]>=44 and box["height"]>=44
        # One tap means the button is already on-screen, not revealed by
        # Playwright auto-scrolling the horizontal filter bar into view.
        assert box["x"] >= 0 and box["x"] + box["width"] <= width + 1
        assert await shortcut.get_attribute("aria-pressed")=="false"
        assert await shortcut.locator(".kr-favorites-count").inner_text()=="0"

        # No favorites yet: direct entry gives clear guidance, not an empty map.
        await shortcut.click()
        assert await shortcut.get_attribute("aria-pressed")=="true"
        assert await page.locator("#listViewContainer").get_by_text("Обраних квартир поки немає").is_visible()
        await shortcut.click()
        assert await shortcut.get_attribute("aria-pressed")=="false"
        assert await page.evaluate("getFilteredListings().length")>2
        await browser.close()


@pytest.mark.asyncio
async def test_saved_favorite_opens_with_one_tap_and_restores_search_conditions():
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        page=await browser.new_page(viewport={"width":390,"height":844},
                                    is_mobile=True,has_touch=True)
        await open_catalog(page)
        heart=page.locator("#listViewContainer [data-favorite-id]").first
        target=int(await heart.get_attribute("data-favorite-id"))
        await heart.click()
        assert await page.locator("#krFavoritesShortcut .kr-favorites-count").inner_text()=="1"

        await page.locator("#searchInput").fill("unmatched-test-query")
        await page.evaluate("setFilter('under15k')")
        old=await page.evaluate("({q:searchQuery,price:ACTIVE_FILTERS.maxPrice})")
        assert old=={"q":"unmatched-test-query","price":15000}
        assert await page.evaluate("getFilteredListings().length")==0

        await page.locator("#krFavoritesShortcut").click()
        assert await page.locator("#krFavoritesShortcut").get_attribute("aria-pressed")=="true"
        assert await page.locator("#searchInput").input_value()==""
        assert await page.evaluate("ACTIVE_FILTERS.maxPrice") is None
        assert await page.evaluate("getFilteredListings().map(x=>x.id)")==[target]
        assert await page.evaluate("CURRENT_VIEW_MODE")=="list"
        assert await page.locator(f'#listViewContainer [data-favorite-id="{target}"]').is_visible()

        # Returning to browse must not silently destroy the user's previous search.
        await page.locator("#krFavoritesShortcut").click()
        assert await page.locator("#krFavoritesShortcut").get_attribute("aria-pressed")=="false"
        assert await page.locator("#searchInput").input_value()=="unmatched-test-query"
        assert await page.evaluate("ACTIVE_FILTERS.maxPrice")==15000
        assert await page.evaluate("getFilteredListings().length")==0
        await browser.close()


@pytest.mark.asyncio
async def test_saved_favorites_reachable_after_reload_and_removed_in_place():
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        page=await browser.new_page(viewport={"width":390,"height":844},
                                    is_mobile=True,has_touch=True)
        await open_catalog(page)
        heart=page.locator("#listViewContainer [data-favorite-id]").first
        target=int(await heart.get_attribute("data-favorite-id"))
        await heart.click()
        await page.reload(wait_until="domcontentloaded")
        await page.wait_for_function("LISTINGS.length > 2")
        button=page.locator("#krFavoritesShortcut")
        assert await button.locator(".kr-favorites-count").inner_text()=="1"
        await button.click()
        assert await page.evaluate("getFilteredListings().map(x=>x.id)")==[target]
        await page.locator(f'#listViewContainer [data-favorite-id="{target}"]').click()
        assert await button.locator(".kr-favorites-count").inner_text()=="0"
        assert await page.locator("#listViewContainer").get_by_text("Обраних квартир поки немає").is_visible()
        assert await page.evaluate("getFilteredListings().length")==0
        await button.click()
        assert await page.evaluate("getFilteredListings().length")>2
        await browser.close()


@pytest.mark.asyncio
async def test_favorites_button_keyboard_and_filter_sheet_remain_in_sync():
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        page=await browser.new_page(viewport={"width":390,"height":844})
        await open_catalog(page)
        button=page.locator("#krFavoritesShortcut")
        await button.focus()
        await button.press("Enter")
        assert await button.get_attribute("aria-pressed")=="true"

        # Independent modern filter-sheet controls must agree with shortcut state.
        await page.locator("#krConditionsTrigger").click()
        assert await page.locator('#krConditionOptions input[data-key="favs"]').is_checked()
        await page.locator("#krFiltersClose").click()
        await button.focus()
        await button.press("Space")
        assert await button.get_attribute("aria-pressed")=="false"
        await browser.close()
