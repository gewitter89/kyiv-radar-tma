# -*- coding: utf-8 -*-
"""Telegram full-screen launch regression — only simulated native WebApp API.

A native Telegram label is NOT DOM and cannot be suppressed by CSS. The tests
verify a safe API request, event-confirmed CSS state, viewport inset, manual
fallback and continued operation on unsupported clients.
"""
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

URL = (Path(__file__).resolve().parents[1] / "index.html").as_uri()
MOCK = r"""() => {
  const handlers = {};
  window.__nativeEvents = handlers;
  window.__fullRequests = 0;
  window.__fullExits = 0;
  window.__closeCalls = 0;
  window.__swipeDisables = 0;
  window.__swipeEnables = 0;
  window.Telegram = {WebApp: {
    platform: 'android', initData: 'synthetic-test-init-only',
    isFullscreen: false,
    ready() {}, expand() {},
    setHeaderColor() {}, setBackgroundColor() {},
    onEvent(name, listener) { handlers[name] = listener; },
    requestFullscreen() {
      window.__fullRequests++;
      // Telegram confirms actual fullscreen asynchronously, not here.
    },
    close() { window.__closeCalls++; },
    disableVerticalSwipes() { window.__swipeDisables++; },
    enableVerticalSwipes() { window.__swipeEnables++; },
    exitFullscreen() {
      window.__fullExits++;
      this.isFullscreen = false;
      handlers.fullscreenChanged?.();
    }
  }};
}"""


@pytest.mark.asyncio
async def test_fullscreen_only_after_native_confirmation_and_respects_insets():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width":390,"height":844},is_mobile=True,has_touch=True)
        await page.route("https://telegram.org/js/telegram-web-app.js",lambda route: route.abort())
        await page.add_init_script(f'({MOCK})()')
        await page.goto(URL, wait_until="domcontentloaded")
        await page.wait_for_function("!!window.KyivRadarTelegramShell")
        assert await page.evaluate("__fullRequests") == 1
        assert not await page.evaluate(
            "document.documentElement.classList.contains('kr-telegram-fullscreen')")
        await page.evaluate("""() => {
            document.documentElement.style.setProperty('--tg-content-safe-area-inset-top','62px');
            Telegram.WebApp.isFullscreen = true;
            __nativeEvents.fullscreenChanged();
        }""")
        assert await page.evaluate(
            "document.documentElement.classList.contains('kr-telegram-fullscreen')")
        top = await page.evaluate("getComputedStyle(document.body).paddingTop")
        assert top == "62px"
        head_y = await page.locator("body > header").evaluate(
            "element => element.getBoundingClientRect().top")
        assert head_y >= 61
        assert await page.locator("body > header").is_visible()
        await browser.close()


@pytest.mark.asyncio
async def test_manual_exit_works_and_respects_user_preference_on_reopen():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.route("https://telegram.org/js/telegram-web-app.js",lambda route: route.abort())
        await page.add_init_script(f'({MOCK})()')
        await page.goto(URL,wait_until="domcontentloaded")
        await page.wait_for_function("document.querySelector('#krSimpleInfo') !== null")
        await page.evaluate("""() => {
            Telegram.WebApp.isFullscreen = true;
            __nativeEvents.fullscreenChanged();
        }""")
        await page.locator("#krSimpleInfo").click()
        button=page.locator("#krTelegramFullscreenToggle")
        assert await button.is_visible()
        assert await button.get_attribute("aria-pressed") == "true"
        await button.click()
        assert await page.evaluate("__fullExits") == 1
        assert await page.evaluate(
            "localStorage.getItem('kr_tg_fullscreen_choice_v1')") == "off"
        assert not await page.evaluate(
            "document.documentElement.classList.contains('kr-telegram-fullscreen')")
        await page.reload(wait_until="domcontentloaded")
        await page.wait_for_function("!!window.KyivRadarTelegramShell")
        assert await page.evaluate("__fullRequests") == 0
        await page.locator("#krSimpleInfo").click()
        button=page.locator("#krTelegramFullscreenToggle")
        assert "Відкрити на весь екран" in await button.inner_text()
        await button.click()
        assert await page.evaluate("__fullRequests") == 1
        assert await page.evaluate(
            "localStorage.getItem('kr_tg_fullscreen_choice_v1')") == "on"
        await browser.close()


@pytest.mark.asyncio
async def test_unsupported_telegram_does_not_change_layout():
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True)
        page=await browser.new_page(viewport={"width":390,"height":844})
        await page.route("https://telegram.org/js/telegram-web-app.js",lambda route: route.abort())
        await page.add_init_script("""(() => {
            window.Telegram={WebApp:{
               initData:'', platform:'web', requestFullscreen(){throw Error('unsupported');},
               ready(){}, expand(){}, onEvent(){} }};
        })()""")
        await page.goto(URL, wait_until="domcontentloaded")
        await page.wait_for_function("!!window.KyivRadarTelegramShell")
        assert await page.evaluate("KyivRadarTelegramShell.supported") is False
        assert await page.evaluate(
            "document.documentElement.classList.contains('kr-telegram-fullscreen')") is False
        await page.locator("#krSimpleInfo").click()
        assert await page.locator("#krTelegramFullscreenToggle").count() == 0
        assert await page.locator("#krSimpleHelp").is_visible()
        await browser.close()


@pytest.mark.asyncio
async def test_native_request_failure_leaves_normal_view_usable():
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True)
        page=await browser.new_page(viewport={"width":390,"height":844})
        await page.route("https://telegram.org/js/telegram-web-app.js",lambda route: route.abort())
        await page.add_init_script("""(() => {
           window.Telegram={WebApp:{
             initData:'synthetic', platform:'ios', isFullscreen:false,
             ready(){},expand(){},onEvent(){},
             requestFullscreen(){throw Error('native unsupported');}
           }};
        })()""")
        await page.goto(URL, wait_until="domcontentloaded")
        await page.wait_for_function("!!window.KyivRadarTelegramShell")
        assert await page.evaluate(
            "document.documentElement.classList.contains('kr-telegram-fullscreen')") is False
        await page.locator("#krSimpleInfo").click()
        assert await page.locator("#krTelegramFullscreenToggle").is_visible()
        assert await page.locator("#krSimpleHelp").is_visible()
        assert await page.locator("#krHero").is_visible()
        await browser.close()


@pytest.mark.asyncio
async def test_close_completely_calls_real_native_webapp_close_not_minimize():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width":390,"height":844},is_mobile=True,has_touch=True)
        await page.route("https://telegram.org/js/telegram-web-app.js",lambda route: route.abort())
        await page.add_init_script(f'({MOCK})()')
        await page.goto(URL,wait_until="domcontentloaded")
        await page.wait_for_function("document.querySelector('#krSimpleInfo') !== null")
        assert await page.evaluate("KyivRadarTelegramShell.canClose") is True
        await page.locator("#krSimpleInfo").click()
        btn=page.locator("#krTelegramCloseCompletely")
        assert await btn.is_visible()
        assert "Закрити застосунок повністю" in await btn.inner_text()
        assert await page.evaluate("__closeCalls") == 0
        await btn.click()
        # Native bridge is stubbed; a real Telegram client closes the Mini App.
        assert await page.evaluate("__closeCalls") == 1
        assert await page.evaluate("__fullExits") == 0
        await browser.close()


@pytest.mark.asyncio
async def test_close_action_not_exposed_to_an_ordinary_browser():
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True)
        page=await browser.new_page(viewport={"width":390,"height":844})
        await page.goto(URL,wait_until="domcontentloaded")
        await page.wait_for_function("document.querySelector('#krSimpleInfo') !== null")
        await page.locator("#krSimpleInfo").click()
        assert await page.locator("#krTelegramCloseCompletely").count() == 0
        await browser.close()


@pytest.mark.asyncio
async def test_vertical_content_swipes_disabled_to_prevent_native_minimize_bar():
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True)
        page=await browser.new_page(viewport={"width":390,"height":844},is_mobile=True,has_touch=True)
        await page.route("https://telegram.org/js/telegram-web-app.js",
                         lambda route: route.abort())
        await page.add_init_script(f'({MOCK})()')
        await page.goto(URL,wait_until="domcontentloaded")
        await page.wait_for_function("!!window.KyivRadarTelegramShell")
        assert await page.evaluate("KyivRadarTelegramShell.swipeControl") is True
        assert await page.evaluate("__swipeDisables") == 1
        assert await page.evaluate("__swipeEnables") == 0
        await page.locator("#krSimpleInfo").click()
        control=page.locator("#krTelegramMinimizeSwipeToggle")
        assert await control.is_visible()
        assert await control.get_attribute("aria-pressed") == "true"
        # Deliberate opt-out: let user swipe to minimize using webview area.
        await control.click()
        assert await page.evaluate("__swipeEnables") == 1
        assert await control.get_attribute("aria-pressed") == "false"
        assert await page.evaluate(
            "localStorage.getItem('kr_tg_prevent_unintentional_minimize_v1')") == "off"
        await page.reload(wait_until="domcontentloaded")
        await page.wait_for_function("!!window.KyivRadarTelegramShell")
        assert await page.evaluate("__swipeDisables") == 0
        assert await page.evaluate("__swipeEnables") == 1
        await page.locator("#krSimpleInfo").click()
        await page.locator("#krTelegramMinimizeSwipeToggle").click()
        assert await page.evaluate("__swipeDisables") == 1
        assert await page.evaluate(
            "localStorage.getItem('kr_tg_prevent_unintentional_minimize_v1')") == "on"
        await browser.close()


@pytest.mark.asyncio
async def test_no_swipe_control_in_non_telegram_browser():
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True)
        page=await browser.new_page(viewport={"width":390,"height":844})
        await page.goto(URL,wait_until="domcontentloaded")
        await page.wait_for_function("!!window.KyivRadarTelegramShell")
        assert await page.evaluate("KyivRadarTelegramShell.swipeControl") is False
        await page.locator("#krSimpleInfo").click()
        assert await page.locator("#krTelegramMinimizeSwipeToggle").count() == 0
        await browser.close()


@pytest.mark.asyncio
async def test_native_telegram_keyboard_launch_with_empty_init_data_keeps_swipe_protection():
    # Official Telegram keyboard-button and inline launches may have empty initData.
    # This is a UX-only native bridge; it must not be tied to authentication data.
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(
            viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True
        )
        await page.route(
            "https://telegram.org/js/telegram-web-app.js",
            lambda route: route.abort(),
        )
        empty_init_mock = MOCK.replace(
            "initData: 'synthetic-test-init-only'", "initData: ''"
        )
        await page.add_init_script(f"({empty_init_mock})()")
        await page.goto(URL, wait_until="domcontentloaded")
        await page.wait_for_function("!!window.KyivRadarTelegramShell")
        assert await page.evaluate("KyivRadarTelegramShell.supported") is True
        assert await page.evaluate("KyivRadarTelegramShell.swipeControl") is True
        assert await page.evaluate("KyivRadarTelegramShell.canClose") is True
        assert await page.evaluate("__swipeDisables") == 1
        assert await page.evaluate("__fullRequests") == 1
        await page.locator("#krSimpleInfo").click()
        assert await page.locator("#krTelegramCloseCompletely").is_visible()
        assert await page.locator("#krTelegramMinimizeSwipeToggle").is_visible()
        await browser.close()


@pytest.mark.asyncio
async def test_fake_mobile_platform_without_native_ready_does_not_enable_bridge():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        await page.route(
            "https://telegram.org/js/telegram-web-app.js",
            lambda route: route.abort(),
        )
        await page.add_init_script("""(() => {
            window.Telegram = {WebApp: {
                platform: 'android', initData: '', requestFullscreen() {},
                close() {}, disableVerticalSwipes() {}, enableVerticalSwipes() {}
            }};
        })()""")
        await page.goto(URL, wait_until="domcontentloaded")
        await page.wait_for_function("!!window.KyivRadarTelegramShell")
        assert await page.evaluate("KyivRadarTelegramShell.swipeControl") is False
        assert await page.evaluate("KyivRadarTelegramShell.canClose") is False
        assert await page.evaluate("KyivRadarTelegramShell.supported") is False
        await browser.close()
