# -*- coding: utf-8 -*-
"""Photo-gallery gesture regression tests (mobile/tablet/desktop)."""
import os
import pytest
from playwright.async_api import async_playwright

INDEX = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "index.html"))
FILE_URL = "file:///" + INDEX.replace("\\", "/")
IMAGE = "data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs="


async def prepare_gallery(page, number=3):
    await page.goto(FILE_URL)
    await page.wait_for_function("typeof LISTINGS !== 'undefined' && LISTINGS.length > 0")
    await page.evaluate(
        """({number, image}) => {
            const item = LISTINGS[0];
            item.images = Array.from({length: number}, () => image);
            openDealModalById(item.id);
        }""",
        {"number": number, "image": IMAGE},
    )
    assert await page.is_visible("#dealModal")


async def send_touch(page, first_x, last_x, first_y=170, last_y=170):
    """Dispatch one-finger touch events; test the gallery's gesture classification."""
    await page.evaluate(
        """({firstX, lastX, firstY, lastY}) => {
            const el = document.getElementById('modalPhotoContainer');
            const a = new Touch({identifier: 1, target: el, clientX: firstX, clientY: firstY});
            const b = new Touch({identifier: 1, target: el, clientX: lastX, clientY: lastY});
            el.dispatchEvent(new TouchEvent('touchstart', {
                bubbles: true, touches: [a], changedTouches: [a]
            }));
            el.dispatchEvent(new TouchEvent('touchend', {
                bubbles: true, touches: [], changedTouches: [b]
            }));
        }""",
        {"firstX": first_x, "lastX": last_x, "firstY": first_y, "lastY": last_y},
    )


@pytest.mark.asyncio
async def test_mobile_swipe_changes_photo_and_vertical_scroll_does_not():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            is_mobile=True, has_touch=True, viewport={"width": 390, "height": 844}
        )
        page = await context.new_page()
        await prepare_gallery(page)
        assert await page.inner_text("#modalPhotoIndex") == "1/3"
        assert not await page.is_visible("#modalPhotoNext")
        assert not await page.is_visible("#modalPhotoPrev")

        await send_touch(page, 310, 85)
        assert await page.inner_text("#modalPhotoIndex") == "2/3"

        await send_touch(page, 85, 310)
        assert await page.inner_text("#modalPhotoIndex") == "1/3"

        await send_touch(page, 310, 290, 160, 340)
        assert await page.inner_text("#modalPhotoIndex") == "1/3"

        await browser.close()


@pytest.mark.asyncio
async def test_tablet_swipe_and_single_photo():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            is_mobile=True, has_touch=True, viewport={"width": 810, "height": 1080}
        )
        page = await context.new_page()
        await prepare_gallery(page)
        await send_touch(page, 650, 350)
        assert await page.inner_text("#modalPhotoIndex") == "2/3"
        assert not await page.is_visible("#modalPhotoNext")

        await page.evaluate("""() => {
            LISTINGS[0].images = [LISTINGS[0].images[0]];
            openDealModalById(LISTINGS[0].id);
        }""")
        await send_touch(page, 650, 350)
        assert not await page.is_visible("#modalPhotoIndex")
        assert not await page.is_visible("#modalPhotoNext")
        await browser.close()


@pytest.mark.asyncio
async def test_desktop_arrows_and_keyboard():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1366, "height": 900})
        await prepare_gallery(page)
        assert await page.is_visible("#modalPhotoNext")
        assert await page.is_visible("#modalPhotoPrev")
        await page.click("#modalPhotoNext")
        assert await page.inner_text("#modalPhotoIndex") == "2/3"

        await page.keyboard.press("ArrowRight")
        assert await page.inner_text("#modalPhotoIndex") == "3/3"

        await page.keyboard.press("ArrowLeft")
        assert await page.inner_text("#modalPhotoIndex") == "2/3"
        await browser.close()
