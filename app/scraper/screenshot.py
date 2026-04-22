"""
Screenshot capture using Playwright.

Takes multiple viewport screenshots at different scroll positions for thorough
visual analysis. Screenshots are stored in Supabase Storage.
"""

from __future__ import annotations

import logging

from playwright.async_api import async_playwright

from app.storage.supabase import upload_file

logger = logging.getLogger(__name__)

# Viewport for a typical desktop view
_VIEWPORT = {"width": 1440, "height": 900}
_TIMEOUT_MS = 20_000
_NAVIGATION_TIMEOUT_MS = 15_000


async def capture_screenshots(url: str, lead_id: str) -> list[dict]:
    """
    Capture screenshots of a website at different scroll positions.

    Returns a list of dicts: [{"type": "viewport"|"scrolled"|"full", "url": str}]
    Each screenshot is uploaded to Supabase Storage.
    """
    screenshots = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport=_VIEWPORT,
                locale="sv-SE",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()

            # Navigate to the page
            try:
                await page.goto(url, wait_until="networkidle", timeout=_NAVIGATION_TIMEOUT_MS)
            except Exception:
                # Fallback to domcontentloaded if networkidle times out
                await page.goto(url, wait_until="domcontentloaded", timeout=_NAVIGATION_TIMEOUT_MS)

            # Wait for images and fonts to load
            await page.wait_for_timeout(2000)

            # Close cookie banners / popups that might obscure the view
            await _dismiss_popups(page)

            # Screenshot 1: Above the fold (viewport)
            viewport_bytes = await page.screenshot(type="jpeg", quality=80)
            viewport_url = _upload_screenshot(viewport_bytes, lead_id, "viewport")
            if viewport_url:
                screenshots.append({"type": "viewport", "url": viewport_url})

            # Screenshot 2: Scrolled down ~one viewport height
            await page.evaluate("window.scrollTo(0, window.innerHeight)")
            await page.wait_for_timeout(500)
            scrolled_bytes = await page.screenshot(type="jpeg", quality=80)
            scrolled_url = _upload_screenshot(scrolled_bytes, lead_id, "scrolled")
            if scrolled_url:
                screenshots.append({"type": "scrolled", "url": scrolled_url})

            # Screenshot 3: Full page (limited height to avoid huge images)
            await page.evaluate("window.scrollTo(0, 0)")
            await page.wait_for_timeout(300)
            try:
                full_bytes = await page.screenshot(
                    type="jpeg",
                    quality=60,
                    full_page=True,
                )
                # Only store if reasonable size (< 3MB)
                if len(full_bytes) < 3 * 1024 * 1024:
                    full_url = _upload_screenshot(full_bytes, lead_id, "full")
                    if full_url:
                        screenshots.append({"type": "full", "url": full_url})
            except Exception as e:
                logger.debug("Full page screenshot failed (page might be too long): %s", e)

            await browser.close()

    except Exception as e:
        logger.warning("Screenshot capture failed for %s: %s", url, e)

    return screenshots


async def capture_screenshot_bytes(url: str) -> list[dict]:
    """
    Capture multiple screenshots at different scroll positions and return raw bytes.

    Takes 4-5 screenshots covering the full page for thorough visual analysis.
    Returns a list of dicts: [{"type": str, "bytes": bytes}]
    """
    result = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport=_VIEWPORT,
                locale="sv-SE",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()

            try:
                await page.goto(url, wait_until="networkidle", timeout=_NAVIGATION_TIMEOUT_MS)
            except Exception:
                await page.goto(url, wait_until="domcontentloaded", timeout=_NAVIGATION_TIMEOUT_MS)

            await page.wait_for_timeout(2000)
            await _dismiss_popups(page)

            # Get total page height for calculating scroll positions
            page_height = await page.evaluate("document.body.scrollHeight")
            viewport_h = _VIEWPORT["height"]

            # Screenshot 1: Viewport (above the fold) - high quality
            viewport_bytes = await page.screenshot(type="jpeg", quality=90)
            result.append({"type": "viewport", "bytes": viewport_bytes})

            # Calculate how many scroll positions to capture (max 4 scrolled screenshots)
            total_scrolls = min(4, max(1, (page_height // viewport_h)))

            for i in range(1, total_scrolls + 1):
                scroll_y = min(i * viewport_h, page_height - viewport_h)
                if scroll_y <= 0:
                    break
                await page.evaluate(f"window.scrollTo(0, {scroll_y})")
                await page.wait_for_timeout(400)
                shot = await page.screenshot(type="jpeg", quality=90)
                result.append({"type": f"scroll_{i}", "bytes": shot})

            # Also capture footer area if not already covered
            footer_scroll = page_height - viewport_h
            if footer_scroll > total_scrolls * viewport_h:
                await page.evaluate(f"window.scrollTo(0, {footer_scroll})")
                await page.wait_for_timeout(400)
                footer_bytes = await page.screenshot(type="jpeg", quality=90)
                result.append({"type": "footer", "bytes": footer_bytes})

            await browser.close()

    except Exception as e:
        logger.warning("Screenshot capture failed for %s: %s", url, e)

    logger.info("Captured %d screenshots for vision analysis", len(result))
    return result


async def _dismiss_popups(page) -> None:
    """Try to close common cookie banners and popups."""
    selectors = [
        # Common cookie banner buttons
        'button:has-text("Acceptera")',
        'button:has-text("Godkänn")',
        'button:has-text("Accept")',
        'button:has-text("OK")',
        '[class*="cookie"] button',
        '[id*="cookie"] button',
        '[class*="consent"] button',
        # Close buttons on modals
        '[class*="popup"] [class*="close"]',
        '[class*="modal"] [class*="close"]',
    ]
    for selector in selectors:
        try:
            btn = page.locator(selector).first
            if await btn.is_visible(timeout=500):
                await btn.click(timeout=1000)
                await page.wait_for_timeout(300)
                return
        except Exception:
            continue


_MOBILE_VIEWPORT = {"width": 375, "height": 812}


async def capture_preview_screenshot(
    url: str,
    site_id: str,
    device: str = "desktop",
) -> str | None:
    """
    Capture a single preview screenshot for the site general page.

    Args:
        url: The viewer preview URL
        site_id: Used for storage path
        device: "desktop" (1440x900) or "mobile" (375x812)

    Returns: Public URL of the uploaded screenshot, or None on failure.
    """
    viewport = _MOBILE_VIEWPORT if device == "mobile" else _VIEWPORT

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport=viewport,
                locale="sv-SE",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ) if device == "desktop" else (
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
                ),
            )
            page = await context.new_page()

            try:
                await page.goto(url, wait_until="networkidle", timeout=_NAVIGATION_TIMEOUT_MS)
            except Exception:
                await page.goto(url, wait_until="domcontentloaded", timeout=_NAVIGATION_TIMEOUT_MS)

            await page.wait_for_timeout(2000)
            await _dismiss_popups(page)

            screenshot_bytes = await page.screenshot(type="jpeg", quality=85)
            await browser.close()

            screenshot_url = _upload_screenshot(
                screenshot_bytes,
                f"previews/{site_id}",
                device,
            )
            return screenshot_url

    except Exception as e:
        logger.warning("Preview screenshot failed for site %s (%s): %s", site_id, device, e)
        return None


def _upload_screenshot(data: bytes, lead_id: str, shot_type: str) -> str | None:
    """Upload a screenshot to Supabase Storage."""
    try:
        return upload_file(
            file_data=data,
            file_name=f"{shot_type}.jpg",
            content_type="image/jpeg",
            prefix=f"screenshots/{lead_id}",
        )
    except Exception as e:
        logger.warning("Failed to upload screenshot: %s", e)
        return None
