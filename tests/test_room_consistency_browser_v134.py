# -*- coding: utf-8 -*-
"""Playwright: contradictory room data cannot masquerade as a valid filter."""
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

ROOT=Path(__file__).resolve().parents[1]
URL=(ROOT/"index.html").as_uri()


@pytest.mark.asyncio
async def test_room_claims_consistency_and_unknowns_in_actual_browser():
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        page=await browser.new_page(viewport={"width":390,"height":844},
                                    is_mobile=True,has_touch=True)
        await page.goto(URL,wait_until="domcontentloaded")
        await page.wait_for_function("Boolean(window.krQualityCatalog) && Boolean(window.krQualityRules)")
        report=await page.evaluate("""() => {
          const rules=window.krQualityRules;
          return {
            uk: rules.explicitRoomClaims("Двокімнатна квартира"),
            ru: rules.explicitRoomClaims("2-х комнатная квартира"),
            titleDesc: rules.explicitRoomClaims("1-кімнатна", "2-кімнатна"),
            studio: rules.explicitRoomClaims("Студія, окрема спальня, 2 поверх"),
            roomsFromTitle: rules.roomCountFromTitle("Трикімнатна квартира")
          };
        }""")
        assert report == {"uk":[2],"ru":[2],"titleDesc":[1,2],
                          "studio":[],"roomsFromTitle":3}

        result=await page.evaluate("""() => {
          const source={id:990911,source:"Київ Радар (Пряма заявка)",
            title:"2-кімнатна квартира",desc:"Опис із джерела",
            rooms:1,price:15000,district:"Дарницький",
            address:"Тестовий район",images:[],
            isOwnerVerified:true,area:50,moderationStatus:"approved"};
          const clean=window.krQualityCatalog([source])[0];
          return {rooms:clean.rooms,roomConflict:clean.roomConflict,
                  initial:getDealRooms(clean),
                  sourceStillHasRooms:source.rooms};
        }""")
        assert result == {"rooms":None,"roomConflict":True,"initial":None,
                          "sourceStillHasRooms":1}
        await browser.close()


@pytest.mark.asyncio
async def test_conflicting_room_count_not_displayed_as_one_room_in_cards():
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        page=await browser.new_page(viewport={"width":390,"height":844},
                                    is_mobile=True,has_touch=True)
        await page.goto(URL,wait_until="domcontentloaded")
        await page.wait_for_function("Boolean(window.krQualityCatalog) && typeof renderAll === 'function'")
        await page.evaluate("""() => {
          LISTINGS=window.krQualityCatalog([{
            id:990912,source:"Київ Радар (Пряма заявка)",
            title:"2-кімнатна тестова квартира",desc:"Тестова пропозиція",
            rooms:1,price:15000,district:"Дарницький",
            address:"Тестове місто",images:[],area:50,
            moderationStatus:"approved",url:"https://example.invalid/testing"
          }]);
          CURRENT_VIEW_MODE='list';ACTIVE_FILTERS.rooms=null;
          renderAll();
        }""")
        assert await page.locator("#listViewContainer").get_by_text(
            "Кімнатність уточнюється",exact=False).count()>=1
        assert await page.evaluate("LISTINGS[0].rooms") is None
        await page.evaluate("ACTIVE_FILTERS.rooms = 1")
        assert await page.evaluate("getFilteredListings().length") == 0
        await browser.close()
