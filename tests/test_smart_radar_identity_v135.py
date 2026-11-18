# -*- coding: utf-8 -*-
"""Identity safety of saved searches and apartment comparisons, all synthetic.

Neither old numeric IDs nor current catalog positions are valid apartment keys.
No production API requests, messages, live property data or private contacts.
"""
import json
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

URL = (Path(__file__).resolve().parents[1] / "index.html").as_uri()


async def ready(page):
    await page.route("**/api/deals*", lambda route: route.abort())
    await page.goto(URL, wait_until="domcontentloaded")
    await page.wait_for_function("""() => LISTINGS.length > 2 &&
        typeof favoriteKey === 'function' &&
        Boolean(window.KyivRadarSmart)""")
    await page.evaluate("setViewMode('list')")


@pytest.mark.asyncio
async def test_reused_numeric_id_never_binds_comparison_to_other_apartment():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        await ready(page)
        original = await page.evaluate("""() => {
          const d=LISTINGS[0];
          const key=favoriteKey(d);
          if (!key) throw Error("Expected a valid synthetic permalink");
          KyivRadarSmart.addFromCard(d.id);
          return {id:d.id,key,source:d.source,url:d.url,title:d.title};
        }""")
        stored = await page.evaluate("JSON.parse(localStorage.getItem('kr_compare_keys_v2'))")
        assert stored == {"version": 2, "keys": [original["key"]]}
        assert await page.evaluate("localStorage.getItem('kr_compare_ids_v1')") is None

        # New imported record reuses the old numeric ID; cannot replace selection.
        await page.evaluate("""(original) => {
          const other={...LISTINGS[1],id:original.id,title:"NOT THE ORIGINAL APARTMENT"};
          LISTINGS=[other];
          refreshFavoriteKeys();
          KyivRadarSmart.open();
        }""", original)
        assert await page.evaluate("KyivRadarSmart.compareCount()") == 1
        panel=page.locator("#smartRadarComparison")
        assert await panel.get_by_text("Збережене порівняння недоступне").is_visible()
        assert await panel.get_by_text("NOT THE ORIGINAL APARTMENT").count() == 0
        assert await panel.get_by_text(original["title"]).count() == 0
        # Original returns with a different numeric ID, but same stable identity.
        await page.evaluate("""(original) => {
          LISTINGS=[{...LISTINGS[0],id:99999,source:original.source,url:original.url,
                     title:original.title,rooms:2}];
          refreshFavoriteKeys();
          KyivRadarSmart.open();
        }""", original)
        assert await panel.get_by_text(original["title"]).is_visible()
        assert await panel.get_by_text("Збережене порівняння недоступне").count() == 0
        await browser.close()


@pytest.mark.asyncio
async def test_legacy_numeric_comparisons_quarantined_until_user_deletes():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page=await browser.new_page()
        await ready(page)
        await page.evaluate("""() => {
          localStorage.setItem('kr_compare_ids_v1','[1,2,2]');
        }""")
        await page.reload(wait_until="domcontentloaded")
        await page.wait_for_selector("#smartRadarOpen")
        await page.locator("#smartRadarOpen").click()
        panel=page.locator("#smartRadarComparison")
        assert await panel.get_by_text("Є старі порівняння").is_visible()
        assert await page.evaluate("KyivRadarSmart.compareCount()") == 0
        assert await page.evaluate("localStorage.getItem('kr_compare_ids_v1')") == "[1,2,2]"
        assert await page.evaluate("localStorage.getItem('kr_compare_keys_v2')") is None
        await panel.get_by_role("button",name="Видалити старі номери").click()
        assert await page.evaluate("localStorage.getItem('kr_compare_ids_v1')") is None
        await browser.close()


@pytest.mark.asyncio
async def test_saved_favorites_search_uses_same_stable_keys_as_favorite_hearts():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page=await browser.new_page()
        await ready(page)
        info=await page.evaluate("""() => {
          const d=LISTINGS[0];
          toggleFavorite(null,d.id);
          ACTIVE_FILTERS.favs=true;
          return {id:d.id,key:favoriteKey(d)};
        }""")
        assert info["key"]
        await page.locator("#smartRadarOpen").click()
        await page.get_by_role("button",name="Зберегти поточні фільтри").click()
        assert "1 зараз підходить" in await page.inner_text("#smartRadarSearches")
        search=await page.evaluate("JSON.parse(localStorage.getItem('kr_saved_searches_v1'))")
        assert info["key"] in search[0]["knownKeys"]
        assert "knownIds" not in search[0]
        # Reuse ID in catalog for unrelated source: no false favorite match.
        await page.evaluate("""(id) => {
          LISTINGS=[{...LISTINGS[1],id}];
          refreshFavoriteKeys();
          KyivRadarSmart.open();
        }""", info["id"])
        assert "0 зараз підходить" in await page.inner_text("#smartRadarSearches")
        assert "0 нових" in await page.inner_text("#smartRadarSearches")
        await browser.close()


@pytest.mark.asyncio
async def test_missing_and_ambiguous_identity_never_leaks_into_compare_selection():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page=await browser.new_page()
        await ready(page)
        await page.evaluate("""() => {
          const a=LISTINGS[0];
          LISTINGS=[a,{...a,id:9999}, {...LISTINGS[1],id:8888,url:null}];
          refreshFavoriteKeys();
          KyivRadarSmart.open();
        }""")
        opts=await page.locator("#smartRadarCompareSelect option").all_text_contents()
        assert len(opts)==1
        assert await page.evaluate("KyivRadarSmart.addFromCard(LISTINGS[0].id)") is False
        assert await page.evaluate("KyivRadarSmart.compareCount()") == 0
        await browser.close()


@pytest.mark.asyncio
async def test_old_search_numeric_baseline_does_not_fake_new_matches():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page=await browser.new_page()
        await ready(page)
        await page.evaluate("""() => {
          localStorage.setItem('kr_saved_searches_v1', JSON.stringify([{
            id:"old-synthetic",title:"Старий пошук",criteria:{query:"",filters:{}},
            knownIds:[1,2]
          }]));
        }""")
        await page.reload(wait_until="domcontentloaded")
        await page.wait_for_selector("#smartRadarOpen")
        await page.locator("#smartRadarOpen").click()
        text=await page.inner_text("#smartRadarSearches")
        assert "облік нових потребує оновлення" in text
        assert "150 нових" not in text
        await page.get_by_role("button",name="Переглянуто").click()
        text=await page.inner_text("#smartRadarSearches")
        assert "0 нових" in text
        stored=await page.evaluate("JSON.parse(localStorage.getItem('kr_saved_searches_v1'))")
        assert isinstance(stored[0]["knownKeys"],list)
        await browser.close()


@pytest.mark.asyncio
async def test_open_comparison_panel_immediately_hides_withdrawn_offer():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width":390,"height":844})
        await ready(page)
        await page.evaluate("""() => KyivRadarSmart.addFromCard(LISTINGS[0].id)""")
        await page.locator("#smartRadarOpen").click()
        container=page.locator("#smartRadarComparison")
        assert await container.get_by_text("Збережене порівняння недоступне").count() == 0
        # A rights revocation or empty new API response removes this offer
        # while the compare panel remains open.
        await page.evaluate("""() => {
          LISTINGS=[];
          refreshFavoriteKeys();
          renderAll();
        }""")
        assert await container.get_by_text("Збережене порівняння недоступне").is_visible()
        assert await page.evaluate("KyivRadarSmart.compareCount()") == 1
        await browser.close()


@pytest.mark.asyncio
async def test_saved_search_keeps_exact_four_and_five_plus_room_filters():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width":390,"height":844})
        await ready(page)
        await page.evaluate("""() => {
          const original=LISTINGS[0];
          LISTINGS=[
            {...original,id:44551,source:"synthetic-partner",rooms:4,
             title:"FOUR ROOMS",url:"https://example.org/rooms/four",price:22000},
            {...original,id:44552,source:"synthetic-partner",rooms:6,
             title:"SIX ROOMS",url:"https://example.org/rooms/six",price:23000}
          ];
          refreshFavoriteKeys();
          ACTIVE_FILTERS.rooms=4;
          ACTIVE_FILTERS.maxPrice=25000;
          searchQuery="";
        }""")
        await page.locator("#smartRadarOpen").click()
        await page.get_by_role("button",name="Зберегти поточні фільтри").click()
        assert "1 зараз підходить" in await page.inner_text("#smartRadarSearches")
        snapshot=await page.evaluate("JSON.parse(localStorage.getItem('kr_saved_searches_v1'))")
        assert snapshot[0]["criteria"]["filters"]["rooms"] == 4
        assert snapshot[0]["criteria"]["filters"]["maxPrice"] == 25000
        await page.evaluate("ACTIVE_FILTERS.rooms=5")
        await page.get_by_role("button",name="Зберегти поточні фільтри").click()
        assert await page.locator("#smartRadarSearches > div").count() == 2
        snapshot=await page.evaluate("JSON.parse(localStorage.getItem('kr_saved_searches_v1'))")
        assert snapshot[1]["criteria"]["filters"]["rooms"] == 5
        assert len(snapshot[0]["knownKeys"]) == 1
        assert len(snapshot[1]["knownKeys"]) == 1
        assert snapshot[0]["knownKeys"][0] != snapshot[1]["knownKeys"][0]
        await browser.close()
