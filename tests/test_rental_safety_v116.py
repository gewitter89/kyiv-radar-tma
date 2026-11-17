# -*- coding: utf-8 -*-
"""Minimal, readable advice belongs with the listing decision, not a fake risk score."""
import os
import pytest
from playwright.async_api import async_playwright

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
URL = "file:///" + os.path.join(ROOT, "index.html").replace("\\", "/")


@pytest.mark.asyncio
@pytest.mark.parametrize("width,height",[(320,480),(390,844)])
async def test_rental_safety_disclosure_is_optional_accessible_and_scrollable(width,height):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width":width,"height":height},
                                      is_mobile=True,has_touch=True)
        await page.goto(URL,wait_until="domcontentloaded")
        await page.locator("#listViewContainer .kr-open-detail").first.click()
        safety=page.locator("#krRentalSafety")
        await safety.scroll_into_view_if_needed()
        summary=safety.locator("summary")
        assert await summary.is_visible()
        assert not await safety.evaluate("(el) => el.open")
        await summary.click()
        assert await safety.evaluate("(el) => el.open")
        content=await safety.inner_text()
        for phrase in ("Не переказуйте завдаток","договору","комісії","Поскаржитися","не означають"):
            assert phrase in content
        assert await page.locator("#modalOriginalLink").count()==1
        # Advice is independent from the catalog metadata and changes no deal.
        assert await page.evaluate("LISTINGS.every(x => x.isOwnerVerified !== true)")
        assert await page.evaluate("LISTINGS.every(x => x.commissionVerified !== true)")
        await summary.click()
        assert not await safety.evaluate("(el) => el.open")
        await browser.close()


@pytest.mark.asyncio
async def test_safety_disclosure_follows_graphite_and_light_theme():
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        page=await browser.new_page(viewport={"width":390,"height":844},is_mobile=True,has_touch=True)
        await page.goto(URL,wait_until="domcontentloaded")
        await page.locator("#listViewContainer .kr-open-detail").first.click()
        for theme in ("dark","light"):
            await page.evaluate("(theme) => window.KyivRadarTheme.set(theme)",theme)
            assert await page.locator("html").get_attribute("data-kr-theme")==theme
            summary=page.locator("#krRentalSafety > summary")
            assert await summary.is_visible()
            css=await summary.evaluate("(el) => ({background:getComputedStyle(el.parentElement).backgroundColor,color:getComputedStyle(el).color, height:el.getBoundingClientRect().height})")
            assert css["height"] >= 44
            assert css["color"] != css["background"]
        await browser.close()
