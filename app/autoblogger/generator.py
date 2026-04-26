"""
AI-powered blog post generator using Anthropic Claude API.

Generates SEO-optimized blog posts with structured metadata.
Uses raw httpx with shared client pooling and retry logic.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from math import ceil

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# --- Shared HTTP client (connection pooling) ---------------------------------
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    """Return a shared httpx client with connection pooling."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=180.0,
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
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return await call_fn()
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status in _RETRYABLE_STATUS_CODES:
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
            raise
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


# --- Token cost tracking ----------------------------------------------------
_INPUT_COST_PER_1M: dict[str, float] = {
    "claude-haiku-4-5-20251001": 1.00,
    "claude-sonnet-4-20250514": 3.00,
}
_OUTPUT_COST_PER_1M: dict[str, float] = {
    "claude-haiku-4-5-20251001": 5.00,
    "claude-sonnet-4-20250514": 15.00,
}


# --- Result dataclass --------------------------------------------------------
@dataclass
class BlogGenerationResult:
    title: str
    slug: str
    content: str  # HTML
    excerpt: str
    meta_title: str
    meta_description: str
    tags: list[str]
    schema_markup: dict  # JSON-LD
    internal_links: list[dict]  # [{"anchor": "...", "suggested_topic": "..."}]
    word_count: int
    reading_time_minutes: int
    ai_model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    generation_prompt: str  # the prompt sent to Claude


# --- Prompt templates --------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert SEO blog writer and content strategist. You produce \
high-quality, engaging, well-structured blog posts optimized for search engines.

You MUST respond with a single valid JSON object and nothing else — no markdown \
fences, no explanation, no text outside the JSON."""

_USER_PROMPT_TEMPLATE = """\
Write a comprehensive, SEO-optimized blog post about the following topic.

Topic: {topic}
Target keywords: {keywords}
Language: {language}
Target word count: approximately {word_count_target} words
{brand_voice_section}
{title_section}
{internal_links_section}

REQUIREMENTS:
- Write the blog content as HTML using semantic tags: <h2>, <h3>, <p>, <ul>, <ol>, <li>, <strong>, <em>, <blockquote>. Do NOT include <h1> (the title is rendered separately).
- The content should be well-structured with clear headings, subheadings, and paragraphs.
- Naturally incorporate the target keywords without keyword stuffing.
- Write in the specified language ({language}).
- Make the content engaging, informative, and valuable to readers.

Return a JSON object with exactly these keys:
{{
  "title": "The blog post title (compelling, keyword-rich, max 80 chars)",
  "slug": "url-friendly-slug-derived-from-title",
  "content": "<h2>...</h2><p>...</p>... (the full HTML blog post body)",
  "excerpt": "A 2-3 sentence summary of the post for previews and meta purposes.",
  "meta_title": "SEO meta title (max 60 characters, include primary keyword)",
  "meta_description": "SEO meta description (max 160 characters, compelling with keyword)",
  "tags": ["tag1", "tag2", "tag3"],
  "schema_markup": {{ "JSON-LD Article schema object with @context, @type, headline, description, author, datePublished (use today's date placeholder YYYY-MM-DD)" }},
  "internal_links": [ {{ "anchor": "anchor text", "suggested_topic": "related post topic" }} ]
}}

IMPORTANT:
- The "content" value must be a valid HTML string.
- The "schema_markup" value must be a valid JSON-LD object (not a string).
- The "internal_links" array should contain 3-5 suggestions for internal linking.
- All text content must be in {language}.
- Return ONLY the JSON object, no other text."""


def _build_prompt(
    topic: str,
    keywords: list[str],
    language: str,
    brand_voice: str | None,
    word_count_target: int,
    title: str | None,
    existing_posts: list[str] | None,
) -> str:
    """Build the user prompt from parameters."""
    keywords_str = ", ".join(keywords) if keywords else topic

    if brand_voice:
        brand_voice_section = f"Brand voice / tone: {brand_voice}"
    else:
        brand_voice_section = ""

    if title:
        title_section = f'Use this exact title: "{title}"'
    else:
        title_section = "Generate a compelling, keyword-rich title."

    if existing_posts:
        posts_list = "\n".join(f"- {t}" for t in existing_posts[:20])
        internal_links_section = (
            "When generating internal_links, reference these existing posts "
            "where relevant:\n" + posts_list
        )
    else:
        internal_links_section = ""

    return _USER_PROMPT_TEMPLATE.format(
        topic=topic,
        keywords=keywords_str,
        language=language,
        word_count_target=word_count_target,
        brand_voice_section=brand_voice_section,
        title_section=title_section,
        internal_links_section=internal_links_section,
    )


# --- Helpers -----------------------------------------------------------------

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _count_words(html: str) -> int:
    """Strip HTML tags and count words."""
    text = _HTML_TAG_RE.sub(" ", html)
    return len(text.split())


def _extract_json(content: str) -> str:
    """Extract JSON from Claude's response, handling markdown fences."""
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].split("```")[0].strip()
    return content


# --- Main generation function ------------------------------------------------

async def generate_blog_post(
    topic: str,
    keywords: list[str],
    language: str = "en",
    brand_voice: str | None = None,
    word_count_target: int = 1200,
    ai_model: str = "claude-sonnet-4-20250514",
    title: str | None = None,
    existing_posts: list[str] | None = None,
) -> BlogGenerationResult:
    """Generate a complete blog post with SEO metadata using Claude.

    Args:
        topic: The blog post topic or subject.
        keywords: Target SEO keywords to incorporate.
        language: Language code for the content (e.g. "en", "es", "fr").
        brand_voice: Optional tone/style instructions.
        word_count_target: Approximate target word count.
        ai_model: The Claude model to use.
        title: Optional pre-set title (Claude will use it as-is).
        existing_posts: Titles of existing posts for internal linking suggestions.

    Returns:
        BlogGenerationResult with all generated content and metadata.
    """
    user_prompt = _build_prompt(
        topic=topic,
        keywords=keywords,
        language=language,
        brand_voice=brand_voice,
        word_count_target=word_count_target,
        title=title,
        existing_posts=existing_posts,
    )

    payload = {
        "model": ai_model,
        "max_tokens": 8192,
        "system": _SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_prompt}],
        "temperature": 0.7,
    }

    start = time.monotonic()

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
                    "Check that your ANTHROPIC_API_KEY belongs to the workspace "
                    "where you added credits."
                )
            resp.raise_for_status()
        return resp

    resp = await _retry_api_call(_do_request)
    data = resp.json()

    duration_ms = int((time.monotonic() - start) * 1000)

    # Extract and parse JSON from response
    raw_content = data["content"][0]["text"]
    json_str = _extract_json(raw_content)
    result = json.loads(json_str)

    # Extract fields with sensible defaults
    content_html = result.get("content", "")
    generated_title = result.get("title", topic)
    slug = result.get("slug", "")
    excerpt = result.get("excerpt", "")
    meta_title = result.get("meta_title", generated_title)[:60]
    meta_description = result.get("meta_description", excerpt)[:160]
    tags = result.get("tags", [])
    schema_markup = result.get("schema_markup", {})
    internal_links = result.get("internal_links", [])

    if not isinstance(tags, list):
        tags = []
    if not isinstance(schema_markup, dict):
        schema_markup = {}
    if not isinstance(internal_links, list):
        internal_links = []

    # Calculate metrics
    word_count = _count_words(content_html)
    reading_time = ceil(word_count / 200) if word_count > 0 else 1

    # Calculate cost
    input_tokens = data["usage"]["input_tokens"]
    output_tokens = data["usage"]["output_tokens"]
    input_cost_rate = _INPUT_COST_PER_1M.get(ai_model, 3.0)
    output_cost_rate = _OUTPUT_COST_PER_1M.get(ai_model, 15.0)
    cost = (
        (input_tokens / 1_000_000) * input_cost_rate
        + (output_tokens / 1_000_000) * output_cost_rate
    )

    logger.info(
        "Blog post generated: model=%s in=%d out=%d cost=$%.4f duration=%dms words=%d",
        ai_model, input_tokens, output_tokens, cost, duration_ms, word_count,
    )

    return BlogGenerationResult(
        title=generated_title,
        slug=slug,
        content=content_html,
        excerpt=excerpt,
        meta_title=meta_title,
        meta_description=meta_description,
        tags=tags,
        schema_markup=schema_markup,
        internal_links=internal_links,
        word_count=word_count,
        reading_time_minutes=reading_time,
        ai_model=ai_model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=round(cost, 6),
        generation_prompt=user_prompt,
    )
