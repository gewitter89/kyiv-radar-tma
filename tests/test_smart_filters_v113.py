# -*- coding: utf-8 -*-
"""v1.13: real responsive browser regression for native catalog-powered filters."""
import os
import pytest
from playwright.async_api import async_playwright

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
URL = "file:///" + os.path.join(ROOT, "index.html").replace("\\", "/")


async def ready(page):
    await page.goto(URL, wait_until="domcontentloaded")
    await page.wait_for_selector("#krRoomsTrigger")
    await page.wait_for_function(
        "typeof LISTINGS !== 'undefined' && LISTINGS.length > 0 && CURRENT_VIEW_MODE === 'list'"
    )


async def select_room(page, rooms):
    await page.locator("#krRoomsTrigger").click()
    await page.locator(f'#krRoomsOptions button[data-room="{rooms}"]').click()
    await page.locator("#krFiltersApply").click()


@pytest.mark.asyncio
@pytest.mark.parametrize("width,height",[(320,640),(390,844),(768,900)])
async def test_compact_filters_and_logo_watermark_do_not_overlap(width,height):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width":width,"height":height},
                                      is_mobile=width<700, has_touch=width<700)
        await ready(page)
        assert await page.get_by_role("heading",name="Знайти квартиру").is_visible()
        assert await page.locator("#filterRooms1").is_hidden()
        assert await page.locator("#filterRooms2").is_hidden()
        assert await page.locator("#krMoreFilters").is_hidden()
        for selector in ["#krRoomsTrigger","#krPriceTrigger","#krConditionsTrigger",
                         "#smartRadarOpen","#viewModeListBtn","#searchInput"]:
            assert await page.locator(selector).is_visible()
        assert "kyiv-radar-mark.svg" in await page.locator("body > header").evaluate(
            "(el) => getComputedStyle(el,'::after').backgroundImage")
        assert await page.locator("#searchInput").evaluate(
            "(el) => el.getBoundingClientRect().height") >= 44
        assert await page.locator("#krRoomsTrigger").evaluate(
            "(el) => el.getBoundingClientRect().height") >= 44
        geom = await page.evaluate("""() => {
          const outer=document.querySelector('#filterBarWrapper').getBoundingClientRect();
          const controls=[...document.querySelectorAll('#krFilterToolbar button'),document.querySelector('#smartRadarOpen')];
          return {outer:{left:outer.left,right:outer.right},items:controls.map(x=>{
            const r=x.getBoundingClientRect(); return {left:r.left,right:r.right,width:r.width}
          })};
        }""")
        assert all(x["left"]>=geom["outer"]["left"]-2 and x["right"]<=geom["outer"]["right"]+2
                   for x in geom["items"]), "All controls fit the filter toolbar"
        over=await page.evaluate(
            "() => Math.max(document.body.scrollWidth,document.documentElement.scrollWidth)-innerWidth")
        assert over<=4
        await page.locator("#krRoomsTrigger").click()
        assert await page.locator("#krFiltersSheet").is_visible()
        assert await page.locator("#krFiltersClose").is_visible()
        assert await page.locator("#krFiltersSheet").get_attribute("role") is None
        assert await page.locator(".kr-filters-panel").get_attribute("aria-modal")=="true"
        await page.keyboard.press("Escape")
        assert await page.locator("#krFiltersSheet").is_hidden()
        await browser.close()


@pytest.mark.asyncio
async def test_exact_rooms_three_four_and_five_plus_with_synthetic_local_records():
    """No guess: 3 is exactly 3, 4 is 4, and 5+ includes >= 5."""
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        page=await browser.new_page(viewport={"width":390,"height":844},is_mobile=True,has_touch=True)
        await ready(page)
        await page.evaluate("""() => {
          const original={...LISTINGS[0],roomConflict:false,price:10000,
            generator:false,gpon:false,pets:false};
          LISTINGS.push({...original,id:993004,rooms:4,title:'Local synthetic four rooms'});
          LISTINGS.push({...original,id:993005,rooms:5,title:'Local synthetic five rooms'});
          LISTINGS.push({...original,id:993006,rooms:6,title:'Local synthetic six rooms'});
          renderAll();
        }""")
        await select_room(page,"3")
        assert await page.evaluate("getFilteredListings().every(a => Number(a.rooms) === 3)")
        assert await page.evaluate("getFilteredListings().length >= 1")
        await select_room(page,"4")
        ids=await page.evaluate("getFilteredListings().map(a => a.id)")
        assert ids==[993004], "4 rooms must not include 3- or 5-room listings"
        await select_room(page,"5")
        ids=await page.evaluate("getFilteredListings().map(a => a.id)")
        assert sorted(ids)==[993005,993006], "5+ includes every property with at least five rooms"
        assert "5+" in await page.locator("#krRoomsTrigger").inner_text()
        await browser.close()


@pytest.mark.asyncio
async def test_real_room_availability_uses_listings_not_faked_choices():
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        page=await browser.new_page(viewport={"width":390,"height":844})
        await ready(page)
        await page.locator("#krRoomsTrigger").click()
        expected=await page.evaluate("""() => [3,4,5].map(n => {
          return LISTINGS.filter(a => a.roomConflict!==true &&
          (n===5?Number(a.rooms)>=5:Number(a.rooms)===n)).length;
        })""")
        for value,count in zip([3,4,5],expected):
            label=await page.locator(f'#krRoomsOptions button[data-room="{value}"]').get_attribute("aria-label")
            assert str(count) in label
        assert await page.locator("#krRoomNotice").is_visible()
        await page.locator("#krFiltersClose").click()
        await browser.close()


@pytest.mark.asyncio
async def test_price_and_conditions_apply_and_cancel_without_side_effects():
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        page=await browser.new_page(viewport={"width":390,"height":844},is_mobile=True,has_touch=True)
        await ready(page)
        await page.locator("#krPriceTrigger").click()
        await page.locator("#krMaxPriceInput").fill("12000")
        await page.keyboard.press("Escape")
        assert await page.evaluate("ACTIVE_FILTERS.maxPrice") is None
        await page.locator("#krPriceTrigger").click()
        await page.locator("#krMaxPriceInput").fill("12000")
        await page.locator("#krFiltersApply").click()
        assert await page.evaluate("ACTIVE_FILTERS.maxPrice")==12000
        assert await page.evaluate(
            "getFilteredListings().every(a => Number(a.price) <= 12000)")
        assert "12" in await page.locator("#krPriceTrigger").inner_text()
        await page.locator("#krConditionsTrigger").click()
        await page.locator('#krConditionOptions input[data-key="generator"]').check()
        await page.locator('#krConditionOptions input[data-key="gpon"]').check()
        await page.locator("#krFiltersApply").click()
        assert await page.evaluate("ACTIVE_FILTERS.generator && ACTIVE_FILTERS.gpon")
        await page.locator("#krConditionsTrigger").click()
        await page.locator("#krFiltersReset").click()
        await page.locator("#krFiltersApply").click()
        assert await page.evaluate(
            "ACTIVE_FILTERS.rooms === null && ACTIVE_FILTERS.maxPrice === null && !ACTIVE_FILTERS.generator && !ACTIVE_FILTERS.gpon")
        assert await page.locator("#krReset").is_hidden()
        await browser.close()


@pytest.mark.asyncio
async def test_filter_sheet_scrolls_on_short_telegram_viewport():
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        page=await browser.new_page(viewport={"width":320,"height":480},
                                    is_mobile=True,has_touch=True)
        await ready(page)
        await page.locator("#krConditionsTrigger").click()
        scroll=page.locator("#krFiltersScroll")
        await scroll.wait_for(state="visible")
        geom=await scroll.evaluate(
            "(el) => ({client:el.clientHeight,scroll:el.scrollHeight,style:getComputedStyle(el).overflowY})")
        assert geom["scroll"]>geom["client"]+50
        assert geom["style"]=="auto"
        await scroll.evaluate("(el) => el.scrollTop = el.scrollHeight")
        assert await scroll.evaluate("(el) => el.scrollTop")>50
        assert await page.locator("#krFiltersApply").is_visible()
        await page.locator("#krFiltersClose").click()
        await browser.close()
