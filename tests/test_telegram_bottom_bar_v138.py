# -*- coding: utf-8 -*-
"""Native Telegram bottom-bar regression, isolated from any real Telegram session."""
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
URL = (ROOT / "index.html").as_uri()

MOCK = r"""(() => {
  window.__colors = {header: [], background: [], bottom: []};
  window.Telegram = {WebApp: {
    platform: 'android', initData: 'mock-only', colorScheme: 'dark',
    ready() {}, expand() {}, onEvent() {},
    setHeaderColor(c) { window.__colors.header.push(c); },
    setBackgroundColor(c) { window.__colors.background.push(c); },
    setBottomBarColor(c) { window.__colors.bottom.push(c); }
  }};
})()"""


@pytest.mark.asyncio
async def test_native_bottom_bar_is_old_kyiv_blue_and_follows_theme():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(
            viewport={"width": 390, "height": 844},
            is_mobile=True,
            has_touch=True,
        )
        await page.route("https://telegram.org/js/telegram-web-app.js", lambda route: route.abort())
        await page.add_init_script(MOCK)
        await page.goto(URL, wait_until="domcontentloaded")
        await page.wait_for_function("!!window.KyivRadarTheme")
        await page.evaluate("KyivRadarTheme.apply()")
        assert await page.evaluate("window.__colors.bottom.at(-1)") == "#0E2037"
        assert await page.evaluate("window.__colors.header.at(-1)") == "#161E29"
        await page.evaluate("KyivRadarTheme.set('light')")
        assert await page.evaluate("window.__colors.bottom.at(-1)") == "#EDF2F7"
        await page.evaluate("KyivRadarTheme.set('dark')")
        assert await page.evaluate("window.__colors.bottom.at(-1)") == "#0E2037"
        assert await page.locator("#krSimpleInfo").is_visible()
        await browser.close()


@pytest.mark.asyncio
async def test_no_bottom_bar_sdk_on_regular_web_browser_does_not_break_page():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        await page.goto(URL, wait_until="domcontentloaded")
        await page.wait_for_function("!!window.KyivRadarTheme")
        assert await page.evaluate("KyivRadarTheme.set('dark')") is True
        assert await page.locator("#krSimpleInfo").is_visible()
        await browser.close()


def test_legacy_bot_handle_is_not_exposed_in_public_html():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "@prostov_shrink_bot" not in html
    assert "kyiv-signal-theme.js?v=1.38.0" in html
