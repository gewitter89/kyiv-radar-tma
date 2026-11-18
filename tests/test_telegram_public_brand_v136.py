# -*- coding: utf-8 -*-
"""Bot handle must never be part of the public Kyiv Radar user-facing UI.

The existing Telegram entry URL remains functional. No real Telegram messages
or API calls, and no credentials, are used in these tests.
"""
import os
import urllib.parse
from pathlib import Path
import pytest
from playwright.async_api import async_playwright

ROOT=Path(__file__).resolve().parents[1]
URL=(ROOT/"index.html").as_uri()
INIT="user=%7B%22id%22%3A12345%7D&auth_date=1700000000&hash=mockhash"
TG_URL=URL+"#tgWebAppData="+urllib.parse.quote(INIT)
OLD="@prostov_shrink_bot"


def test_old_handle_not_bundled_in_visible_app_messages_or_server_errors():
    html=(ROOT/"index.html").read_text(encoding="utf-8")
    api=(ROOT/"server/kyiv_radar_api.py").read_text(encoding="utf-8")
    guidance=(ROOT/"experience.js").read_text(encoding="utf-8")
    assert OLD not in html
    assert OLD not in api
    assert "Відкрити бота" not in guidance
    assert "чат із ботом" not in guidance
    # The existing Telegram bot URL is intentionally retained as a navigation
    # dependency; pretending to remove it would break contact handoff.
    assert 'const BOT_URL = "https://t.me/prostov_shrink_bot"' in guidance


@pytest.mark.asyncio
async def test_all_telegram_handoff_dialogs_use_app_brand_not_old_bot_name():
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True)
        page=await browser.new_page(viewport={"width":390,"height":844})
        await page.goto(URL,wait_until="domcontentloaded")
        await page.wait_for_function("typeof window.krContactHandoff === 'function'")
        for script in [
            "window.krContactHandoff(101, 'Синтетична квартира')",
            "window.krLandlordHandoff()",
            "window.krContactError('Сервіс тимчасово недоступний', 502)",
        ]:
            await page.evaluate(script)
            popup=page.locator("#krHandoff")
            await popup.wait_for(state="visible")
            text=await popup.inner_text()
            assert "Київ Радар" in text
            assert "prostov_shrink_bot" not in text
            assert "Відкрити бота" not in text
            link=popup.locator('a[href="https://t.me/prostov_shrink_bot"]')
            assert await link.count() == 1
            assert "Київ Радар" in await link.inner_text()
            await page.evaluate("document.querySelector('#krHandoff .kr-dialog-close').click()")
        await browser.close()


@pytest.mark.asyncio
async def test_legacy_backend_error_body_never_leaks_into_user_ui():
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True)
        page=await browser.new_page(viewport={"width":390,"height":844})
        calls=[]
        async def server(route):
            calls.append(route.request.post_data_json)
            await route.fulfill(
                status=502,content_type="application/json",
                headers={"access-control-allow-origin":"*"},
                body='{"detail":"Не вдалося доставити контакт у Telegram @prostov_shrink_bot"}')
        await page.route("**/api/send_contact",server)
        await page.goto(TG_URL,wait_until="domcontentloaded")
        await page.wait_for_function("typeof sendContactToBotChat === 'function' && LISTINGS.length > 0")
        await page.evaluate("""() => {
            const d=LISTINGS[0];
            d.source='Київ Радар';
            d.contactVerified=true;
            openDealModalById(d.id);
        }""")
        assert await page.locator("#modalCallBtn").is_visible()
        await page.locator("#modalCallBtn").click()
        popup=page.locator("#krHandoff")
        await popup.wait_for(state="visible")
        assert len(calls)==1
        assert "prostov_shrink_bot" not in await popup.inner_text()
        assert "простов" not in (await page.locator("#krContactStatus").inner_text()).casefold()
        assert "Київ Радар" in await popup.inner_text()
        await browser.close()
