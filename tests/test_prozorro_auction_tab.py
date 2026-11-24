"""Browser tests for staging auction tab using isolated synthetic API and mocked Telegram."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import pytest
from playwright.async_api import async_playwright

ROOT=Path(__file__).resolve().parents[1]
ORIGIN="http://127.0.0.1:8765"
HTML='<!doctype html><html lang="uk"><head><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/auction-tab.css"></head><body><header>КИЇВ РАДАР</header><script src="/auction-tab.js"></script></body></html>'


def response(now=None):
    now=now or datetime.now(timezone.utc)
    rows=[]
    for n,price in [(1,"2000000.00"),(2,"1000000.00")]:
        key=f"ALE001-UA-20261124-{n:05d}"
        rows.append({"auction_id":key,"source_url":"https://prozorro.sale/auction/"+key+"/",
                     "source":"prozorro_sale","kind":"sale_auction","city":"Київ","asset_class":"apartment_classified",
                     "starting_bid_uah":price,"vat_included":False,"bidding_ends_at":(now+timedelta(days=n)).isoformat(),
                     "observed_at":(now-timedelta(minutes=1)).isoformat(),
                     "valid_until":(now+timedelta(seconds=45)).isoformat()})
    return {"available":True,"coverage_complete":False,"auctions":rows}


async def configure(page, *, enabled=True):
    calls=[]
    state={"available":True,"errors":[]}
    page.on("pageerror",lambda error: state["errors"].append(str(error)))
    async def route(r):
        path=r.request.url.removeprefix(ORIGIN)
        if path=="/":
            await r.fulfill(content_type="text/html",body=HTML)
        elif path in ("/auction-tab.js","/auction-tab.css"):
            await r.fulfill(content_type="text/javascript" if path.endswith(".js") else "text/css",
                            body=(ROOT/path[1:]).read_text(encoding="utf-8"))
        elif path=="/api/auctions":
            calls.append(path)
            if state["available"]:
                await r.fulfill(status=200,content_type="application/json",body=json.dumps(response(),ensure_ascii=False))
            else:
                await r.fulfill(status=503,content_type="application/json",body=json.dumps({"available":False,"auctions":[]}))
        else:
            await r.abort()
    await page.route("**/*",route)
    if enabled:
        await page.add_init_script("""window.KR_AUCTIONS_STAGING=true;
          window.__links=[];window.Telegram={WebApp:{openLink(url){window.__links.push(url)}}};""")
    await page.goto(ORIGIN+"/")
    return calls,state


def test_actual_index_wires_tab_but_never_enables_flag():
    text=(ROOT/"index.html").read_text(encoding="utf-8")
    assert "./auction-tab.js?v=1" in text
    assert "KR_AUCTIONS_STAGING=true" not in text


@pytest.mark.asyncio
async def test_disabled_never_calls_api():
    async with async_playwright() as p:
        browser=await p.chromium.launch()
        page=await browser.new_page()
        calls,_=await configure(page,enabled=False)
        assert await page.locator("#krAuctionsNav").count()==0
        assert calls==[]
        await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("width,height",[(320,640),(390,844),(768,1024),(1280,900)])
async def test_filters_favorites_telegram_and_layout(width,height):
    async with async_playwright() as p:
        browser=await p.chromium.launch()
        page=await browser.new_page(viewport={"width":width,"height":height},has_touch=width<500,is_mobile=width<500)
        calls,state=await configure(page)
        await page.locator("#krAuctionsNav").click()
        cards=page.locator("#krAuctionList article")
        try:
            await cards.nth(1).wait_for(timeout=8000)
        except Exception:
            pytest.fail(f"auction cards missing: calls={calls}, errors={state['errors']}, status={await page.locator('#krAuctionDialog [role=status]').inner_text()}, hidden={await page.evaluate('document.hidden')}")
        assert calls==["/api/auctions"]
        assert await page.locator("#krAuctionDialog").evaluate("(e)=>e.scrollWidth<=e.clientWidth+1")
        await page.locator("#krAuctionSort").select_option("price")
        assert "00002" in await cards.first.inner_text()
        await page.locator("#krAuctionMax").fill("1500000")
        assert await cards.count()==1
        await cards.first.get_by_role("button",name="Додати в обрані").click()
        await page.locator("#krAuctionOnlyFav").check()
        assert await cards.count()==1
        await cards.first.get_by_role("link").click()
        assert (await page.evaluate("window.__links"))==["https://prozorro.sale/auction/ALE001-UA-20261124-00002/"]
        await page.reload()
        await page.locator("#krAuctionsNav").click()
        try:
            await cards.nth(1).wait_for(timeout=8000)
        except Exception:
            pytest.fail(f"auction cards missing: calls={calls}, errors={state['errors']}, status={await page.locator('#krAuctionDialog [role=status]').inner_text()}, hidden={await page.evaluate('document.hidden')}")
        await page.locator("#krAuctionOnlyFav").check()
        assert await cards.count()==1
        assert "00002" in await cards.first.inner_text()
        await page.get_by_role("button",name="Закрити аукціони").click()
        state["available"]=False
        await page.locator("#krAuctionsNav").click()
        await page.get_by_text("Дані тимчасово недоступні.").wait_for()
        assert await cards.count()==0
        await browser.close()
