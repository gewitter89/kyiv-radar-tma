# -*- coding: utf-8 -*-
"""A missing real photo should never render a broken-image icon in detail view.

Use synthetic catalog in CI, intercepted image responses and no external access.
"""
from pathlib import Path
import base64

import pytest
from playwright.async_api import async_playwright

URL = (Path(__file__).resolve().parents[1] / "index.html").as_uri()
BAD = "https://qa-images.example.test/photo-failed.png"
GOOD = "https://qa-images.example.test/photo-loaded.png"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/RqwAAAAASUVORK5CYII="
)


@pytest.mark.asyncio
async def test_modal_bad_photo_fallback_and_recovery_without_external_images():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844},
                                      is_mobile=True, has_touch=True)

        async def images(route):
            if route.request.url == GOOD:
                await route.fulfill(status=200, content_type="image/png", body=PNG)
            else:
                await route.abort("failed")

        await page.route("https://qa-images.example.test/**", images)
        await page.route("**/api/deals*", lambda route: route.abort())
        await page.goto(URL, wait_until="domcontentloaded")
        await page.wait_for_function("LISTINGS.length > 0")
        await page.evaluate("""({bad, good}) => {
           const entry = LISTINGS[0];
           entry.images = [bad, good];
           openDealModalById(entry.id);
        }""", {"bad": BAD, "good": GOOD})

        fallback = page.locator("#modalPhotoPlaceholder")
        await fallback.get_by_text("Фото тимчасово недоступне").wait_for(state="visible")
        assert await page.locator("#modalImage").is_hidden()
        # User may swipe to another image; the image failure does not trap them.
        assert await page.locator("#modalPhotoIndex").inner_text() == "1/2"
        await page.evaluate("switchModalPhoto(1)")
        await page.wait_for_function("""() => {
          const img = document.querySelector('#modalImage');
          const fallback = document.querySelector('#modalPhotoPlaceholder');
          return img && img.complete && img.naturalWidth > 0 &&
                 !img.classList.contains('hidden') &&
                 fallback?.classList.contains('hidden');
        }""")
        assert await page.locator("#modalPhotoIndex").inner_text() == "2/2"

        await page.evaluate("switchModalPhoto(-1)")
        await fallback.get_by_text("Фото тимчасово недоступне").wait_for(state="visible")
        assert await page.locator("#modalImage").is_hidden()
        await browser.close()


@pytest.mark.asyncio
async def test_modal_no_photos_has_clear_text_and_hidden_controls():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        await page.route("**/api/deals*", lambda route: route.abort())
        await page.goto(URL, wait_until="domcontentloaded")
        await page.wait_for_function("LISTINGS.length > 0")
        await page.evaluate("""() => {
           const entry = LISTINGS[0];
           entry.images = [];
           openDealModalById(entry.id);
        }""")
        assert await page.get_by_text("Фотографій поки немає").is_visible()
        assert await page.locator("#modalImage").is_hidden()
        for selector in ("#modalPhotoIndex", "#modalPhotoDots", "#modalPhotoPrev", "#modalPhotoNext"):
            assert await page.locator(selector).is_hidden()
        await browser.close()
