# -*- coding: utf-8 -*-
"""Kyiv Signal theme identity regression: actual browser layout, readability, preference."""
import os
import re
import pytest
from playwright.async_api import async_playwright

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
URL = "file:///" + os.path.join(ROOT, "index.html").replace("\\", "/")


async def ready(page):
    await page.goto(URL, wait_until="domcontentloaded")
    await page.wait_for_selector("html.kr-unified-111[data-kr-theme]")
    await page.wait_for_selector(".kr-theme-option", state="attached")


def contrast_ratio(a, b):
    """WCAG luminance calculation for computed rgb() colors."""
    def luminance(rgb):
        values = [int(v) / 255 for v in re.findall(r"\d+", rgb)[:3]]
        channels = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values]
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
    la, lb = sorted([luminance(a), luminance(b)], reverse=True)
    return (la + 0.05) / (lb + 0.05)


@pytest.mark.asyncio
@pytest.mark.parametrize("width,height", [(320, 640), (390, 844), (768, 900)])
async def test_graphite_logo_is_single_source_and_decorative_wave_is_gone(width, height):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width":width, "height":height},
                                      is_mobile=width < 700, has_touch=width < 700)
        await ready(page)
        assert await page.locator("header .kr-native-seam").count() == 0
        assert await page.locator("#krHero .kr-ukraine-curve").count() == 0
        assert await page.locator(".kr-brand-mark img").count() == 1
        mark = page.locator(".kr-brand-mark img")
        assert (await mark.get_attribute("src")).endswith("kyiv-radar-mark.svg")
        assert await mark.evaluate("(img) => img.naturalWidth > 0")
        assert await page.locator("#krRadarSlot img.kr-radar-mini-mark").count() == 1
        assert await page.locator('#krHero .kr-kyiv-skyline svg').count() == 1
        # Brand image appears as a low-opacity watermark behind functional controls.
        assert "kyiv-radar-mark.svg" in await page.locator("body > header").evaluate(
            "(el) => getComputedStyle(el, '::after').backgroundImage"
        )
        assert await page.locator("#krHero").evaluate(
            "(el) => getComputedStyle(el, '::after').content"
        ) == "none"
        assert await page.locator("#searchInput").is_visible()
        assert await page.locator("#floatingViewToggle").is_visible()
        assert await page.locator("#krDataStatus").is_visible()
        assert await page.locator("#krSimpleInfo").is_visible()
        overflow = await page.evaluate(
            "() => Math.max(document.body.scrollWidth,document.documentElement.scrollWidth)-innerWidth"
        )
        assert overflow <= 4
        await browser.close()


@pytest.mark.asyncio
async def test_graphite_and_light_have_readable_main_header_and_status():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width":390,"height":844},
                                      is_mobile=True,has_touch=True)
        await ready(page)
        for theme, expected_bg, expected_header in [
            ("dark","rgb(16, 21, 29)","rgb(22, 30, 41)"),
            ("light","rgb(245, 247, 249)","rgb(237, 242, 247)")
        ]:
            assert await page.evaluate("(value) => window.KyivRadarTheme.set(value)",theme)
            assert await page.locator("html").get_attribute("data-kr-theme") == theme
            background = await page.locator("body").evaluate("(el) => getComputedStyle(el).backgroundColor")
            assert background == expected_bg
            head = page.locator("body > header")
            header_bg = await head.evaluate("(el) => getComputedStyle(el).backgroundColor")
            assert header_bg == expected_header
            heading_fg = await page.locator("#krHero h1").evaluate(
                "(el) => getComputedStyle(el).color"
            )
            assert contrast_ratio(heading_fg, header_bg) >= 4.5
            bar_bg = await page.locator("#krResultsBar").evaluate(
                "(el) => getComputedStyle(el).backgroundColor"
            )
            status_fg = await page.locator("#krDataStatus").evaluate(
                "(el) => getComputedStyle(el).color"
            )
            assert contrast_ratio(status_fg, bar_bg) >= 4.5
            assert await page.locator("meta[name='theme-color']").get_attribute("content") == (
                "#161E29" if theme == "dark" else "#EDF2F7"
            )
            assert await page.locator(".kr-brand-mark img").evaluate("(img) => img.naturalWidth > 0")
        await browser.close()


@pytest.mark.asyncio
async def test_theme_controls_persist_without_breaking_search_and_gallery():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width":390,"height":844},
                                            is_mobile=True,has_touch=True)
        page = await context.new_page()
        await ready(page)
        await page.locator("#krSimpleInfo").click()
        dialog = page.locator("#krSimpleHelp")
        assert await dialog.is_visible()
        await dialog.locator('.kr-theme-option[data-mode="light"]').click()
        assert await page.locator("html").get_attribute("data-kr-theme") == "light"
        assert await dialog.locator('.kr-theme-option[data-mode="light"]').get_attribute("aria-pressed") == "true"
        await dialog.get_by_role("button", name="Зрозуміло").click()
        await page.reload(wait_until="domcontentloaded")
        await page.wait_for_selector("html.kr-unified-111[data-kr-theme='light']")
        assert await page.evaluate("window.KyivRadarTheme.getMode()") == "light"
        assert await page.locator("#searchInput").is_visible()
        await page.locator("#searchInput").fill("Позняки")
        assert await page.locator("#searchInput").input_value() == "Позняки"
        assert await page.locator("#floatingViewToggle").is_visible()
        await context.close()
        await browser.close()


@pytest.mark.asyncio
async def test_auto_theme_can_follow_os_when_telegram_theme_unavailable():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width":390,"height":844},
                                      is_mobile=True,has_touch=True)
        await page.emulate_media(color_scheme="light")
        await ready(page)
        expected = await page.evaluate("""() => {
          const color = window.Telegram?.WebApp?.colorScheme;
          if (color === 'light' || color === 'dark') return color;
          return matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
        }""")
        await page.evaluate("window.KyivRadarTheme.set('auto')")
        assert await page.locator("html").get_attribute("data-kr-theme") == expected
        assert await page.evaluate("window.KyivRadarTheme.getMode()") == "auto"
        await browser.close()


@pytest.mark.asyncio
async def test_listing_photo_error_exposes_friendly_recoverable_fallback():
    """The main apartment image may fail remotely; never leave an unlabelled black box."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width":390,"height":844},
                                      is_mobile=True,has_touch=True)
        await ready(page)
        frame = page.locator("#listViewContainer > div[onclick]").first.locator(".relative.h-48")
        await frame.locator(".kr-gallery-fallback").wait_for()
        # Observe error/load handler effects synchronously, without an unrelated
        # network image event or live catalog re-render racing our assertions.
        error_state = await frame.evaluate("""el => {
          el.querySelector('.kr-gallery-image').dispatchEvent(new Event('error'));
          return {
            missing: el.classList.contains('kr-gallery-missing'),
            text: el.querySelector('.kr-gallery-fallback').textContent
          };
        }""")
        assert error_state["missing"]
        assert "тимчасово недоступне" in error_state["text"]
        assert await frame.locator(".kr-gallery-next").is_visible()
        await frame.locator(".kr-gallery-next").click()
        assert "1/" not in (await frame.locator(".kr-gallery-count").inner_text())
        recovered = await frame.evaluate("""el => {
          el.querySelector('.kr-gallery-image').dispatchEvent(new Event('load'));
          return !el.classList.contains('kr-gallery-missing');
        }""")
        assert recovered
        await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("width,height", [(320, 640), (390, 844)])
async def test_native_telegram_title_bar_exactly_matches_web_header_in_both_themes(width, height):
    """A Telegram native title bar is solid. Its paint must equal the first HTML surface."""
    from pathlib import Path

    index = Path(ROOT, "index.html").read_text(encoding="utf-8")
    assert '<meta name="theme-color" content="#161E29">' in index
    assert 'bg-[#161E29]' in index  # no black first-frame navbar flash
    assert "h-[2.5px]" not in index  # no obsolete stripe at the border

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": width, "height": height},
                                      is_mobile=True, has_touch=True)
        await ready(page)
        # Observe SDK calls without contacting Telegram or sending anything.
        await page.evaluate("""() => {
          window.__krNativeColors = [];
          window.Telegram = window.Telegram || {};
          window.Telegram.WebApp = window.Telegram.WebApp || {};
          window.Telegram.WebApp.setHeaderColor =
             color => window.__krNativeColors.push(color);
          window.Telegram.WebApp.setBackgroundColor = () => {};
        }""")
        for mode, color, css_rgb in [
            ("dark", "#161E29", "rgb(22, 30, 41)"),
            ("light", "#EDF2F7", "rgb(237, 242, 247)")
        ]:
            await page.evaluate("(theme) => window.KyivRadarTheme.set(theme)", mode)
            status = await page.evaluate("""() => {
              const html = document.documentElement;
              const header = document.querySelector('body > header');
              return {
                native: window.KyivRadarTheme.nativeColors().header,
                cssToken: getComputedStyle(html).getPropertyValue('--kr-header').trim(),
                webHeader: getComputedStyle(header).backgroundColor,
                meta: document.querySelector('meta[name="theme-color"]').content,
                sdkCalls: window.__krNativeColors,
                stripe: Boolean(document.body.firstElementChild?.classList.contains("h-[2.5px]"))
              };
            }""")
            assert status["native"] == color
            assert status["cssToken"] == color
            assert status["meta"] == color
            assert status["webHeader"] == css_rgb
            assert status["sdkCalls"][-1] == color
            assert status["stripe"] is False
        # The navbar background is a single opaque surface with no border/shadow seam.
        border = await page.locator("body > header").evaluate(
            "(el) => ({bottom: getComputedStyle(el).borderBottomWidth, shadow: getComputedStyle(el).boxShadow})"
        )
        assert border["bottom"] == "0px"
        assert border["shadow"] == "none"
        await browser.close()
