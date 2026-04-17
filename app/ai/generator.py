"""
AI-powered site generator.

Takes scraped data and produces a SiteSchema JSON via LLM.
Uses Anthropic Claude API. Sends screenshots as images for accurate
color matching and design understanding.
"""

from __future__ import annotations

import base64
import json
import logging
import time

import httpx

from app.ai.prompts import build_prompt
from app.config import settings
from app.sites.site_schema import SiteSchema

logger = logging.getLogger(__name__)


class GenerationResult:
    def __init__(
        self,
        site_schema: SiteSchema,
        tokens_used: int,
        model: str,
        cost_usd: float,
        duration_ms: int,
    ):
        self.site_schema = site_schema
        self.tokens_used = tokens_used
        self.model = model
        self.cost_usd = cost_usd
        self.duration_ms = duration_ms


# Approximate costs per 1M tokens (input + output blended)
_COST_PER_1M: dict[str, float] = {
    "claude-haiku-4-5-20251001": 1.00,
    "claude-sonnet-4-6": 3.00,
}


_VALID_TOP_LEVEL_KEYS = {
    "meta", "theme", "branding", "business", "hero", "about",
    "features", "stats", "services", "process", "gallery", "team",
    "testimonials", "faq", "cta", "contact", "seo",
}


def _strip_unknown_keys(site_data: dict) -> None:
    """Remove unexpected top-level keys before Pydantic validation."""
    for key in list(site_data.keys()):
        if key not in _VALID_TOP_LEVEL_KEYS:
            del site_data[key]


async def generate_site(
    business_name: str,
    industry: str | None,
    website_url: str,
    email: str | None,
    phone: str | None,
    address: str | None,
    texts: dict | None,
    colors: dict | None,
    services: list | None,
    logo_url: str | None,
    social_links: dict | None,
    images: list | None = None,
    visual_analysis: dict | None = None,
    model_override: str | None = None,
    screenshot_bytes: list[dict] | None = None,
) -> GenerationResult:
    """
    Generate a complete SiteSchema using an LLM.

    Optionally sends screenshots as images in the prompt for accurate
    color matching and design analysis.
    Retries once on invalid JSON.
    """
    model = model_override or settings.AI_MODEL
    system_prompt, user_prompt = build_prompt(
        business_name=business_name,
        industry=industry,
        website_url=website_url,
        email=email,
        phone=phone,
        address=address,
        texts=texts,
        colors=colors,
        services=services,
        logo_url=logo_url,
        social_links=social_links,
        images=images,
        visual_analysis=visual_analysis,
    )

    last_error = None
    for attempt in range(2):
        try:
            start = time.monotonic()

            raw_json, tokens = await _call_anthropic(
                system_prompt, user_prompt, model,
                screenshot_bytes=screenshot_bytes,
            )

            duration_ms = int((time.monotonic() - start) * 1000)

            # Parse and validate
            site_data = json.loads(raw_json)
            _strip_unknown_keys(site_data)
            site_schema = SiteSchema(**site_data)

            cost_per_m = _COST_PER_1M.get(model, 1.0)
            cost = (tokens / 1_000_000) * cost_per_m

            logger.info(
                "Site generated: model=%s tokens=%d cost=$%.4f duration=%dms attempt=%d",
                model, tokens, cost, duration_ms, attempt + 1,
            )

            return GenerationResult(
                site_schema=site_schema,
                tokens_used=tokens,
                model=model,
                cost_usd=round(cost, 6),
                duration_ms=duration_ms,
            )

        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            logger.warning("Generation attempt %d failed: %s", attempt + 1, e)
            continue

    raise RuntimeError(f"Failed to generate valid site after 2 attempts: {last_error}")


async def _call_anthropic(
    system: str,
    user: str,
    model: str,
    screenshot_bytes: list[dict] | None = None,
) -> tuple[str, int]:
    """Call Anthropic API with optional screenshot images. Returns (json_string, total_tokens)."""

    # Build user message content — include screenshots as images if available
    user_content: list[dict] = []

    if screenshot_bytes:
        # Add up to 3 screenshots to the generation prompt for color/design accuracy
        for shot in screenshot_bytes[:3]:
            img_bytes = shot.get("bytes")
            if not img_bytes or len(img_bytes) == 0:
                continue
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            user_content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": b64,
                },
            })

    user_content.append({"type": "text", "text": user})

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 16000,
                "system": system,
                "messages": [{"role": "user", "content": user_content}],
                "temperature": 0.5,
            },
        )
        if resp.status_code != 200:
            body = resp.text[:500]
            if "credit balance" in body.lower():
                raise RuntimeError(
                    "Anthropic API: insufficient credits. "
                    "Check that your ANTHROPIC_API_KEY belongs to the workspace where you added credits."
                )
            resp.raise_for_status()
        data = resp.json()

        content = data["content"][0]["text"]
        # Extract JSON from potential markdown code blocks
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        tokens = data["usage"]["input_tokens"] + data["usage"]["output_tokens"]
        return content, tokens
