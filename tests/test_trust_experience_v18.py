# -*- coding: utf-8 -*-
"""Real browser regression checks for trust labels and complaint recovery."""
import os
import pytest
from playwright.async_api import async_playwright

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
URL = "file:///" + os.path.join(ROOT, "index.html").replace("\\", "/")


async def app_ready(page):
    await page.route("**/api/deals*", lambda route: route.abort())
    await page.goto(URL, wait_until="domcontentloaded")
    await page.wait_for_selector("#krHero")
    await page.wait_for_function("LISTINGS.length > 0 && typeof openDealModalById === 'function'")


@pytest.mark.asyncio
async def test_imported_listing_does_not_gain_false_verification_in_modal():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        await app_ready(page)
        await page.evaluate("""() => {
            const d = LISTINGS.find(x => x.source === 'DOM.RIA');
            d.actualityConfirmed = true;
            d.verifiedAt = new Date().toISOString();
            d.reviewedByRadar = false;
            openDealModalById(d.id);
        }""")
        assert await page.locator("#dealModal").is_visible()
        assert "Наявність не перевірена" in await page.locator("#modalVerifiedDate").inner_text()
        assert await page.locator("#modalVerificationTag").inner_text() == "Не перевірено"
        assert "Оголошення з DOM.RIA" in await page.locator("#modalSourceDetails").inner_text()
        assert await page.locator("#modalOriginalLink").is_visible()
        assert "evidence_ref" not in await page.locator("#modalSourceDetails").inner_text()
        await browser.close()


@pytest.mark.asyncio
async def test_only_fresh_explicit_evidence_label_shows_confirmation():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await app_ready(page)
        await page.evaluate("""() => {
            const d = LISTINGS.find(x => x.source === 'OLX');
            d.actualityConfirmed = true;
            d.reviewedByRadar = true;
            d.verifiedAt = new Date().toISOString();
            openDealModalById(d.id);
        }""")
        assert "Наявність перевірено" in await page.locator("#modalVerifiedDate").inner_text()
        assert await page.locator("#modalVerificationTag").inner_text() == "Перевірено"
        await page.evaluate("""() => {
            const d = currentModalDeal;
            d.verifiedAt = '2020-01-01T12:00:00Z';
            openDealModalById(d.id);
        }""")
        assert "Наявність не перевірена" in await page.locator("#modalVerifiedDate").inner_text()
        await browser.close()


@pytest.mark.asyncio
async def test_report_failure_keeps_dialog_open_and_retry_works():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        await app_ready(page)
        await page.evaluate("() => openDealModalById(LISTINGS[0].id)")
        await page.evaluate("() => openReportModal()")
        assert await page.locator("#reportModal").is_visible()
        calls = {"n": 0}

        async def answer(route):
            calls["n"] += 1
            if calls["n"] == 1:
                await route.fulfill(
                    status=503, content_type="application/json",
                    headers={"access-control-allow-origin": "*"},
                    body='{"detail":"Сервер тимчасово недоступний"}')
            else:
                await route.fulfill(
                    status=200, content_type="application/json",
                    headers={"access-control-allow-origin": "*"},
                    body='{"success":true,"id":31}')

        await page.route("**/api/reports", answer)
        button = page.locator("#reportModal button[onclick^='submitReport']").first
        await button.click()
        await page.wait_for_function(
            "() => document.getElementById('krReportStatus').textContent.includes('тимчасово')"
        )
        assert await page.locator("#reportModal").is_visible()
        assert await button.is_enabled()
        await button.click()
        await page.wait_for_function("() => document.getElementById('reportModal').classList.contains('hidden')")
        assert calls["n"] == 2
        await browser.close()


@pytest.mark.asyncio
async def test_report_reasons_have_clear_specific_choices():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        await app_ready(page)
        await page.evaluate("() => openReportModal()")
        text = await page.locator("#reportModal").inner_text()
        assert "Неправильні дані про світло або інтернет" in text
        assert "Фото або дані використали без дозволу" in text
        assert "вимагають 50%" not in text
        assert await page.locator("#krReportStatus").get_attribute("role") == "status"
        assert await page.locator("#reportModal button[onclick^='submitReport']").count() == 7
        await browser.close()


@pytest.mark.asyncio
async def test_server_empty_result_does_not_resurrect_stale_static_catalog():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        await page.route("**/api/deals*", lambda route: route.fulfill(
            status=200, content_type="application/json",
            headers={"access-control-allow-origin": "*"},
            body='{"success":true,"count":0,"deals":[]}'))
        await page.goto(URL, wait_until="domcontentloaded")
        await page.wait_for_function(
            "() => window.KR_CATALOG_MODE === 'live' && LISTINGS.length === 0"
        )
        assert await page.locator("#listViewContainer > div[onclick]").count() == 0
        assert "немає доступних оголошень" in await page.locator("#listViewContainer").inner_text()
        await browser.close()
