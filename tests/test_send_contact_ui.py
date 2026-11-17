# -*- coding: utf-8 -*-
"""
Kyiv Radar Send Contact Button UI Test Suite
Tests sendContactToBotChat() behavior in index.html:
1. Privacy: All public listings have phone=null (no raw phones leaked).
2. Browser mode with phone: Copies real phone number without fake fallbacks.
3. Browser mode without phone: Displays truthful "Номер не вказано в оголошенні" without fake "+380671112233".
4. Telegram mode with successful backend API (200 OK):
   Shows "✓ Контакт надіслано у ваш Telegram-чат!"
5. Telegram mode with failed backend API (502 / 401 error):
   Shows truthful error "⚠️ Не вдалося надіслати контакт: ..."
   NEVER masks the failure by silently copying phone to clipboard.
"""

import os
import json
import urllib.parse
import pytest
from playwright.async_api import async_playwright

INDEX_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "index.html"))
BASE_FILE_URL = "file:///" + INDEX_PATH.replace("\\", "/")

# Standard Telegram WebApp hash data string
RAW_INIT_DATA = "user=%7B%22id%22%3A12345%7D&auth_date=1700000000&hash=mockhash"
TG_HASH = "#tgWebAppData=" + urllib.parse.quote(RAW_INIT_DATA)
TG_FILE_URL = BASE_FILE_URL + TG_HASH

@pytest.mark.asyncio
async def test_public_catalog_privacy_protection():
    """Verify that public catalog in index.html contains ZERO unmasked raw phone numbers."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(BASE_FILE_URL)
        await page.wait_for_timeout(500)

        raw_phones_count = await page.evaluate("""() => {
            if (!LISTINGS || !Array.isArray(LISTINGS)) return -1;
            return LISTINGS.filter(d => d.phone !== null && d.phone !== undefined && d.phone !== '').length;
        }""")
        assert raw_phones_count == 0, f"Privacy leak: found {raw_phones_count} unmasked phone numbers in public catalog!"
        await browser.close()

@pytest.mark.asyncio
async def test_browser_mode_with_phone():
    """Outside Telegram: clicking 'У чат' on deal with phone copies real phone."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 390, "height": 844},
            permissions=["clipboard-read", "clipboard-write"]
        )
        page = await context.new_page()
        await page.goto(BASE_FILE_URL)
        await page.wait_for_timeout(1000)

        # Inject phone into deal #1 to test this branch
        await page.evaluate("""() => {
            if (LISTINGS && LISTINGS.length > 0) {
                LISTINGS[0].phone = "+380509998877";
                openDealModalById(LISTINGS[0].id);
            }
        }""")
        await page.wait_for_timeout(400)
        assert await page.is_visible("#dealModal")

        # Click "У чат" button
        await page.click("#modalChatBtn")
        await page.wait_for_timeout(400)

        # Verify toast content
        toast = await page.inner_text("#toastText")
        assert "скопійовано" in toast or "+380" in toast
        assert "+380671112233" not in toast, "Fake fallback phone MUST NOT be used!"

        await browser.close()

@pytest.mark.asyncio
async def test_browser_mode_without_phone():
    """Outside Telegram: default masked deal directs users to Telegram instead of leaking a number."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 390, "height": 844},
            permissions=["clipboard-read", "clipboard-write"]
        )
        page = await context.new_page()
        await page.goto(BASE_FILE_URL)
        await page.wait_for_timeout(1000)

        # Open deal #1 (already has phone = null)
        await page.locator("#listViewContainer .kr-open-detail").first.click()
        await page.wait_for_timeout(400)
        assert await page.is_visible("#dealModal")

        # Click "У чат" button
        await page.click("#modalCallBtn")
        await page.wait_for_timeout(400)

        dialog = page.get_by_role("dialog", name="Відкрийте квартиру в Telegram")
        assert await dialog.is_visible()
        content = await dialog.inner_text()
        assert "контакт захищено" in content.lower()
        assert await dialog.locator('a[href="https://t.me/prostov_shrink_bot"]').is_visible()
        assert "+380671112233" not in content, "Fake fallback phone MUST NOT be used!"

        await browser.close()

@pytest.mark.asyncio
async def test_telegram_mode_successful_delivery():
    """Inside Telegram WebApp: when API returns success, displays confirmation toast."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 390, "height": 844})
        page = await context.new_page()

        # Intercept backend /api/send_contact and return HTTP 200 success
        await page.route("**/api/send_contact", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"success": True, "dealId": 1, "message": "Контакт надіслано"})
        ))

        # Navigate using Telegram WebApp hash
        await page.goto(TG_FILE_URL)
        await page.wait_for_timeout(1000)

        await page.locator("#listViewContainer .kr-open-detail").first.click()
        await page.wait_for_timeout(500)

        await page.click("#modalCallBtn")
        await page.wait_for_timeout(500)

        toast = await page.inner_text("#toastText")
        assert "Контакт надіслано у ваш Telegram-чат" in toast, f"Unexpected toast: {toast}"

        await browser.close()

@pytest.mark.asyncio
async def test_telegram_mode_error_unmasked():
    """
    Inside Telegram WebApp: when API returns failure (e.g. 502 / 401),
    displays truthful error toast and DOES NOT silently mask it with clipboard copy.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 390, "height": 844})
        page = await context.new_page()

        # Intercept backend /api/send_contact and return HTTP 502 error
        await page.route("**/api/send_contact", lambda route: route.fulfill(
            status=502,
            content_type="application/json",
            body=json.dumps({"detail": "Запустіть бота @prostov_shrink_bot (/start)"})
        ))

        # Navigate using Telegram WebApp hash
        await page.goto(TG_FILE_URL)
        await page.wait_for_timeout(1000)

        await page.locator("#listViewContainer .kr-open-detail").first.click()
        await page.wait_for_timeout(500)

        await page.click("#modalCallBtn")
        await page.wait_for_timeout(500)

        dialog = page.get_by_role("dialog", name="Спробуйте ще раз через Telegram")
        assert await dialog.is_visible()
        content = await dialog.inner_text()
        assert "не вдалося отримати контакт" in content.lower()
        assert "@prostov_shrink_bot" in content or "Запустіть" in content
        assert "скопійовано" not in content, "Failure MUST NOT be masked by a false success!"

        await browser.close()


def test_social_share_metadata_is_truthful_and_complete():
    """The published preview must describe filters, not fabricate verification."""
    with open(INDEX_PATH, encoding="utf-8") as html:
        page = html.read()
    assert '<meta property="og:locale" content="uk_UA">' in page
    assert '<meta property="og:site_name" content="Київ Радар">' in page
    assert 'перевірка автономності при блекаутах' not in page
    assert 'заявленими можливостями автономності' in page
    assert os.path.isfile(os.path.join(os.path.dirname(INDEX_PATH), "og-preview.png"))
