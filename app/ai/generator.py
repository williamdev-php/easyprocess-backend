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
import random
import time
from typing import TYPE_CHECKING

import asyncio

import httpx

from app.ai.prompts import build_prompt

if TYPE_CHECKING:
    from app.ai.planner import SiteBlueprint

from app.config import settings
from app.database import get_db_session
from app.platform_settings.service import get_setting
from app.sites.site_schema import CURRENT_VIEWER_VERSION, SiteSchema

logger = logging.getLogger(__name__)

# --- Shared HTTP client (connection pooling) ---------------------------------
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    """Return a shared httpx client with connection pooling."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=120.0,
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
                keepalive_expiry=60,
            ),
        )
    return _http_client


async def close_http_client() -> None:
    """Close the shared client (call on app shutdown)."""
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None


# --- Retry helpers -----------------------------------------------------------
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}
_MAX_API_RETRIES = 3
_BASE_BACKOFF_SECONDS = 2.0


async def _retry_api_call(call_fn, *, max_retries: int = _MAX_API_RETRIES):
    """Retry an async API call with exponential backoff on transient errors.

    Retries on: httpx network errors, timeout, and 429/5xx status codes.
    Raises on: 4xx client errors (except 429), RuntimeError for credits.
    """
    last_exc = None
    for attempt in range(max_retries):
        try:
            return await call_fn()
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status in _RETRYABLE_STATUS_CODES:
                # Use Retry-After header if present (common for 429)
                retry_after = e.response.headers.get("retry-after")
                if retry_after and retry_after.isdigit():
                    wait = float(retry_after)
                else:
                    wait = _BASE_BACKOFF_SECONDS * (2 ** attempt)
                logger.warning(
                    "API returned %d, retrying in %.1fs (attempt %d/%d)",
                    status, wait, attempt + 1, max_retries,
                )
                last_exc = e
                await asyncio.sleep(wait)
                continue
            raise  # non-retryable status
        except (httpx.TimeoutException, httpx.ConnectError, httpx.ConnectTimeout) as e:
            wait = _BASE_BACKOFF_SECONDS * (2 ** attempt)
            logger.warning(
                "API network error (%s), retrying in %.1fs (attempt %d/%d)",
                type(e).__name__, wait, attempt + 1, max_retries,
            )
            last_exc = e
            await asyncio.sleep(wait)
            continue

    raise RuntimeError(f"API call failed after {max_retries} retries: {last_exc}")


class GenerationResult:
    def __init__(
        self,
        site_schema: SiteSchema,
        tokens_used: int,
        input_tokens: int,
        output_tokens: int,
        model: str,
        cost_usd: float,
        duration_ms: int,
        install_apps: list[str] | None = None,
    ):
        self.site_schema = site_schema
        self.tokens_used = tokens_used
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.model = model
        self.cost_usd = cost_usd
        self.duration_ms = duration_ms
        self.install_apps = install_apps or []


# Pricing per 1M tokens (USD)
_INPUT_COST_PER_1M: dict[str, float] = {
    "claude-haiku-4-5-20251001": 1.00,
    "claude-sonnet-4-6": 3.00,
    "gemini-2.5-flash": 0.15,
}
_OUTPUT_COST_PER_1M: dict[str, float] = {
    "claude-haiku-4-5-20251001": 5.00,
    "claude-sonnet-4-6": 15.00,
    "gemini-2.5-flash": 0.60,
}

# Models that use the Google Gemini API instead of Anthropic
_GEMINI_MODELS = {"gemini-2.5-flash"}


# Number of available style variants (0 through N-1). Increase this when
# you add more variant layouts in the viewer section components.
# 0 = Original, 1 = Modern Cards, 2 = Clean & Minimal, 3 = Bold & Filled
TOTAL_STYLE_VARIANTS = 4  # variants 0, 1, 2, 3

_VALID_TOP_LEVEL_KEYS = {
    "meta", "theme", "branding", "business", "section_order", "style_variant",
    "viewer_version", "section_settings",
    "hero", "about", "features", "stats", "services", "process",
    "gallery", "team", "testimonials", "faq", "cta", "contact",
    "pricing", "video", "logo_cloud", "custom_content", "banner",
    "ranking", "quiz",
    "seo",
    "pages", "install_apps",
}


def _strip_unknown_keys(site_data: dict) -> None:
    """Remove unexpected top-level keys before Pydantic validation."""
    for key in list(site_data.keys()):
        if key not in _VALID_TOP_LEVEL_KEYS:
            del site_data[key]


def _promote_home_page_sections(site_data: dict) -> None:
    """If the AI placed home-page sections inside pages[0].sections instead of
    at the top level, extract them so the viewer can render them."""
    # Only act when ALL content sections are null/missing
    _SECTION_KEYS = {
        "hero", "about", "features", "stats", "services", "process",
        "gallery", "team", "testimonials", "faq", "cta", "contact",
        "pricing", "video", "logo_cloud", "custom_content", "banner",
        "ranking", "quiz",
    }
    has_any_section = any(site_data.get(k) for k in _SECTION_KEYS)
    if has_any_section:
        return

    pages = site_data.get("pages")
    if not isinstance(pages, list) or not pages:
        return

    home_page = None
    home_idx = None
    for idx, page in enumerate(pages):
        if not isinstance(page, dict):
            continue
        slug = page.get("slug", "")
        if slug in ("/", "", "home", "hem"):
            home_page = page
            home_idx = idx
            break

    if not home_page:
        # Fallback: use the first page if it has sections
        if isinstance(pages[0], dict) and pages[0].get("sections"):
            home_page = pages[0]
            home_idx = 0
        else:
            return

    sections = home_page.get("sections")
    if not isinstance(sections, list) or not sections:
        return

    # Build section_order from the page sections
    promoted_order = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        stype = section.get("type")
        sdata = section.get("data")
        if not stype or not isinstance(sdata, dict):
            continue
        if stype in _SECTION_KEYS:
            site_data[stype] = sdata
            promoted_order.append(stype)

    if promoted_order:
        # Update section_order to match what we promoted
        site_data["section_order"] = promoted_order
        # Remove the home page from pages since it's now at top level
        if home_idx is not None:
            pages.pop(home_idx)
        logger.info(
            "Promoted %d sections from pages[%s] to top level: %s",
            len(promoted_order), home_idx, promoted_order,
        )


# Mapping from custom-page slug patterns to the top-level section key they replace.
# Organized by language for i18n support. Add new languages as needed.
_SECTION_SLUGS_BY_LANG: dict[str, dict[str, list[str]]] = {
    "sv": {
        "about": ["om-oss", "om"],
        "services": ["tjanster", "vara-tjanster"],
        "gallery": ["galleri"],
        "faq": ["vanliga-fragor"],
    },
    "en": {
        "about": ["about-us"],
        "services": ["our-services"],
        "gallery": [],
        "faq": ["frequently-asked-questions"],
    },
}


def _build_slug_to_section_map() -> dict[str, str]:
    """Build a flat slug→section mapping from all languages."""
    mapping: dict[str, str] = {}
    for section_key in ("about", "services", "gallery", "faq"):
        # The English key itself always maps
        mapping[section_key] = section_key
        for _lang, sections in _SECTION_SLUGS_BY_LANG.items():
            for slug in sections.get(section_key, []):
                mapping[slug] = section_key
    return mapping


_PAGE_SLUG_TO_SECTION = _build_slug_to_section_map()


def _deduplicate_pages_vs_sections(site_data: dict) -> None:
    """Null out top-level sections when a custom page covers the same topic.

    This prevents duplicate navigation entries (e.g. standard "Om oss" link
    AND a custom "Om oss" page link).  The custom page is always preferred
    because it contains richer, site-specific content.

    Contact is intentionally excluded — the standard contact template is the
    default, and custom contact pages are opt-in.
    """
    pages = site_data.get("pages")
    if not isinstance(pages, list) or not pages:
        return

    page_slugs = {
        p.get("slug")
        for p in pages
        if isinstance(p, dict) and not p.get("parent_slug")
    }

    for slug in page_slugs:
        section_key = _PAGE_SLUG_TO_SECTION.get(slug)
        if section_key and site_data.get(section_key) is not None:
            logger.info(
                "Dedup: custom page '%s' covers section '%s' — nulling section",
                slug, section_key,
            )
            site_data[section_key] = None

    # Trim long page titles (strip " | BusinessName" pattern)
    for p in pages:
        if not isinstance(p, dict):
            continue
        title = p.get("title", "")
        if " | " in title:
            p["title"] = title.split(" | ")[0].strip()
        # Keep title short — max 30 chars
        if len(p.get("title", "")) > 30:
            p["title"] = p["title"][:29].rstrip() + "…"


def _sanitize_ai_output(site_data: dict) -> None:
    """Fix common AI generation issues before Pydantic validation.

    - Remove gallery images with null/empty URLs
    - Replace null strings with empty strings for required string fields
    """
    # Promote home-page sections from pages[] to top level if needed
    _promote_home_page_sections(site_data)

    # Remove gallery images missing a URL
    gallery = site_data.get("gallery")
    if isinstance(gallery, dict) and "images" in gallery:
        gallery["images"] = [
            img for img in gallery["images"]
            if isinstance(img, dict) and img.get("url")
        ]

    # Fix null strings in blocks that have required title/subtitle fields
    for block_key in ("stats", "testimonials", "faq", "features", "services",
                      "gallery", "process", "team", "about",
                      "pricing", "video", "logo_cloud", "custom_content",
                      "ranking"):
        block = site_data.get(block_key)
        if isinstance(block, dict):
            for str_field in ("title", "subtitle"):
                if str_field in block and block[str_field] is None:
                    block[str_field] = ""

    # Validate section_settings animation values
    valid_anims = {"fade-up", "fade-in", "slide-left", "slide-right", "scale", "none"}
    settings = site_data.get("section_settings")
    if isinstance(settings, dict):
        for _key, val in settings.items():
            if isinstance(val, dict) and val.get("animation") not in valid_anims:
                val["animation"] = "fade-up"

    # Deduplicate: if a custom page covers a standard section, null out the
    # top-level section so the viewer doesn't show both in navigation.
    _deduplicate_pages_vs_sections(site_data)


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
    industry_prompt_hint: str | None = None,
    industry_default_sections: list[str] | None = None,
    crawl_report: dict | None = None,
    blueprint: "SiteBlueprint | None" = None,
    context: str | None = None,
    is_freeform: bool = False,
) -> GenerationResult:
    """
    Generate a complete SiteSchema using an LLM.

    Optionally sends screenshots as images in the prompt for accurate
    color matching and design analysis.
    Retries once on invalid JSON.
    """
    # Resolve model: explicit override > platform setting > env default
    if model_override:
        model = model_override
    else:
        try:
            async with get_db_session() as db:
                model = await get_setting(db, "ai_model")
        except Exception:
            model = settings.AI_MODEL

    if blueprint and is_freeform:
        from app.ai.prompts import build_freeform_prompt
        system_prompt, user_prompt = build_freeform_prompt(
            blueprint=blueprint,
            business_name=business_name,
            context=context or "",
            email=email,
            colors=colors,
            logo_url=logo_url,
            images=images,
        )
    elif blueprint:
        from app.ai.prompts import build_blueprint_prompt
        system_prompt, user_prompt = build_blueprint_prompt(
            blueprint=blueprint,
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
            crawl_report=crawl_report,
        )
    else:
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
            industry_prompt_hint=industry_prompt_hint,
            industry_default_sections=industry_default_sections,
            crawl_report=crawl_report,
        )

    last_error = None
    for attempt in range(2):
        try:
            start = time.monotonic()

            if model in _GEMINI_MODELS:
                raw_json, input_tokens, output_tokens = await _call_gemini(
                    system_prompt, user_prompt, model,
                    screenshot_bytes=screenshot_bytes,
                )
            else:
                raw_json, input_tokens, output_tokens = await _call_anthropic(
                    system_prompt, user_prompt, model,
                    screenshot_bytes=screenshot_bytes,
                )

            duration_ms = int((time.monotonic() - start) * 1000)

            # Parse and validate
            site_data = json.loads(raw_json)

            # Extract install_apps before stripping unknown keys
            install_apps = site_data.pop("install_apps", [])
            if not isinstance(install_apps, list):
                install_apps = []
            install_apps = [s for s in install_apps if isinstance(s, str)]

            _strip_unknown_keys(site_data)
            _sanitize_ai_output(site_data)

            # Assign a random style variant for visual variety.
            # The AI doesn't control this — it's pure backend randomization.
            site_data["style_variant"] = random.randint(0, TOTAL_STYLE_VARIANTS - 1)

            # Stamp the current viewer version so this site is locked to it.
            site_data["viewer_version"] = CURRENT_VIEWER_VERSION

            site_schema = SiteSchema(**site_data)

            total_tokens = input_tokens + output_tokens
            input_cost_per_m = _INPUT_COST_PER_1M.get(model, 1.0)
            output_cost_per_m = _OUTPUT_COST_PER_1M.get(model, 5.0)
            cost = (input_tokens / 1_000_000) * input_cost_per_m + (output_tokens / 1_000_000) * output_cost_per_m

            logger.info(
                "Site generated: model=%s in=%d out=%d cost=$%.4f duration=%dms attempt=%d",
                model, input_tokens, output_tokens, cost, duration_ms, attempt + 1,
            )

            return GenerationResult(
                site_schema=site_schema,
                tokens_used=total_tokens,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                model=model,
                cost_usd=round(cost, 6),
                duration_ms=duration_ms,
                install_apps=install_apps,
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
) -> tuple[str, int, int]:
    """Call Anthropic API with optional screenshot images. Returns (json_string, input_tokens, output_tokens)."""

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

    payload = {
        "model": model,
        "max_tokens": 16000,
        "system": [
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [{"role": "user", "content": user_content}],
        "temperature": 0.5,
    }

    async def _do_request():
        client = _get_http_client()
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        if resp.status_code != 200:
            body = resp.text[:500]
            if "credit balance" in body.lower():
                raise RuntimeError(
                    "Anthropic API: insufficient credits. "
                    "Check that your ANTHROPIC_API_KEY belongs to the workspace where you added credits."
                )
            resp.raise_for_status()
        return resp

    resp = await _retry_api_call(_do_request)
    data = resp.json()

    content = data["content"][0]["text"]
    # Extract JSON from potential markdown code blocks
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].split("```")[0].strip()

    return content, data["usage"]["input_tokens"], data["usage"]["output_tokens"]


async def _call_gemini(
    system: str,
    user: str,
    model: str,
    screenshot_bytes: list[dict] | None = None,
) -> tuple[str, int, int]:
    """Call Google Gemini API. Returns (json_string, input_tokens, output_tokens)."""

    # Build parts array
    parts: list[dict] = []

    if screenshot_bytes:
        for shot in screenshot_bytes[:3]:
            img_bytes = shot.get("bytes")
            if not img_bytes or len(img_bytes) == 0:
                continue
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            parts.append({
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": b64,
                },
            })

    parts.append({"text": user})

    api_key = settings.GOOGLE_AI_API_KEY
    if not api_key:
        raise RuntimeError("GOOGLE_AI_API_KEY is not configured")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": 0.5,
            "maxOutputTokens": 16000,
            "responseMimeType": "application/json",
        },
    }

    async def _do_request():
        client = _get_http_client()
        resp = await client.post(
            url,
            headers={"Content-Type": "application/json"},
            json=payload,
        )
        if resp.status_code != 200:
            resp.raise_for_status()
        return resp

    resp = await _retry_api_call(_do_request)
    data = resp.json()
    content = data["candidates"][0]["content"]["parts"][0]["text"]

    # Extract JSON from potential markdown code blocks
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].split("```")[0].strip()

    usage = data.get("usageMetadata", {})
    input_tokens = usage.get("promptTokenCount", 0)
    output_tokens = usage.get("candidatesTokenCount", 0)

    return content, input_tokens, output_tokens
