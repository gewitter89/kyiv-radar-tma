# -*- coding: utf-8 -*-
"""v1.28: a favorite must work in list, carousel and after a refresh.

Real mobile-browser regression against the shipped HTML/JavaScript; no
production API, account login, Telegram token or live listings involved.
"""
import json
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
URL = (ROOT / "index.html").as_uri()


async def open_apartments(page):
    await page.route("**/api/deals*", lambda route: route.abort())
    await page.goto(URL, wait_until="domcontentloaded")
    await page.wait_for_function("LISTINGS.length > 2 && typeof toggleFavorite === 'function'")
    await page.evaluate("setViewMode('list')")
    await page.locator("#listViewContainer [data-favorite-id]").first.wait_for(state="visible")


@pytest.mark.asyncio
@pytest.mark.parametrize("width,height", [(320, 640), (390, 844), (768, 1024)])
async def test_heart_taps_save_and_remove_without_opening_listing(width, height):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": width, "height": height},
                                      is_mobile=width < 500, has_touch=width < 500)
        await open_apartments(page)
        heart = page.locator("#listViewContainer [data-favorite-id]").first
        fav_id = int(await heart.get_attribute("data-favorite-id"))
        assert await heart.get_attribute("aria-pressed") == "false"
        assert await heart.get_attribute("aria-label") == "Додати в обрані"
        bounds = await heart.bounding_box()
        assert bounds and bounds["width"] >= 44 and bounds["height"] >= 44
        await heart.click()
        assert await page.locator("#dealModal").is_hidden()
        selected = page.locator(f'#listViewContainer [data-favorite-id="{fav_id}"]')
        assert await selected.get_attribute("aria-pressed") == "true"
        assert await selected.get_attribute("aria-label") == "Прибрати з обраного"
        assert await page.locator("#favCount").inner_text() == "1"
        saved = await page.evaluate("JSON.parse(localStorage.getItem('kr_favs'))")
        assert saved == [fav_id]
        await selected.click()
        assert await page.locator("#favCount").inner_text() == "0"
        assert await page.locator(f'#listViewContainer [data-favorite-id="{fav_id}"]').get_attribute("aria-pressed") == "false"
        assert await page.evaluate("JSON.parse(localStorage.getItem('kr_favs'))") == []
        await browser.close()


@pytest.mark.asyncio
async def test_favorites_survive_reload_and_favorites_filter_removes_card_immediately():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844},
                                      is_mobile=True, has_touch=True)
        await open_apartments(page)
        heart = page.locator("#listViewContainer [data-favorite-id]").first
        fav_id = int(await heart.get_attribute("data-favorite-id"))
        await heart.click()
        await page.reload(wait_until="domcontentloaded")
        await page.wait_for_function("LISTINGS.length > 2")
        await page.evaluate("setViewMode('list')")
        selected = page.locator(f'#listViewContainer [data-favorite-id="{fav_id}"]')
        assert await selected.get_attribute("aria-pressed") == "true"
        assert await page.locator("#favCount").inner_text() == "1"
        await page.evaluate("setFilter('favs')")
        assert await page.locator("#filterFavs").get_attribute("aria-pressed") == "true"
        assert await page.evaluate("getFilteredListings().map(x => x.id)") == [fav_id]
        await selected.click()
        assert await page.evaluate("getFilteredListings().length") == 0
        assert await page.locator("#favCount").inner_text() == "0"
        assert await page.locator("#listViewContainer .kr-empty-state").is_visible()
        await page.evaluate("setFilter('favs')")
        assert await page.locator("#filterFavs").get_attribute("aria-pressed") == "false"
        assert await page.evaluate("getFilteredListings().length") > 2
        await browser.close()


@pytest.mark.asyncio
async def test_mobile_list_scroll_position_preserved_and_carousel_heart_updated():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844},
                                      is_mobile=True, has_touch=True)
        await open_apartments(page)
        list_view = page.locator("#listViewContainer")
        target = list_view.locator("[data-favorite-id]").nth(12)
        await target.scroll_into_view_if_needed()
        previous = await list_view.evaluate("element => element.scrollTop")
        fav_id = int(await target.get_attribute("data-favorite-id"))
        await target.click()
        new_position = await list_view.evaluate("element => element.scrollTop")
        assert abs(new_position - previous) <= 5
        assert await page.locator(f'#carousel-track [data-favorite-id="{fav_id}"]').get_attribute("aria-pressed") == "true"
        # Trigger a second representation: the shared state must update the list.
        await page.locator(f'#carousel-track [data-favorite-id="{fav_id}"]').evaluate("element => element.click()")
        assert await page.locator(f'#listViewContainer [data-favorite-id="{fav_id}"]').get_attribute("aria-pressed") == "false"
        await browser.close()


@pytest.mark.asyncio
async def test_saved_string_ids_normalized_and_corrupt_data_is_ignored():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        await page.add_init_script("""() => {
          try { localStorage.setItem('kr_favs', JSON.stringify(['1', '2', 'bad', -8])); }
          catch (e) {}
        }""")
        await open_apartments(page)
        assert await page.evaluate("FAVORITES.has(1) && FAVORITES.has(2)") is True
        assert await page.evaluate("FAVORITES.has('1')") is False
        assert await page.locator("#favCount").inner_text() == "2"
        await browser.close()


@pytest.mark.asyncio
async def test_keyboard_button_can_toggle_favorite_without_opening_modal():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        await open_apartments(page)
        heart = page.locator("#listViewContainer [data-favorite-id]").first
        fav_id = int(await heart.get_attribute("data-favorite-id"))
        await heart.focus()
        await heart.press("Enter")
        assert await page.locator(f'#listViewContainer [data-favorite-id="{fav_id}"]').get_attribute("aria-pressed") == "true"
        assert await page.locator("#dealModal").is_hidden()
        await browser.close()
