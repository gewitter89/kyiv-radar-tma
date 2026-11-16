"""Generate comparable QA screenshots from the actual responsive application."""
import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
URL = (ROOT / "index.html").as_uri()
OUTPUT = ROOT / "artifacts"


async def screenshot(browser, name: str, width: int, height: int, mobile=False):
    context = await browser.new_context(
        viewport={"width": width, "height": height},
        device_scale_factor=1,
        is_mobile=mobile,
        has_touch=mobile,
    )
    page = await context.new_page()
    await page.goto(URL, wait_until="domcontentloaded")
    await page.wait_for_function("typeof LISTINGS !== 'undefined' && LISTINGS.length > 0")
    await page.wait_for_timeout(1200)
    await page.screenshot(path=str(OUTPUT / (name + "-map.png")))
    await page.evaluate("""() => openDealModalById(LISTINGS[0].id)""")
    await page.wait_for_timeout(800)
    await page.screenshot(path=str(OUTPUT / (name + "-listing.png")))
    await context.close()


async def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            await screenshot(browser, "phone", 390, 844, True)
            await screenshot(browser, "tablet", 820, 1180, True)
            await screenshot(browser, "desktop", 1440, 900, False)
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
