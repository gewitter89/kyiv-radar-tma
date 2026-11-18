# -*- coding: utf-8 -*-
"""Stable favorites security regressions. No live feed or API credentials."""
import json
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

URL = (Path(__file__).resolve().parents[1] / "index.html").as_uri()


async def setup(page):
    await page.route("**/api/deals*", lambda route: route.abort())
    await page.goto(URL, wait_until="domcontentloaded")
    await page.wait_for_function(
        "LISTINGS.length > 2 && typeof favoriteKey === 'function' && "
        "typeof KRFavoriteIdentity !== 'undefined'")
    await page.evaluate("setViewMode('list')")


@pytest.mark.asyncio
async def test_numeric_id_reuse_does_not_reassign_favorite_to_wrong_apartment():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width":390,"height":844},
                                      is_mobile=True,has_touch=True)
        await setup(page)
        chosen = await page.evaluate("""() => {
          const target = LISTINGS[0];
          toggleFavorite(null, target.id);
          return {id:target.id,key:favoriteKey(target),url:target.url,source:target.source};
        }""")
        assert chosen["key"]
        # A later catalog refresh reuses the old numeric ID for a different offer.
        result = await page.evaluate("""(chosen) => {
          const old = LISTINGS.find(i => i.id === chosen.id);
          const unrelated = {...LISTINGS[1], id: chosen.id};
          const sameOfferNewNumericId = {...old, id: 9999821};
          LISTINGS = [unrelated, sameOfferNewNumericId];
          refreshFavoriteKeys();
          renderAll();
          return {
            savedWrong: FAVORITES.has(favoriteKey(unrelated)),
            savedOriginal: FAVORITES.has(favoriteKey(sameOfferNewNumericId)),
            visible: getFilteredListings().length,
            keys: JSON.parse(localStorage.getItem('kr_favs_v2')).keys
          };
        }""", chosen)
        assert result["savedWrong"] is False
        assert result["savedOriginal"] is True
        assert result["keys"] == [chosen["key"]]
        await page.evaluate("setFilter('favs')")
        assert await page.evaluate("getFilteredListings().map(i=>i.id)") == [9999821]
        await browser.close()


@pytest.mark.asyncio
async def test_same_numeric_id_changed_url_does_not_show_as_saved():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width":390,"height":844})
        await setup(page)
        result = await page.evaluate("""() => {
          const first = LISTINGS[0];
          toggleFavorite(null, first.id);
          const oldKey = favoriteKey(first);
          LISTINGS = [{...first, url:'https://different.example.ua/brand-new-offer'}];
          refreshFavoriteKeys();
          renderAll();
          return {oldKey, newKey:favoriteKey(LISTINGS[0]), red:
            document.querySelector('[data-favorite-id]')?.getAttribute('aria-pressed')};
        }""")
        assert result["oldKey"] != result["newKey"]
        assert result["red"] == "false"
        await page.evaluate("setFilter('favs')")
        assert await page.evaluate("getFilteredListings().length") == 0
        assert await page.locator("#listViewContainer").get_by_text(
            "Збережені оголошення зараз недоступні").is_visible()
        await browser.close()


@pytest.mark.asyncio
async def test_duplicated_source_url_is_ambiguous_and_not_savable():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width":390,"height":844})
        await setup(page)
        result = await page.evaluate("""() => {
          const a = LISTINGS[0];
          LISTINGS = [a, {...a, id:888888}];
          refreshFavoriteKeys();
          renderAll();
          toggleFavorite(null, a.id);
          return {
            keys:FAVORITES.size,
            firstDisabled:document.querySelector('[data-favorite-id]')?.disabled,
            secondDisabled:[...document.querySelectorAll('[data-favorite-id]')].every(b=>b.disabled)
          };
        }""")
        assert result == {"keys":0,"firstDisabled":True,"secondDisabled":True}
        await browser.close()


@pytest.mark.asyncio
async def test_stable_identity_strips_tracking_but_not_listing_identifiers():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await setup(page)
        keys = await page.evaluate("""() => {
          const source='OLX';
          const key=url=>KRFavoriteIdentity.stableKey({source,url});
          return {
           clean:key('https://www.olx.ua/d/uk/obyavlenie/test-IDA1.html'),
           tracking:key('https://www.olx.ua/d/uk/obyavlenie/test-IDA1.html?utm_source=ad&gclid=xyz#photos'),
           token:key('https://www.olx.ua/offer?auth_token=secret'),
           root:key('https://www.olx.ua/'),
           relative:key('/d/test'),
           insecure:key('http://www.olx.ua/d/test'),
           a:key('https://example.ua/offer?id=123'),
           b:key('https://example.ua/offer?id=124'),
           noSource:KRFavoriteIdentity.stableKey({url:'https://example.ua/x'})
          };
        }""")
        assert keys["clean"] == keys["tracking"]
        assert keys["a"] != keys["b"]
        assert all(keys[k] is None for k in ("token","root","relative","insecure","noSource"))
        await browser.close()


@pytest.mark.asyncio
async def test_old_numeric_only_favorites_remain_unresolved_until_manual_clear():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width":390,"height":844})
        await page.add_init_script("""(() => {
          localStorage.setItem('kr_favs', JSON.stringify([1,2]));
        })();""")
        await setup(page)
        assert await page.evaluate("FAVORITES.size") == 0
        assert await page.evaluate("LEGACY_FAVORITE_IDS.size") == 2
        await page.locator("#krFavoritesShortcut").click()
        assert await page.evaluate("getFilteredListings().length") == 0
        warning=page.locator("#listViewContainer").get_by_text("2 старих збережень", exact=False)
        assert await warning.is_visible()
        assert await page.evaluate("JSON.parse(localStorage.getItem('kr_favs'))") == [1,2]
        page.once("dialog", lambda dialog: dialog.accept())
        await page.locator("#listViewContainer").get_by_role(
            "button", name="Видалити старі номери").click()
        assert await page.evaluate("LEGACY_FAVORITE_IDS.size") == 0
        assert await page.evaluate("localStorage.getItem('kr_favs')") is None
        await browser.close()


@pytest.mark.asyncio
async def test_corrupted_v2_storage_and_legacy_are_ignored_without_crashing():
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        page=await browser.new_page()
        await page.add_init_script("""(() => {
          localStorage.setItem('kr_favs_v2','{this is not JSON');
          localStorage.setItem('kr_favs','{also broken');
        })();""")
        await setup(page)
        assert await page.evaluate("FAVORITES.size+LEGACY_FAVORITE_IDS.size") == 0
        assert await page.locator("#krFavoritesShortcut").is_visible()
        heart=page.locator("#listViewContainer [data-favorite-id]").first
        await heart.click()
        assert await page.evaluate("JSON.parse(localStorage.getItem('kr_favs_v2')).version") == 2
        await browser.close()


@pytest.mark.asyncio
async def test_saved_partner_becomes_unavailable_on_catalog_withdrawal_no_cached_card():
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        page=await browser.new_page(viewport={"width":390,"height":844})
        await setup(page)
        result=await page.evaluate("""() => {
          const old=LISTINGS[0]; toggleFavorite(null,old.id);
          LISTINGS=LISTINGS.filter(item=>item.id!==old.id);
          refreshFavoriteKeys(); renderAll();
          return {count:FAVORITES.size, active:getFilteredListings().some(x=>x.id===old.id)};
        }""")
        assert result == {"count":1,"active":False}
        await page.locator("#krFavoritesShortcut").click()
        assert await page.evaluate("getFilteredListings().length") == 0
        assert await page.locator("#listViewContainer").get_by_text(
            "Збережені оголошення зараз недоступні").is_visible()
        # No old listing is recreated from localStorage snapshots.
        assert await page.evaluate(
            "JSON.stringify(JSON.parse(localStorage.getItem('kr_favs_v2'))).includes('images')"
        ) is False
        await browser.close()
