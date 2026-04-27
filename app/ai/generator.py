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

# Fuzzy keywords: if a page slug contains any of these, it covers the section.
_SECTION_FUZZY_KEYWORDS: dict[str, list[str]] = {
    "about": ["om-oss", "om-", "about"],
    "services": ["tjanst", "service"],
    "gallery": ["galler", "portfolio"],
    "faq": ["faq", "fragor"],
    "contact": ["kontakt", "contact"],
}


def _deduplicate_pages_vs_sections(site_data: dict) -> None:
    """Null out top-level sections when a custom page covers the same topic.

    The custom page is always preferred because it contains richer,
    site-specific content.  Uses exact slug match first, then fuzzy keyword
    match as fallback.
    """
    pages = site_data.get("pages")
    if not isinstance(pages, list) or not pages:
        return

    top_level_slugs = [
        p.get("slug", "")
        for p in pages
        if isinstance(p, dict) and not p.get("parent_slug")
    ]

    # For each standard section, check if ANY custom page covers it
    for section_key in ("about", "services", "gallery", "faq", "contact"):
        if site_data.get(section_key) is None:
            continue  # Already null

        matched = False
        for slug in top_level_slugs:
            # Exact slug match
            if _PAGE_SLUG_TO_SECTION.get(slug) == section_key:
                matched = True
                break
            # Fuzzy keyword match
            keywords = _SECTION_FUZZY_KEYWORDS.get(section_key, [])
            if any(kw in slug for kw in keywords):
                matched = True
                break

        if matched:
            logger.info("Dedup: custom page covers '%s' — nulling section", section_key)
            site_data[section_key] = None

    # Clean up page data
    for p in pages:
        if not isinstance(p, dict):
            continue
        # Strip leading slashes from slugs (AI sometimes writes "/om-oss" instead of "om-oss")
        # A leading slash in a slug causes "//om-oss" → protocol-relative URL → broken link
        slug = p.get("slug", "")
        if slug.startswith("/"):
            p["slug"] = slug.lstrip("/")
        parent = p.get("parent_slug")
        if isinstance(parent, str) and parent.startswith("/"):
            p["parent_slug"] = parent.lstrip("/")

        # Trim long page titles (strip " | BusinessName" pattern)
        title = p.get("title", "")
        if " | " in title:
            p["title"] = title.split(" | ")[0].strip()
        # Keep title short — max 30 chars
        if len(p.get("title", "")) > 30:
            p["title"] = p["title"][:29].rstrip() + "…"


# Standard routes that always exist in the viewer
_STANDARD_ROUTES = {
    "/about", "/services", "/gallery", "/faq", "/contact",
    "/blog", "/bookings", "/",
}


def _validate_cta_links(site_data: dict) -> None:
    """Validate all CTA/button hrefs in the generated site data.

    Checks that internal links (starting with /) point to either a standard
    route or a custom page slug defined in site_data['pages'].
    Invalid internal links are replaced with '/contact' as a safe fallback.
    External URLs (http/https/mailto/tel) are left as-is.
    """
    # Build set of valid internal paths
    valid_paths = set(_STANDARD_ROUTES)
    pages = site_data.get("pages")
    if isinstance(pages, list):
        for p in pages:
            if isinstance(p, dict):
                slug = p.get("slug", "")
                if slug:
                    valid_paths.add(f"/{slug}")
                    # Also allow parent/child paths
                    parent = p.get("parent_slug")
                    if parent:
                        valid_paths.add(f"/{parent}/{slug}")

    def _fix_href(href: str) -> str:
        """Return the href if valid, or a fallback."""
        if not href or not isinstance(href, str):
            return "/contact"
        href = href.strip()
        # External URLs, mailto:, tel: are always valid
        if href.startswith(("http://", "https://", "mailto:", "tel:")):
            return href
        # Anchor links are discouraged but not broken
        if href.startswith("#"):
            return "/contact"
        # Internal path — must match a known route or page slug
        if href.startswith("/"):
            if href in valid_paths:
                return href
            # Try without trailing slash
            normalized = href.rstrip("/")
            if normalized in valid_paths:
                return normalized
            logger.info("Validate links: invalid internal href '%s' — replacing with '/contact'", href)
            return "/contact"
        # Bare slug without leading slash — add slash and check
        with_slash = f"/{href}"
        if with_slash in valid_paths:
            return with_slash
        return "/contact"

    def _walk_and_fix(obj):
        """Recursively walk dicts/lists and fix any href fields in CTA/button objects."""
        if isinstance(obj, dict):
            # Fix href in CTA-like objects (have both label and href)
            if "href" in obj and ("label" in obj or "text" in obj):
                obj["href"] = _fix_href(obj["href"])
            # Recurse into all values
            for v in obj.values():
                _walk_and_fix(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk_and_fix(item)

    _walk_and_fix(site_data)


def _fix_toggle_consistency(site_data: dict) -> None:
    """Fix text/toggle inconsistencies in generated data.

    If the AI wrote text referencing a form but set show_form=false,
    the user sees text about a form but no form. This function fixes
    such contradictions by enabling the toggle.
    """
    # Fix contact section
    _fix_contact_toggles(site_data.get("contact"))

    # Fix contact sections inside pages
    pages = site_data.get("pages")
    if isinstance(pages, list):
        for page in pages:
            if not isinstance(page, dict):
                continue
            for section in (page.get("sections") or []):
                if isinstance(section, dict) and section.get("type") == "contact":
                    _fix_contact_toggles(section.get("data"))

    # Fix CTA section
    cta = site_data.get("cta")
    if isinstance(cta, dict):
        if cta.get("button") and cta.get("show_button") is False:
            logger.info("Fix toggle: CTA has button but show_button=false — enabling")
            cta["show_button"] = True

    # Fix hero CTA
    hero = site_data.get("hero")
    if isinstance(hero, dict):
        if hero.get("cta") and hero.get("show_cta") is False:
            logger.info("Fix toggle: Hero has CTA but show_cta=false — enabling")
            hero["show_cta"] = True


def _fix_contact_toggles(contact: dict | None) -> None:
    """Fix contact section toggle inconsistencies."""
    if not isinstance(contact, dict):
        return

    text = (contact.get("text") or "").lower()

    # If text mentions form but show_form is false
    form_keywords = ["formulär", "form", "fyll i", "skicka meddelande", "skriv till oss"]
    if any(kw in text for kw in form_keywords) and contact.get("show_form") is False:
        logger.info("Fix toggle: Contact text mentions form but show_form=false — enabling")
        contact["show_form"] = True

    # If text mentions phone/contact info but show_info is false
    info_keywords = ["ring", "telefon", "mejla", "besök", "adress"]
    if any(kw in text for kw in info_keywords) and contact.get("show_info") is False:
        logger.info("Fix toggle: Contact text mentions info but show_info=false — enabling")
        contact["show_info"] = True

    # If both show_form and show_info are explicitly false, enable form as default
    if contact.get("show_form") is False and contact.get("show_info") is False:
        logger.info("Fix toggle: Both show_form and show_info are false — enabling show_form")
        contact["show_form"] = True


def _sanitize_ai_output(site_data: dict, *, original_logo_url: str | None = None) -> None:
    """Fix common AI generation issues before Pydantic validation.

    - Remove gallery images with null/empty URLs
    - Replace null strings with empty strings for required string fields
    - Validate logo_url against the original input
    """
    # Promote home-page sections from pages[] to top level if needed
    _promote_home_page_sections(site_data)

    # Validate logo: if no logo was provided to the generator, the AI must not
    # use a page image as logo.  Null it out so the viewer shows business name.
    branding = site_data.get("branding")
    if isinstance(branding, dict):
        ai_logo = branding.get("logo_url")
        if ai_logo and not original_logo_url:
            # AI invented a logo from page images — remove it
            logger.info("Sanitize: AI set logo_url but no logo was provided — clearing")
            branding["logo_url"] = None
        elif ai_logo and original_logo_url and ai_logo != original_logo_url:
            # AI replaced the real logo with a different image — restore
            logger.info("Sanitize: AI changed logo_url — restoring original")
            branding["logo_url"] = original_logo_url

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

    # Validate CTA hrefs — ensure all internal links point to real pages/routes
    _validate_cta_links(site_data)

    # Fix text/toggle inconsistencies
    _fix_toggle_consistency(site_data)


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
            _sanitize_ai_output(site_data, original_logo_url=logo_url)

            # Auto-generate SEO fields from content
            from app.ai.seo_generator import generate_seo
            generate_seo(site_data)

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


# ---------------------------------------------------------------------------
# Orchestrated multi-call generation
# ---------------------------------------------------------------------------

_ORCHESTRATOR_SEMAPHORE = asyncio.Semaphore(4)


async def orchestrate_site_generation(
    blueprint: "SiteBlueprint",
    business_name: str,
    industry: str | None = None,
    website_url: str = "",
    email: str | None = None,
    phone: str | None = None,
    address: str | None = None,
    texts: dict | None = None,
    colors: dict | None = None,
    services: list | None = None,
    logo_url: str | None = None,
    social_links: dict | None = None,
    images: list | None = None,
    visual_analysis: dict | None = None,
    model_override: str | None = None,
    screenshot_bytes: list[dict] | None = None,
    crawl_report: dict | None = None,
    context: str | None = None,
    is_freeform: bool = False,
) -> GenerationResult:
    """Orchestrated generation: 1 LLM call for homepage + 1 per sub-page.

    Produces higher quality by giving each page full AI attention.
    Falls back to single-call generate_site() if orchestration fails.
    """
    from app.ai.prompts import build_homepage_prompt, build_page_prompt

    # Resolve model
    if model_override:
        model = model_override
    else:
        try:
            async with get_db_session() as db:
                model = await get_setting(db, "ai_model")
        except Exception:
            model = settings.AI_MODEL

    is_gemini = model in _GEMINI_MODELS
    total_input = 0
    total_output = 0
    start = time.monotonic()

    # --- Step 1: Generate homepage ---
    homepage_system, homepage_user = build_homepage_prompt(
        blueprint=blueprint,
        business_name=business_name,
        email=email,
        phone=phone,
        address=address,
        colors=colors,
        logo_url=logo_url,
        social_links=social_links,
        images=images,
        visual_analysis=visual_analysis,
        texts=texts,
        services=services,
        context=context,
        crawl_report=crawl_report,
        industry=industry,
    )

    homepage_data = await _call_and_parse(
        homepage_system, homepage_user, model, is_gemini,
        screenshot_bytes=screenshot_bytes,
        max_tokens=8000,
    )
    total_input += homepage_data["_input_tokens"]
    total_output += homepage_data["_output_tokens"]
    del homepage_data["_input_tokens"]
    del homepage_data["_output_tokens"]

    logger.info(
        "Orchestrator: homepage generated, sections=%s",
        homepage_data.get("section_order", []),
    )

    # Extract install_apps from homepage
    install_apps = homepage_data.pop("install_apps", [])
    if not isinstance(install_apps, list):
        install_apps = []

    # --- Step 2: Generate sub-pages in parallel ---
    page_results: list[dict] = []

    if blueprint.pages_plan:
        all_slugs = [pp.slug for pp in blueprint.pages_plan]

        async def _gen_page(pp):
            async with _ORCHESTRATOR_SEMAPHORE:
                page_sys, page_usr = build_page_prompt(
                    page_plan=pp,
                    blueprint=blueprint,
                    business_name=business_name,
                    images=images,
                    context=context,
                    texts=texts,
                    services=services,
                    all_page_slugs=all_slugs,
                )
                try:
                    result = await _call_and_parse(
                        page_sys, page_usr, model, is_gemini,
                        max_tokens=5000,
                    )
                    return pp, result
                except Exception as e:
                    logger.warning("Orchestrator: page '%s' failed: %s", pp.slug, e)
                    return pp, None

        tasks = [_gen_page(pp) for pp in blueprint.pages_plan]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        for pp, result in results:
            if result is None:
                continue
            inp = result.pop("_input_tokens", 0)
            outp = result.pop("_output_tokens", 0)
            total_input += inp
            total_output += outp

            page_dict = {
                "slug": pp.slug,
                "title": pp.title,
                "sections": result.get("sections", []),
                "show_in_nav": True,
                "nav_order": len(page_results) + 1,
            }
            # Apply section_settings from page result
            if result.get("section_settings"):
                # Merge into homepage_data section_settings with page-prefixed keys
                ss = homepage_data.get("section_settings") or {}
                for k, v in result["section_settings"].items():
                    ss[f"{pp.slug}_{k}"] = v
                homepage_data["section_settings"] = ss

            page_results.append(page_dict)
            logger.info(
                "Orchestrator: page '%s' generated, sections=%d",
                pp.slug, len(page_dict["sections"]),
            )

    # --- Step 3: Assemble ---
    site_data = _assemble_site(homepage_data, page_results)

    # --- Step 4: SEO post-processor ---
    from app.ai.seo_generator import generate_seo
    generate_seo(site_data)

    # --- Step 5: Standard sanitization ---
    _strip_unknown_keys(site_data)
    _sanitize_ai_output(site_data, original_logo_url=logo_url)

    site_data["style_variant"] = random.randint(0, TOTAL_STYLE_VARIANTS - 1)
    site_data["viewer_version"] = CURRENT_VIEWER_VERSION

    site_schema = SiteSchema(**site_data)

    duration_ms = int((time.monotonic() - start) * 1000)
    total_tokens = total_input + total_output
    input_cost_per_m = _INPUT_COST_PER_1M.get(model, 1.0)
    output_cost_per_m = _OUTPUT_COST_PER_1M.get(model, 5.0)
    cost = (total_input / 1_000_000) * input_cost_per_m + (total_output / 1_000_000) * output_cost_per_m

    logger.info(
        "Orchestrator complete: pages=%d model=%s in=%d out=%d cost=$%.4f duration=%dms",
        len(page_results), model, total_input, total_output, cost, duration_ms,
    )

    return GenerationResult(
        site_schema=site_schema,
        tokens_used=total_tokens,
        input_tokens=total_input,
        output_tokens=total_output,
        model=model,
        cost_usd=round(cost, 6),
        duration_ms=duration_ms,
        install_apps=[s for s in install_apps if isinstance(s, str)],
    )


def _assemble_site(homepage_data: dict, page_results: list[dict]) -> dict:
    """Merge homepage + page results into a complete site_data dict."""
    site_data = dict(homepage_data)

    if page_results:
        site_data["pages"] = page_results

    # Ensure required top-level keys exist
    if "meta" not in site_data or not isinstance(site_data.get("meta"), dict):
        site_data["meta"] = {}
    if "seo" not in site_data or not isinstance(site_data.get("seo"), dict):
        site_data["seo"] = {}

    return site_data


async def _call_and_parse(
    system: str,
    user: str,
    model: str,
    is_gemini: bool,
    screenshot_bytes: list[dict] | None = None,
    max_tokens: int = 8000,
) -> dict:
    """Make an LLM call and parse the JSON result. Returns dict with _input_tokens/_output_tokens."""
    for attempt in range(2):
        try:
            if is_gemini:
                raw_json, inp, outp = await _call_gemini(system, user, model, screenshot_bytes=screenshot_bytes)
            else:
                raw_json, inp, outp = await _call_anthropic(system, user, model, screenshot_bytes=screenshot_bytes)

            data = json.loads(raw_json)
            data["_input_tokens"] = inp
            data["_output_tokens"] = outp
            return data

        except (json.JSONDecodeError, ValueError) as e:
            if attempt == 0:
                logger.warning("Orchestrator parse attempt %d failed: %s", attempt + 1, e)
                continue
            raise

    raise RuntimeError("Failed to parse LLM response after 2 attempts")


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
