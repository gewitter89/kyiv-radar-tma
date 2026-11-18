# -*- coding: utf-8 -*-
"""Real Chromium regressions for the evidence-specific listing passport.

All records are disposable synthetic CI fixtures. No real broker/landlord
contacts, OLX pages, production complaints or paid API access.
"""
import json
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

URL = (Path(__file__).resolve().parents[1] / "index.html").as_uri()


async def ready(page):
    await page.route("**/api/deals*", lambda route: route.abort())
    await page.goto(URL, wait_until="domcontentloaded")
    await page.wait_for_function(
        "LISTINGS.length > 2 && !!window.KRListingPassport && "
        "typeof openDealModalById === 'function'")
    await page.evaluate("setViewMode('list')")


async def open_passport(page):
    await page.evaluate("() => openDealModalById(LISTINGS[0].id)")
    passport = page.locator("#krListingPassport")
    await passport.locator("summary").click()
    return passport


@pytest.mark.asyncio
async def test_unreviewed_import_does_not_become_verified_from_one_boolean():
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True)
        page=await browser.new_page(viewport={"width":390,"height":844},is_mobile=True,has_touch=True)
        await ready(page)
        await page.evaluate("""() => {
          LISTINGS[0].actualityConfirmed=true;
          LISTINGS[0].reviewedByRadar=false;
          LISTINGS[0].verifiedAt=new Date().toISOString();
        }""")
        passport=await open_passport(page)
        assert await passport.get_by_text("Характеристики ще не підтверджено").is_visible()
        assert await passport.get_by_text("Не підтверджена",exact=True).count() >= 1
        assert await passport.get_by_text("Дані частково перевірено").count() == 0
        assert await passport.locator(".kr-passport-row").count() == 9
        await browser.close()


@pytest.mark.asyncio
async def test_only_current_independent_availability_review_gets_timestamp():
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True)
        page=await browser.new_page(viewport={"width":390,"height":844})
        await ready(page)
        await page.evaluate("""() => {
          const d=LISTINGS[0];
          d.actualityConfirmed=true;
          d.reviewedByRadar=true;
          d.verifiedAt=new Date().toISOString();
        }""")
        passport=await open_passport(page)
        assert await passport.get_by_text("Дані частково перевірено").is_visible()
        availability=passport.locator(".kr-passport-row").filter(
            has=passport.locator("dt.kr-passport-label").get_by_text("Наявність", exact=True))
        assert "Перевіряли" in await availability.inner_text()
        # Availability review must NOT certify independent room/price/ownership.
        room=passport.locator(".kr-passport-row").filter(has_text="Кімнатність")
        assert "відповідність сторінці джерела" in await room.inner_text()
        await page.evaluate("""() => {
          LISTINGS[0].verifiedAt="2020-01-01T10:00:00Z";
          openDealModalById(LISTINGS[0].id);
        }""")
        passport=page.locator("#krListingPassport")
        await passport.locator("summary").click()
        availability=passport.locator(".kr-passport-row").filter(
            has=passport.locator("dt.kr-passport-label").get_by_text("Наявність", exact=True))
        assert "Не підтверджена" in await availability.inner_text()
        await browser.close()


@pytest.mark.asyncio
async def test_conflicting_room_data_is_marked_without_showing_wrong_count():
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True)
        page=await browser.new_page(viewport={"width":320,"height":700},is_mobile=True,has_touch=True)
        await ready(page)
        await page.evaluate("""() => {
          const d=LISTINGS[0];
          d.roomConflict=true;
          d.rooms=null;
        }""")
        passport=await open_passport(page)
        assert await passport.get_by_text("Є розбіжності — уточніть характеристики").is_visible()
        rows=passport.locator(".kr-passport-row")
        room=rows.filter(has_text="Кімнатність")
        assert "Є суперечність" in await room.inner_text()
        assert "Кількість кімнат не узгоджується" in await room.inner_text()
        # A narrow viewport must not overflow horizontally.
        coords=await passport.evaluate("""el => {
          const a=el.getBoundingClientRect();
          return {left:a.left,right:a.right,viewport:document.documentElement.clientWidth};
        }""")
        assert coords["left"] >= -2
        assert coords["right"] <= coords["viewport"] + 2
        await browser.close()


@pytest.mark.asyncio
async def test_passport_escapes_untrusted_source_and_never_inserts_html():
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True)
        page=await browser.new_page()
        await ready(page)
        await page.evaluate("""() => {
          LISTINGS[0].source='<img src=x onerror="window.passportPwned=1">';
        }""")
        passport=await open_passport(page)
        assert await passport.locator("img").count() == 0
        assert await passport.get_by_text("<img src=x onerror=", exact=False).count() >= 1
        assert await page.evaluate("typeof window.passportPwned") == "undefined"
        await browser.close()


@pytest.mark.asyncio
async def test_report_room_mismatch_includes_optional_explanation_and_clears_success():
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True)
        page=await browser.new_page(viewport={"width":390,"height":844})
        await ready(page)
        posts=[]
        async def report(route):
            posts.append(route.request.post_data_json)
            await route.fulfill(status=200,content_type="application/json",
                                headers={"access-control-allow-origin":"*"},
                                body='{"success":true,"id":501}')
        await page.route("**/api/reports",report)
        passport=await open_passport(page)
        await passport.locator("#krPassportReport").click()
        assert await page.locator("#reportModal").is_visible()
        explanation="У першоджерелі 2 кімнати, в картці одна."
        await page.locator("#krReportDetails").fill(explanation)
        await page.get_by_role("button",name="Кількість кімнат відрізняється від джерела").click()
        await page.wait_for_function("""() => document.querySelector('#reportModal')
                                    .classList.contains('hidden')""")
        assert len(posts)==1
        assert posts[0]["reason"]=="Невідповідність кількості кімнат"
        assert posts[0]["details"]==explanation
        assert posts[0]["dealId"]==await page.evaluate("LISTINGS[0].id")
        assert await page.locator("#krReportDetails").input_value()==""
        await browser.close()


@pytest.mark.asyncio
async def test_failed_report_preserves_written_details_for_retry():
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True)
        page=await browser.new_page()
        await ready(page)
        async def error(route):
            await route.fulfill(status=503,content_type="application/json",
                                headers={"access-control-allow-origin":"*"},
                                body='{"detail":"Сервер тимчасово недоступний"}')
        await page.route("**/api/reports",error)
        passport=await open_passport(page)
        await passport.locator("#krPassportReport").click()
        await page.locator("#krReportDetails").fill("На сайті зазначено іншу ціну.")
        await page.get_by_role("button",name="Ціна або додаткові платежі інші").click()
        await page.wait_for_function("""() => document.querySelector('#krReportStatus')
                                    .textContent.includes('тимчасово')""")
        assert await page.locator("#reportModal").is_visible()
        assert await page.locator("#krReportDetails").input_value()=="На сайті зазначено іншу ціну."
        assert await page.locator("#krReportDetails").is_enabled()
        await browser.close()


@pytest.mark.asyncio
async def test_api_revocation_closes_stale_open_detail_and_report():
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True)
        page=await browser.new_page(viewport={"width":390,"height":844})
        await ready(page)
        passport=await open_passport(page)
        await passport.locator("#krPassportReport").click()
        assert await page.locator("#dealModal").is_visible()
        assert await page.locator("#reportModal").is_visible()
        await page.evaluate("""() => {
          LISTINGS=[];
          refreshFavoriteKeys();
          renderAll();
        }""")
        assert await page.locator("#dealModal").is_hidden()
        assert await page.locator("#reportModal").is_hidden()
        assert await page.evaluate("currentModalDeal === null") is True
        await browser.close()


@pytest.mark.asyncio
async def test_same_unique_source_url_rebinds_live_detail_without_stale_contact():
    """A redraw with the SAME public identity may update its catalog ID."""
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True)
        page=await browser.new_page(viewport={"width":390,"height":844})
        await ready(page)
        await open_passport(page)
        result=await page.evaluate("""() => {
          const old=currentModalDeal;
          const oldKey=favoriteKey(old);
          if (!oldKey) throw Error('Missing synthetic stable source URL');
          const changed={...old,id:999991,price:old.price+111};
          LISTINGS=LISTINGS.map(d => d===old?changed:d);
          refreshFavoriteKeys();
          renderAll();
          return {
            oldKey,
            nextKey:favoriteKey(currentModalDeal),
            id:currentModalDeal?.id,
            price:currentModalDeal?.price,
            expectedPrice:changed.price,
            modalOpen:!document.getElementById('dealModal').classList.contains('hidden')
          };
        }""")
        assert result["oldKey"] == result["nextKey"]
        assert result["id"] == 999991
        assert result["price"] == result["expectedPrice"]
        assert result["modalOpen"]
        await browser.close()


@pytest.mark.asyncio
async def test_source_identity_changed_same_numeric_id_never_rebinds():
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True)
        page=await browser.new_page(viewport={"width":390,"height":844})
        await ready(page)
        await open_passport(page)
        await page.evaluate("""() => {
          const old=currentModalDeal;
          const fake={...old,title:"DIFFERENT HOME",source:"new-partner",
                     url:"https://example.org/offer/unrelated"};
          LISTINGS=LISTINGS.map(d => d===old?fake:d);
          refreshFavoriteKeys();
          renderAll();
        }""")
        assert await page.locator("#dealModal").is_hidden()
        assert await page.evaluate("currentModalDeal === null") is True
        await browser.close()
