# -*- coding: utf-8 -*-
"""Kyiv Radar 1.9: screenshot-grounded compact design and in-card gallery regression."""
import os
import re
import pytest
from playwright.async_api import async_playwright

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
URL = "file:///" + os.path.join(ROOT, "index.html").replace("\\", "/")


async def ready(page):
    await page.goto(URL, wait_until="domcontentloaded")
    await page.wait_for_selector("#krHero .kr-ukraine-curve svg")
    await page.wait_for_function(
        "typeof LISTINGS !== 'undefined' && LISTINGS.length > 0 && CURRENT_VIEW_MODE === 'list'"
    )
    await page.locator("#listViewContainer .kr-gallery-count").first.wait_for()


@pytest.mark.asyncio
async def test_skyline_wave_and_compact_result_row_on_phone():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844},
                                      is_mobile=True, has_touch=True)
        await ready(page)
        assert await page.locator("#krHero .kr-kyiv-skyline svg").count() == 1
        assert await page.locator("#krHero .kr-ukraine-curve path").count() == 1
        assert await page.locator(".kr-brand-mark svg").count() == 1
        count = await page.locator("#krResultsCount").inner_text()
        assert re.match(r"^\d+ оголош(ень|ення)$", count)
        assert "із" not in count
        assert await page.locator("#krDataStatus").is_visible()
        assert await page.locator("#viewModeListBtn").is_visible()
        bar = await page.locator("#krResultsBar").bounding_box()
        assert bar and bar["height"] <= 60, "The results/status toolbar should fit in one slim row"
        overflow = await page.evaluate(
            "() => Math.max(document.body.scrollWidth, document.documentElement.scrollWidth) - innerWidth"
        )
        assert overflow <= 4, "No horizontal viewport overflow"
        await browser.close()


@pytest.mark.asyncio
async def test_card_photo_buttons_change_image_without_opening_detail():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844},
                                      is_mobile=True, has_touch=True)
        await ready(page)
        card = page.locator("#listViewContainer > div[onclick]").first
        count = card.locator(".kr-gallery-count")
        assert await count.inner_text() == "1/10"
        src1 = await card.locator("img.kr-gallery-image").get_attribute("src")
        await card.locator(".kr-gallery-next").click()
        assert await count.inner_text() == "2/10"
        src2 = await card.locator("img.kr-gallery-image").get_attribute("src")
        assert src1 != src2
        assert await page.locator("#dealModal").is_hidden()
        await card.locator(".kr-gallery-prev").click()
        assert await count.inner_text() == "1/10"
        await card.locator(".kr-open-detail").click()
        assert await page.locator("#dealModal").is_visible()
        await browser.close()


@pytest.mark.asyncio
async def test_in_card_swipe_keeps_vertical_scroll_and_prevents_unwanted_modal():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844},
                                      is_mobile=True, has_touch=True)
        await ready(page)
        photo = page.locator("#listViewContainer > div[onclick]").first.locator(".relative.h-48")
        await photo.evaluate("""element => {
          const fire = (x1,y1,x2,y2) => {
            const a = new Touch({identifier:7,target:element,clientX:x1,clientY:y1});
            const b = new Touch({identifier:7,target:element,clientX:x2,clientY:y2});
            element.dispatchEvent(new TouchEvent('touchstart',{bubbles:true,touches:[a],changedTouches:[a]}));
            element.dispatchEvent(new TouchEvent('touchend',{bubbles:true,touches:[],changedTouches:[b]}));
          };
          fire(310,190,80,192);
          element.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true}));
        }""")
        assert await photo.locator(".kr-gallery-count").inner_text() == "2/10"
        assert await page.locator("#dealModal").is_hidden()
        await photo.evaluate("""element => {
          const a = new Touch({identifier:8,target:element,clientX:200,clientY:130});
          const b = new Touch({identifier:8,target:element,clientX:185,clientY:310});
          element.dispatchEvent(new TouchEvent('touchstart',{bubbles:true,touches:[a],changedTouches:[a]}));
          element.dispatchEvent(new TouchEvent('touchend',{bubbles:true,touches:[],changedTouches:[b]}));
        }""")
        assert await photo.locator(".kr-gallery-count").inner_text() == "2/10"
        await browser.close()


@pytest.mark.asyncio
async def test_only_one_photo_has_no_misleading_gallery_controls():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        await ready(page)
        await page.evaluate("""() => {
          const item = LISTINGS[0];
          item.images = [item.images[0]];
          renderAll();
        }""")
        first = page.locator("#listViewContainer > div[onclick]").first
        assert await first.locator(".kr-gallery-controls").count() == 0
        assert await first.locator("img").count() == 1
        await browser.close()
