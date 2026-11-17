# -*- coding: utf-8 -*-
"""Actual CSS readability of housing decisions in both Kyiv Signal themes."""
import os
import re
import pytest
from playwright.async_api import async_playwright

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
URL = "file:///" + os.path.join(ROOT, "index.html").replace("\\", "/")


def luminance(color):
    rgb = [int(v)/255. for v in re.findall(r"\d+", color)[:3]]
    channels = [v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4 for v in rgb]
    return .2126*channels[0]+.7152*channels[1]+.0722*channels[2]


def contrast(foreground, background):
    hi, lo = sorted([luminance(foreground),luminance(background)],reverse=True)
    return (hi+.05)/(lo+.05)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode",["dark","light"])
async def test_living_conditions_and_commission_are_readable_in_both_themes(mode):
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        page=await browser.new_page(viewport={"width":390,"height":844},is_mobile=True,has_touch=True)
        await page.goto(URL,wait_until="domcontentloaded")
        await page.locator("#listViewContainer .kr-open-detail").first.click()
        await page.evaluate("(value) => window.KyivRadarTheme.set(value)",mode)
        tiles=page.locator("#modalEquipment > div")
        assert await tiles.count()>=3
        for index in range(await tiles.count()):
            tile=tiles.nth(index)
            css=await tile.evaluate("""el => ({
                text:getComputedStyle(el.querySelector('span:not(.w-2)')).color,
                bg:getComputedStyle(el).backgroundColor,
                note:el.querySelector('small') ? getComputedStyle(el.querySelector('small')).color : null
            })""")
            assert contrast(css["text"],css["bg"])>=4.5, f"{mode} tile {index} poor text contrast"
            if css["note"]:
                assert contrast(css["note"],css["bg"])>=4.5, f"{mode} tile {index} poor note contrast"
        badge=page.locator("#modalCommissionBadge")
        info=await badge.evaluate("""el => ({
            text:getComputedStyle(el).color, bg:getComputedStyle(el).backgroundColor
        })""")
        assert contrast(info["text"],info["bg"])>=4.5
        assert await page.locator("#krRentalSafety > summary").is_visible()
        await browser.close()
