"""
Before/after video generator using Playwright screen recording.

Records a single continuous video that:
1. Shows a "BEFORE" title card
2. Scrolls through the original website
3. Shows an "AFTER" title card
4. Scrolls through the newly generated site
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from playwright.async_api import async_playwright, Page

from app.config import settings
from app.storage.supabase import upload_file

logger = logging.getLogger(__name__)

_VIEWPORT = {"width": 960, "height": 540}
_NAVIGATION_TIMEOUT_MS = 15_000
_MAX_SCROLL_HEIGHT = 4000  # Cap scrolling to avoid very long videos on tall pages
_UPLOAD_TIMEOUT = 120.0


def _title_card_html(title: str, subtitle: str, color: str) -> str:
    """Generate a data URI HTML page for a title card."""
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{
  width:100vw;height:100vh;display:flex;flex-direction:column;
  align-items:center;justify-content:center;
  background:linear-gradient(135deg,{color} 0%,#1a1a2e 100%);
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  color:#fff;
}}
h1{{font-size:72px;font-weight:800;letter-spacing:-2px;margin-bottom:16px;
   text-shadow:0 4px 30px rgba(0,0,0,0.3)}}
p{{font-size:24px;opacity:0.8;font-weight:300}}
</style></head><body>
<h1>{title}</h1>
<p>{subtitle}</p>
</body></html>"""
    return "data:text/html;charset=utf-8," + html.replace("\n", "").replace("#", "%23")


async def _smooth_scroll(page: Page, pause_on_hero_ms: int = 2500) -> None:
    """Scroll down the page smoothly with a pause on the hero section."""
    # Pause on the hero area first (above the fold)
    await page.wait_for_timeout(pause_on_hero_ms)

    page_height = await page.evaluate("document.body.scrollHeight")
    viewport_h = _VIEWPORT["height"]
    max_scroll = min(page_height - viewport_h, _MAX_SCROLL_HEIGHT)
    scroll_step = 250  # pixels per step
    scroll_delay = 50  # ms between steps — smooth feel

    current = 0
    while current < max_scroll:
        current = min(current + scroll_step, max_scroll)
        await page.evaluate(f"window.scrollTo({{top: {current}, behavior: 'instant'}})")
        await page.wait_for_timeout(scroll_delay)

    # Pause at the bottom briefly
    await page.wait_for_timeout(800)


async def _dismiss_popups(page: Page) -> None:
    """Try to close common cookie banners and popups."""
    selectors = [
        'button:has-text("Acceptera")',
        'button:has-text("Godkänn")',
        'button:has-text("Accept")',
        'button:has-text("OK")',
        '[class*="cookie"] button',
        '[id*="cookie"] button',
        '[class*="consent"] button',
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


async def generate_before_after_video(
    original_url: str,
    generated_site_id: str,
    business_name: str | None = None,
) -> str:
    """
    Generate a before/after video comparing the original website
    with the new generated site.

    Returns the public URL of the uploaded video.
    """
    viewer_url = f"{settings.VIEWER_URL}/{generated_site_id}"
    name = business_name or "Website"

    with tempfile.TemporaryDirectory() as tmpdir:
        video_dir = Path(tmpdir) / "videos"
        video_dir.mkdir()

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport=_VIEWPORT,
                locale="sv-SE",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                record_video_dir=str(video_dir),
                record_video_size=_VIEWPORT,
            )
            page = await context.new_page()

            # ── Title card: BEFORE ──
            before_card = _title_card_html("Innan", f"{name} — nuvarande hemsida", "#6b21a8")
            await page.goto(before_card)
            await page.wait_for_timeout(2500)

            # ── Navigate to original site ──
            try:
                await page.goto(
                    original_url,
                    wait_until="networkidle",
                    timeout=_NAVIGATION_TIMEOUT_MS,
                )
            except Exception:
                try:
                    await page.goto(
                        original_url,
                        wait_until="domcontentloaded",
                        timeout=_NAVIGATION_TIMEOUT_MS,
                    )
                except Exception as e:
                    logger.warning("Could not load original site %s: %s", original_url, e)

            await page.wait_for_timeout(1500)
            await _dismiss_popups(page)
            await _smooth_scroll(page)

            # ── Title card: AFTER ──
            after_card = _title_card_html("Efter", f"{name} — ny hemsida av Qvicko", "#059669")
            await page.goto(after_card)
            await page.wait_for_timeout(2500)

            # ── Navigate to generated site ──
            try:
                await page.goto(
                    viewer_url,
                    wait_until="networkidle",
                    timeout=_NAVIGATION_TIMEOUT_MS,
                )
            except Exception:
                try:
                    await page.goto(
                        viewer_url,
                        wait_until="domcontentloaded",
                        timeout=_NAVIGATION_TIMEOUT_MS,
                    )
                except Exception as e:
                    logger.warning("Could not load generated site %s: %s", viewer_url, e)

            await page.wait_for_timeout(1500)
            await _smooth_scroll(page, pause_on_hero_ms=3000)

            # ── End card ──
            end_card = _title_card_html("Qvicko", "Din nya hemsida vantar", "#2563eb")
            await page.goto(end_card)
            await page.wait_for_timeout(2000)

            # Close context to finalize the video file
            await context.close()
            await browser.close()

        # Find the recorded video file
        video_files = list(video_dir.glob("*.webm"))
        if not video_files:
            raise RuntimeError("Playwright did not produce a video file")

        video_path = video_files[0]
        video_bytes = video_path.read_bytes()

        logger.info(
            "Video generated: %s (%.1f MB)",
            video_path.name,
            len(video_bytes) / (1024 * 1024),
        )

        # Upload to Supabase Storage (higher timeout for video files)
        public_url = upload_file(
            file_data=video_bytes,
            file_name="before_after.webm",
            content_type="video/webm",
            prefix=f"videos/{generated_site_id}",
            timeout=_UPLOAD_TIMEOUT,
        )

        return public_url
