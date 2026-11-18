"""Generate comparable QA screenshots from the actual responsive application."""
import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
URL = (ROOT / "index.html").as_uri()
OUTPUT = ROOT / "artifacts"


async def wait_for_photo(page):
    """Avoid photographing a loading frame when remote images are slow."""
    try:
        await page.wait_for_function(
            "document.querySelector('#listViewContainer img.kr-gallery-image')?.naturalWidth > 0",
            timeout=2800)
    except Exception:
        pass


async def screenshot(browser, name: str, width: int, height: int, mobile=False):
    context = await browser.new_context(
        viewport={"width": width, "height": height},
        device_scale_factor=1,
        is_mobile=mobile,
        has_touch=mobile,
    )
    page = await context.new_page()
    await page.goto(URL, wait_until="domcontentloaded")
    await page.wait_for_function(
        "typeof LISTINGS !== 'undefined' && LISTINGS.length > 0 && document.querySelectorAll('#listViewContainer > div[onclick]').length > 0"
    )
    await page.wait_for_timeout(550)
    exceptions = []
    page.on("pageerror", lambda error: exceptions.append(str(error)))
    await page.wait_for_selector("#krHero")
    await wait_for_photo(page)
    await page.screenshot(path=str(OUTPUT / (name + "-first-visit.png")))
    if name == "phone":
        await page.locator("#krRoomsTrigger").click()
        await page.screenshot(path=str(OUTPUT / "phone-rooms-filter.png"))
        await page.locator("#krFiltersClose").click()
    await page.evaluate("""() => openDealModalById(LISTINGS[0].id)""")
    await page.wait_for_timeout(450)
    await page.screenshot(path=str(OUTPUT / (name + "-listing.png")))
    # Capture the real expanded evidence passport for mobile/tablet/desktop QA.
    if await page.locator("#krListingPassport").count():
        await page.locator("#krListingPassport summary").click()
        await page.locator("#krPassportRows").scroll_into_view_if_needed()
        await page.screenshot(path=str(OUTPUT / (name + "-passport.png")))
        await page.locator("#krListingPassport summary").click()
    if await page.locator("#krOriginalAction").is_visible():
        # The import's safe first action is an outgoing source URL, not a bot
        # contact request. Do not navigate to a third-party website in QA.
        original = page.locator("#krOriginalAction")
        href = await original.get_attribute("href")
        assert href and href.startswith("https://")
        assert await page.locator("#modalCallBtn").is_hidden()
        await page.screenshot(path=str(OUTPUT / (name + "-source-action.png")))
    else:
        # Only a supported first-party contact flow can show Telegram handoff.
        await page.locator("#modalCallBtn").click()
        await page.wait_for_timeout(180)
        if await page.locator("#krHandoff").is_visible():
            await page.screenshot(path=str(OUTPUT / (name + "-telegram-handoff.png")))
            await page.keyboard.press("Escape")
    await page.evaluate("""() => closeDealModal()""")
    await page.locator("#smartRadarOpen").click()
    await page.wait_for_timeout(200)
    await page.screenshot(path=str(OUTPUT / (name + "-saved-search.png")))
    await page.keyboard.press("Escape")
    assert not exceptions, "Uncaught browser errors in " + name + ": " + "; ".join(exceptions)
    await context.close()


async def screenshot_light(browser):
    """Review light theme in the actual app, not a separate design mockup."""
    context = await browser.new_context(
        viewport={"width":390,"height":844},device_scale_factor=1,
        is_mobile=True,has_touch=True)
    page = await context.new_page()
    await page.goto(URL,wait_until="domcontentloaded")
    await page.wait_for_selector("html.kr-unified-111[data-kr-theme]")
    await page.wait_for_function(
        "document.querySelectorAll('#listViewContainer > div[onclick]').length > 0")
    await page.evaluate("window.KyivRadarTheme.set('light')")
    await page.wait_for_selector("html[data-kr-theme='light']")
    await wait_for_photo(page)
    await page.wait_for_timeout(350)
    await page.screenshot(path=str(OUTPUT / "phone-light-first-visit.png"))
    await page.locator("#krConditionsTrigger").click()
    await page.screenshot(path=str(OUTPUT / "phone-light-conditions-filter.png"))
    await page.locator("#krFiltersClose").click()
    await page.evaluate("() => openDealModalById(LISTINGS[0].id)")
    await page.wait_for_selector("#dealModal:not(.hidden)")
    await page.screenshot(path=str(OUTPUT / "phone-light-listing-v115.png"))
    await page.locator("#krListingPassport summary").click()
    await page.locator("#krPassportRows").scroll_into_view_if_needed()
    await page.screenshot(path=str(OUTPUT / "phone-light-passport.png"))
    await page.locator("#krListingPassport summary").click()
    await page.evaluate("() => closeDealModal()")
    await page.locator("#krSimpleInfo").click()
    await page.screenshot(path=str(OUTPUT / "phone-light-theme-settings.png"))
    await context.close()


async def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            await screenshot(browser, "phone", 390, 844, True)
            await screenshot_light(browser)
            await screenshot(browser, "tablet", 820, 1180, True)
            await screenshot(browser, "desktop", 1440, 900, False)
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
