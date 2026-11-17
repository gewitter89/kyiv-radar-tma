# -*- coding: utf-8 -*-
"""v1.15 tenant journey: truthful progress, once-only request, scroll and recovery."""
import asyncio
import json
import os
import urllib.parse

import pytest
from playwright.async_api import async_playwright

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
URL = "file:///" + os.path.join(ROOT, "index.html").replace("\\", "/")
INIT = "user=%7B%22id%22%3A12345%7D&auth_date=1700000000&hash=mockhash"
TELEGRAM_URL = URL + "#tgWebAppData=" + urllib.parse.quote(INIT)


async def ready(page, telegram=False):
    await page.goto(TELEGRAM_URL if telegram else URL, wait_until="domcontentloaded")
    await page.wait_for_selector("#listViewContainer .kr-open-detail")
    # Isolated verified-contact fixture: does not write to any production dataset.
    # Contact endpoint tests must not impersonate unverified OLX/DIM.RIA cards.
    await page.evaluate("""() => {
        const fixture = getFilteredListings()[0];
        fixture.source = 'Київ Радар';
        fixture.contactVerified = true;
        renderAll();
    }""")
    await page.locator("#listViewContainer .kr-open-detail").first.click()
    await page.wait_for_selector("#dealModal:not(.hidden)")
    assert await page.locator("#dealModal").get_attribute("aria-modal") == "true"
    assert await page.locator("#krDealScroll").is_visible()


@pytest.mark.asyncio
async def test_one_slow_telegram_request_disables_duplicate_calls_and_recovers():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width":390,"height":844},
                                      is_mobile=True,has_touch=True)
        requests = []
        started = asyncio.Event()
        unblock = asyncio.Event()

        async def handler(route):
            requests.append(route.request.post_data_json)
            started.set()
            await unblock.wait()
            await route.fulfill(status=200, content_type="application/json",
                                body=json.dumps({"success":True,"dealId":1}))

        await page.route("**/api/send_contact", handler)
        await ready(page, telegram=True)
        await page.evaluate("() => {sendContactToBotChat(); sendContactToBotChat();}")
        await asyncio.wait_for(started.wait(), timeout=6)
        assert await page.locator("#modalCallBtn").is_disabled()
        assert await page.locator("#modalCallBtn").get_attribute("aria-busy") == "true"
        status = page.locator("#krContactStatus")
        assert await status.get_attribute("data-state") == "pending"
        assert "Надсилаємо" in await status.inner_text()
        geometry = await page.evaluate("""() => {
          const status=document.querySelector('#krContactStatus').getBoundingClientRect();
          const action=document.querySelector('#krDealActionBar').getBoundingClientRect();
          return {statusBottom:status.bottom,actionTop:action.top};
        }""")
        assert geometry["statusBottom"] <= geometry["actionTop"] + 1
        assert geometry["statusBottom"] > geometry["actionTop"] - 100
        assert len(requests) == 1
        # Even a direct helper call must be idempotent while in flight.
        await page.evaluate("sendContactToBotChat()")
        assert len(requests) == 1
        unblock.set()
        await page.wait_for_function("""() => document.querySelector('#krContactStatus').dataset.state === 'success'""")
        assert await page.locator("#modalCallBtn").is_enabled()
        assert "Перевірте приватний чат" in await status.inner_text()
        assert len(requests) == 1
        await browser.close()


@pytest.mark.asyncio
async def test_telegram_error_is_not_success_and_button_can_retry():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width":390,"height":844},
                                      is_mobile=True,has_touch=True)
        counter = []
        async def handler(route):
            counter.append(1)
            await route.fulfill(status=502, content_type="application/json",
                                body=json.dumps({"detail":"Запустіть бота /start"}))
        await page.route("**/api/send_contact", handler)
        await ready(page, telegram=True)
        await page.locator("#modalCallBtn").click()
        await page.wait_for_function("""() => document.querySelector('#krContactStatus').dataset.state === 'error'""")
        status = page.locator("#krContactStatus")
        assert "Не вдалося" in await status.inner_text()
        assert "надіслано" not in (await status.inner_text()).lower()
        assert await page.locator("#modalCallBtn").is_enabled()
        assert len(counter) == 1
        await browser.close()


@pytest.mark.asyncio
async def test_opening_another_apartment_clears_previous_contact_feedback():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width":390,"height":844},
                                      is_mobile=True,has_touch=True)
        await page.route("**/api/send_contact", lambda route: route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({"success":True})))
        await ready(page, telegram=True)
        await page.locator("#modalCallBtn").click()
        await page.wait_for_function("""() => document.querySelector('#krContactStatus').dataset.state === 'success'""")
        await page.evaluate("""() => {
          const next=LISTINGS.find(x => x.id !== currentModalDeal.id);
          if (!next) throw new Error('Insufficient listings');
          openDealModalById(next.id);
        }""")
        assert await page.locator("#krContactStatus").is_hidden()
        assert await page.locator("#modalCallBtn").is_enabled()
        await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("width,height",[(320,480),(390,650)])
async def test_detail_sheet_is_scrollable_and_bottom_action_stays_reachable(width,height):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width":width,"height":height},
                                      is_mobile=True,has_touch=True)
        await ready(page)
        scroll = page.locator("#krDealScroll")
        layout = await scroll.evaluate("""el => ({
          height:el.clientHeight, content:el.scrollHeight,
          overflow:getComputedStyle(el).overflowY
        })""")
        assert layout["content"] > layout["height"] + 60
        assert layout["overflow"] == "auto"
        await scroll.evaluate("(el) => el.scrollTop = el.scrollHeight")
        assert await scroll.evaluate("(el) => el.scrollTop") > 50
        call = await page.locator("#modalCallBtn").bounding_box()
        assert call is not None
        assert call["height"] >= 44
        assert call["y"] >= -1 and call["y"] + call["height"] <= height + 3
        assert await page.get_by_role("button",name="Закрити деталі квартири").is_visible()
        assert await page.locator("#modalOriginalLink").count() == 1
        overflow = await page.evaluate(
            "() => Math.max(document.body.scrollWidth,document.documentElement.scrollWidth) - innerWidth"
        )
        assert overflow <= 4
        await browser.close()


@pytest.mark.asyncio
async def test_contact_handoff_outside_telegram_does_not_pretend_to_send():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width":390,"height":844})
        await ready(page)
        assert await page.locator("#krContactStatus").is_hidden()
        await page.locator("#modalCallBtn").click()
        assert await page.locator("#krContactStatus").get_attribute("data-state") == "info"
        assert "лише в Telegram" in await page.locator("#krContactStatus").inner_text()
        assert await page.get_by_role("dialog", name="Відкрийте квартиру в Telegram").is_visible()
        await browser.close()


@pytest.mark.asyncio
async def test_switching_apartment_during_pending_request_clears_stale_progress():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width":390,"height":844},
                                      is_mobile=True,has_touch=True)
        started, unblock = asyncio.Event(), asyncio.Event()

        async def handler(route):
            started.set()
            await unblock.wait()
            await route.fulfill(status=200,content_type="application/json",
                                body=json.dumps({"success":True}))

        await page.route("**/api/send_contact",handler)
        await ready(page,telegram=True)
        first_id = await page.evaluate("currentModalDeal.id")
        await page.evaluate("() => {sendContactToBotChat();}")
        await asyncio.wait_for(started.wait(),timeout=6)
        await page.evaluate("""() => {
          const other=LISTINGS.find(x => x.id!==currentModalDeal.id);
          if (!other) throw new Error('Need two listings');
          openDealModalById(other.id);
        }""")
        assert await page.evaluate("currentModalDeal.id") != first_id
        assert "попередній" in (await page.locator("#krContactStatus").inner_text()).lower()
        unblock.set()
        await page.wait_for_function("contactRequestPending === false")
        assert await page.locator("#krContactStatus").is_hidden()
        assert await page.locator("#modalCallBtn").is_enabled()
        await browser.close()
