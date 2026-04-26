"""
AI-powered site planner.

Creates a SiteBlueprint via a fast/cheap LLM call before the main generator
runs. The blueprint decides which sections to include, the tone, and
per-section tips — so the generator can focus on producing great content.
"""

from __future__ import annotations

import json
import logging
import time

from pydantic import BaseModel

from app.ai.generator import _get_http_client
from app.ai.planner_prompts import build_planner_prompt
from app.config import settings

logger = logging.getLogger(__name__)

# Pricing per 1M tokens (USD) — Haiku
_PLANNER_MODEL = "claude-haiku-4-5-20251001"
_INPUT_COST_PER_1M = 1.00
_OUTPUT_COST_PER_1M = 5.00


# ---------------------------------------------------------------------------
# Blueprint models
# ---------------------------------------------------------------------------

class SectionPlan(BaseModel):
    section: str          # "hero", "about", "gallery", etc.
    tip: str              # Specific tip for the generator for this section
    priority: int         # 1=must-have, 2=recommended, 3=nice-to-have


class SiteBlueprint(BaseModel):
    purpose: str          # "Företagssida för restaurang"
    tone: str             # "professionell och inbjudande"
    target_audience: str  # "potentiella kunder"
    sections: list[SectionPlan]
    excluded_sections: list[str]
    color_direction: str | None = None
    content_direction: str
    pages_plan: list[dict] | None = None


# ---------------------------------------------------------------------------
# Planner entry point
# ---------------------------------------------------------------------------

async def plan_site(
    business_name: str,
    context: str,
    industry: str | None = None,
    industry_hint: str | None = None,
    num_images: int = 0,
    colors: dict | None = None,
    scraped_data_summary: str | None = None,
) -> SiteBlueprint | None:
    """Run the planner LLM call and return a SiteBlueprint.

    Returns None on failure (with logging) so the caller can fall back
    to generating without a blueprint.
    """
    system_prompt, user_prompt = build_planner_prompt(
        business_name=business_name,
        context=context,
        industry=industry,
        industry_hint=industry_hint,
        num_images=num_images,
        colors=colors,
        scraped_data_summary=scraped_data_summary,
    )

    payload = {
        "model": _PLANNER_MODEL,
        "max_tokens": 1500,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
        "temperature": 0.3,
    }

    headers = {
        "x-api-key": settings.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }

    last_error: Exception | None = None

    for attempt in range(2):
        try:
            start = time.monotonic()

            client = _get_http_client()
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=payload,
            )

            if resp.status_code != 200:
                body = resp.text[:500]
                logger.error(
                    "Planner API error %d (attempt %d): %s",
                    resp.status_code, attempt + 1, body,
                )
                if "credit balance" in body.lower():
                    logger.error("Anthropic API: insufficient credits")
                    return None
                resp.raise_for_status()

            data = resp.json()
            content = data["content"][0]["text"]

            # Extract JSON from potential markdown code blocks
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            blueprint_data = json.loads(content)
            blueprint = SiteBlueprint(**blueprint_data)

            # Track token usage and cost
            input_tokens = data["usage"]["input_tokens"]
            output_tokens = data["usage"]["output_tokens"]
            tokens_used = input_tokens + output_tokens
            cost_usd = round(
                (input_tokens / 1_000_000) * _INPUT_COST_PER_1M
                + (output_tokens / 1_000_000) * _OUTPUT_COST_PER_1M,
                6,
            )

            # Attach metadata as private attributes
            blueprint._tokens_used = tokens_used  # type: ignore[attr-defined]
            blueprint._cost_usd = cost_usd  # type: ignore[attr-defined]

            duration_ms = int((time.monotonic() - start) * 1000)
            logger.info(
                "Blueprint created: sections=%d in=%d out=%d cost=$%.4f duration=%dms attempt=%d",
                len(blueprint.sections),
                input_tokens,
                output_tokens,
                cost_usd,
                duration_ms,
                attempt + 1,
            )

            return blueprint

        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            logger.warning("Planner attempt %d failed (parse): %s", attempt + 1, e)
            continue
        except Exception as e:
            last_error = e
            logger.error("Planner attempt %d failed (unexpected): %s", attempt + 1, e)
            return None

    logger.error("Planner failed after 2 attempts: %s", last_error)
    return None
