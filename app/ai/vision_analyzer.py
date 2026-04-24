"""
Vision-based website analyzer using Claude's vision capabilities.

Sends multiple screenshots of a website to Claude and extracts detailed design
information: exact colors (hex), layout structure, typography, content sections,
and visual style — all structured as JSON for the site generator.
"""

from __future__ import annotations

import base64
import json
import logging

from app.ai.generator import _get_http_client
from app.config import settings

logger = logging.getLogger(__name__)

_VISION_PROMPT = """Du är en expert webbdesigner som analyserar screenshots av en hemsida.

Analysera ALLA screenshots noggrant. Svara ENBART med valid JSON — ingen text före eller efter.

VIKTIGT om färger:
- Identifiera de EXAKTA hex-koderna som används på sidan
- Primary = den mest dominerande varumärkesfärgen (knappar, rubriker, accenter)
- Secondary = den sekundära färgen (bakgrunder, gradienter)
- Accent = kontrastfärg för CTA-knappar och framhävningar
- Background = bakgrundsfärgen (ofta #ffffff eller liknande)
- Text = textfärgen (ofta mörk, nära #111827)
- Var EXTREMT precis med hex-koderna. Gissa inte — analysera pixlarna.

{
  "colors": {
    "primary": "#exact_hex",
    "secondary": "#exact_hex",
    "accent": "#exact_hex",
    "background": "#exact_hex",
    "text": "#exact_hex"
  },
  "typography": {
    "heading_style": "serif/sans-serif/display, beskriv stil",
    "body_style": "serif/sans-serif",
    "heading_weight": "thin/normal/semibold/bold/extrabold/black"
  },
  "layout": {
    "hero_type": "fullscreen_image/gradient/solid_color/video/split",
    "has_hero_image": true/false,
    "navigation_style": "transparent/solid/sticky",
    "section_count": 0,
    "column_layout": "beskrivning av kolumner/grid"
  },
  "design_style": "modern/minimalist/luxury/corporate/playful/rustic — kort beskrivning",
  "mood": "känsla/stämning sidan förmedlar — 2-3 ord",
  "content_sections": [
    {
      "type": "hero/about/services/gallery/testimonials/features/stats/team/faq/process/cta/contact/pricing/other",
      "headline": "rubrik om synlig",
      "summary": "kort beskrivning av innehållet, max 50 ord",
      "has_images": true/false,
      "image_count": 0
    }
  ],
  "images": {
    "total_visible": 0,
    "hero_image_description": "beskrivning av hero-bilden om det finns en",
    "image_style": "foto/illustration/ikon/mixed",
    "image_quality": "high/medium/low"
  },
  "cta_buttons": ["text på synliga CTA-knappar"],
  "business_info_visible": {
    "name": "företagsnamn om synligt",
    "tagline": "slogan/tagline om synlig",
    "phone": "telefonnummer om synligt",
    "email": "email om synlig",
    "address": "adress om synlig"
  },
  "overall_quality": "professional/semi-professional/amateur/outdated",
  "improvement_areas": ["2-3 konkreta förbättringsområden"]
}"""


async def analyze_screenshots(screenshot_bytes_list: list[dict]) -> dict | None:
    """
    Analyze website screenshots using Claude Vision.

    Sends up to 5 screenshots for thorough analysis of colors, layout, and content.

    Args:
        screenshot_bytes_list: List of {"type": str, "bytes": bytes} dicts

    Returns:
        Dict with detailed visual analysis results, or None on failure.
    """
    if not screenshot_bytes_list:
        logger.info("No screenshots provided for vision analysis")
        return None

    if not settings.ANTHROPIC_API_KEY:
        logger.warning("No Anthropic API key configured, skipping vision analysis")
        return None

    # Build the content array with images — use up to 5 screenshots
    content = []
    for shot in screenshot_bytes_list[:5]:
        img_bytes = shot.get("bytes")
        if not img_bytes or len(img_bytes) == 0:
            logger.warning("Empty screenshot bytes, skipping")
            continue
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": b64,
            },
        })

    if not content:
        logger.warning("No valid screenshot data to analyze")
        return None

    content.append({"type": "text", "text": _VISION_PROMPT})

    try:
        import httpx

        client = _get_http_client()
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 4000,
                "messages": [{"role": "user", "content": content}],
                "temperature": 0.2,
            },
        )
        resp.raise_for_status()
        data = resp.json()

        text = data["content"][0]["text"].strip()
        # Extract JSON from potential markdown code blocks
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        # Find the JSON object in the text (skip any preamble/postamble)
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]

        result = json.loads(text)

        tokens = data["usage"]["input_tokens"] + data["usage"]["output_tokens"]
        logger.info(
            "Vision analysis complete: tokens=%d, keys=%s, sections=%d",
            tokens, list(result.keys()),
            len(result.get("content_sections", [])),
        )

        return result

    except httpx.TimeoutException:
        logger.warning("Vision analysis timed out")
        return None
    except httpx.HTTPStatusError as e:
        logger.warning(
            "Vision API returned HTTP %d: %s",
            e.response.status_code,
            e.response.text[:500],
        )
        return None
    except json.JSONDecodeError as e:
        logger.warning("Vision analysis returned invalid JSON: %s", e)
        return None
    except Exception:
        logger.exception("Vision analysis failed with unexpected error")
        return None
