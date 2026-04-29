"""
AI-powered blog post generator for the auto-blog system.

Reads ALL brand guidelines (VOICE, STATS, STORIES, OPINIONS, HUMOUR, on-page-seo)
and generates fully SEO-optimized blog posts covering all 15 on-page SEO categories.

Uses the Anthropic Claude API via httpx with retry logic.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from math import ceil
from pathlib import Path

import httpx

from app.config import settings
from app.auto_blog.config import (
    AI_MODEL,
    BRAND_DIR,
    DEFAULT_LANGUAGE,
    WORD_COUNT_TARGET,
    get_hreflang_map,
    get_language_codes,
)
from app.auto_blog.schemas import (
    AuthorInfo,
    BlogPostContent,
    BlogPostMeta,
    BreadcrumbItem,
    ExternalLink,
    FAQItem,
    InternalLink,
    OpenGraphData,
    TOCEntry,
)

logger = logging.getLogger(__name__)

# --- Shared HTTP client ------------------------------------------------------
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=240.0,
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
                keepalive_expiry=60,
            ),
        )
    return _http_client


async def close_http_client() -> None:
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None


# --- Brand guidelines loader -------------------------------------------------

_BRAND_FILES = [
    "VOICE.md",
    "STATS.md",
    "STORIES.md",
    "OPINIONS.md",
    "HUMOUR.md",
    "on-page-seo.md",
]


def _load_brand_file(filename: str) -> str:
    """Read a single brand file if it exists and has content."""
    path = BRAND_DIR / filename
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8").strip()
    if not content or _is_empty_template(content):
        return ""
    return content


def _load_all_brand_guidelines() -> str:
    """Read ALL brand markdown files and return as a combined context string."""
    sections: list[str] = []
    for fname in _BRAND_FILES:
        content = _load_brand_file(fname)
        if content:
            sections.append(f"=== {fname} ===\n{content}")
    return "\n\n" + "\n\n".join(sections) + "\n" if sections else ""


def _is_empty_template(content: str) -> bool:
    """Check if a brand file is still just the empty template."""
    cleaned = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)
    cleaned = re.sub(r"^#+\s+.*$", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"- \[[ x]\].*$", "", cleaned, flags=re.MULTILINE)
    cleaned = cleaned.strip()
    return len(cleaned) == 0


# --- Retry helper ------------------------------------------------------------
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}
_MAX_API_RETRIES = 3
_BASE_BACKOFF_SECONDS = 2.0


async def _retry_api_call(call_fn, *, max_retries: int = _MAX_API_RETRIES):
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return await call_fn()
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status in _RETRYABLE_STATUS_CODES:
                retry_after = e.response.headers.get("retry-after")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else _BASE_BACKOFF_SECONDS * (2 ** attempt)
                logger.warning("API %d, retry in %.1fs (%d/%d)", status, wait, attempt + 1, max_retries)
                last_exc = e
                await asyncio.sleep(wait)
                continue
            raise
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            wait = _BASE_BACKOFF_SECONDS * (2 ** attempt)
            logger.warning("API network error (%s), retry in %.1fs (%d/%d)", type(e).__name__, wait, attempt + 1, max_retries)
            last_exc = e
            await asyncio.sleep(wait)

    raise RuntimeError(f"API call failed after {max_retries} retries: {last_exc}")


# --- Language name helper ----------------------------------------------------

_LANGUAGE_NAMES = {
    "en": "English", "sv": "Swedish", "de": "German", "fr": "French",
    "es": "Spanish", "it": "Italian", "pt": "Portuguese", "nl": "Dutch",
    "da": "Danish", "no": "Norwegian", "fi": "Finnish", "pl": "Polish",
    "ja": "Japanese", "ko": "Korean", "zh": "Chinese", "ar": "Arabic",
}


def _lang_name(code: str) -> str:
    return _LANGUAGE_NAMES.get(code, code)


# --- Prompts -----------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a world-class SEO content strategist and blog writer. You produce \
long-form, fully SEO-optimized blog posts that satisfy every item in the \
on-page SEO checklist provided below.

You have deep expertise in E-E-A-T (Experience, Expertise, Authority, Trust), \
semantic HTML5, JSON-LD structured data, and accessibility best practices.

You MUST respond with a single valid JSON object and NOTHING else — no markdown \
fences, no explanation, no text outside the JSON."""


_USER_PROMPT_TEMPLATE = """\
Write a comprehensive, fully SEO-optimized blog post following EVERY rule below.

═══════════════════════════════════════════════════════════
TOPIC: {topic}
TARGET KEYWORDS: {keywords}
LANGUAGE: Write the ENTIRE post in {language_name} ({language_code})
TARGET WORD COUNT: minimum {word_count_target} words (aim for 1500+)
DATE: {date_today}
═══════════════════════════════════════════════════════════

{brand_guidelines}

═══════════════════════════════════════════════════════════
MANDATORY SEO REQUIREMENTS — follow every single point:
═══════════════════════════════════════════════════════════

1. HEAD & METADATA
   - "meta_title": 50-60 chars, primary keyword near the start.
   - "meta_description": 150-160 chars, keyword + benefit + soft CTA.
   - "og_title", "og_description" (can differ from meta for social appeal).

2. URL / SLUG
   - "slug": under 60 chars, primary keyword, hyphens only, lowercase, no stop words.

3. HEADINGS
   - The "title" field is the H1 — include primary keyword.
   - Use logical H2 → H3 hierarchy in "content". Never skip levels.
   - H2s should use supporting keywords and questions.
   - Add an `id` attribute to every H2 for anchor links (e.g. `<h2 id="what-is-seo">`).

4. COPY & BODY
   - First paragraph answers the query directly.
   - Short paragraphs: 2-4 sentences max.
   - Bold key takeaways with <strong>.
   - Use <ul>/<ol> lists for scannable content.
   - Use bucket brigades and transition phrases.
   - Minimum {word_count_target} words.

5. FAQ SECTION (MANDATORY)
   - Include 4-6 FAQ questions at the end of "content" inside a section:
     `<section id="faq" aria-label="Frequently Asked Questions"><h2>FAQ</h2>...`
   - Also return them in the "faq" array for JSON-LD schema generation.
   - Each answer: 2-4 sentences, direct.

6. IMAGES (references in content)
   - When referencing images use descriptive alt text with keywords.
   - Suggest filenames like `topic-keyword.webp`.
   - Add `loading="lazy"` for below-fold images.
   - Always include width and height attributes.

7. INTERNAL LINKS (3-5)
   - Return an "internal_links" array with descriptive anchor text.
   - In the "content" HTML, include 3-5 `<a href="...">descriptive anchor</a>` internal links.
   - Never use "click here" or "read more" as anchor text.

8. EXTERNAL LINKS (2-3)
   - Return an "external_links" array.
   - In "content", include 2-3 links to authoritative sources (.gov, .edu, major industry).
   - All external links must have `target="_blank" rel="noopener"`.

9. SCHEMA MARKUP — return these as JSON objects:
   - "schema_article": BlogPosting with headline, description, author, datePublished, inLanguage, wordCount.
   - "schema_faq": FAQPage with all FAQ items as mainEntity.
   - "schema_breadcrumb": BreadcrumbList with Home > Blog > [Post Title].
   - "schema_author": Person with name, url, description.

10. E-E-A-T SIGNALS
    - Author byline displayed in content.
    - Published date included.
    - Cite authoritative sources inline.
    - Use real stories, numbers, opinions from the brand voice files.
    - Write with genuine expertise — not generic fluff.

11. ACCESSIBILITY
    - Use semantic HTML5: <article>, <section>, <nav>, <aside> where appropriate.
    - ARIA labels on the FAQ section.
    - Descriptive link text everywhere.
    - Alt text on all image references.

12. TABLE OF CONTENTS
    - Return a "toc" array with id, text, level for every H2 and H3.
    - These will be rendered as jump links at the top of the post.

═══════════════════════════════════════════════════════════
RETURN FORMAT — a single JSON object with these exact keys:
═══════════════════════════════════════════════════════════

{{
  "title": "H1 title in {language_name} — 50-70 chars, primary keyword near start",
  "slug": "keyword-focused-slug-lowercase-hyphens",
  "excerpt": "2-3 sentence summary in {language_name}",
  "meta_title": "SEO title in {language_name} — 50-60 chars, primary keyword first",
  "meta_description": "SEO description in {language_name} — 150-160 chars, keyword + benefit + CTA",
  "og_title": "Compelling social title in {language_name}",
  "og_description": "Social description in {language_name} — can differ from meta",
  "primary_keyword": "the main keyword",
  "secondary_keywords": ["keyword2", "keyword3", "keyword4"],
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
  "featured_image_alt": "Descriptive alt text for the featured image with keyword",
  "content": "<article>FULL HTML BLOG POST with semantic tags, anchor IDs on H2s, internal links, external links, FAQ section at end</article>",
  "toc": [
    {{"id": "heading-anchor-id", "text": "Heading Text", "level": 2}},
    {{"id": "sub-heading-id", "text": "Sub Heading", "level": 3}}
  ],
  "faq": [
    {{"question": "Question in {language_name}?", "answer": "Direct 2-4 sentence answer."}},
    {{"question": "Another question?", "answer": "Another answer."}}
  ],
  "internal_links": [
    {{"anchor_text": "descriptive anchor text", "suggested_url": "/blog/related-topic", "context": "sentence context"}}
  ],
  "external_links": [
    {{"anchor_text": "source name", "url": "https://authoritative-source.com/page", "rel": "noopener"}}
  ],
  "schema_article": {{
    "@context": "https://schema.org",
    "@type": "BlogPosting",
    "headline": "...",
    "description": "...",
    "author": {{"@type": "Person", "name": "{author_name}", "url": "{author_url}"}},
    "datePublished": "{date_today}",
    "dateModified": "{date_today}",
    "inLanguage": "{language_code}",
    "wordCount": 1500,
    "mainEntityOfPage": {{"@type": "WebPage", "@id": "/{language_code}/blog/SLUG"}}
  }},
  "schema_faq": {{
    "@context": "https://schema.org",
    "@type": "FAQPage",
    "mainEntity": [
      {{
        "@type": "Question",
        "name": "Question?",
        "acceptedAnswer": {{"@type": "Answer", "text": "Answer."}}
      }}
    ]
  }},
  "schema_breadcrumb": {{
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    "itemListElement": [
      {{"@type": "ListItem", "position": 1, "name": "Home", "item": "/"}},
      {{"@type": "ListItem", "position": 2, "name": "Blog", "item": "/{language_code}/blog"}},
      {{"@type": "ListItem", "position": 3, "name": "Post Title", "item": "/{language_code}/blog/SLUG"}}
    ]
  }},
  "schema_author": {{
    "@context": "https://schema.org",
    "@type": "Person",
    "name": "{author_name}",
    "url": "{author_url}",
    "description": "{author_bio}"
  }}
}}

CRITICAL RULES:
- ALL text content MUST be in {language_name}.
- "content" MUST be valid semantic HTML5 with <article> wrapper.
- Every H2 MUST have a unique id attribute for anchor links.
- Include the FAQ section inside "content" AND in the "faq" array.
- External links in content MUST have target="_blank" rel="noopener".
- Minimum {word_count_target} words in the body content.
- Return ONLY the JSON object, absolutely no other text."""


# --- Robust JSON parsing -----------------------------------------------------

def _parse_json_robust(text: str) -> dict:
    """Parse JSON with fallback repair for common AI generation issues.

    Handles: trailing commas, unescaped newlines in strings, truncated output.
    """
    # First try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Remove trailing commas before } or ]
    repaired = re.sub(r",\s*([\]}])", r"\1", text)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    # Try to fix unescaped control characters inside string values
    # Replace literal newlines/tabs inside JSON strings
    def _escape_string_contents(m: re.Match) -> str:
        s = m.group(0)
        inner = s[1:-1]  # strip surrounding quotes
        inner = inner.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
        return f'"{inner}"'

    repaired2 = re.sub(
        r'"(?:[^"\\]|\\.)*"',
        _escape_string_contents,
        repaired,
        flags=re.DOTALL,
    )
    try:
        return json.loads(repaired2)
    except json.JSONDecodeError:
        pass

    # If the JSON is truncated (stop_reason=max_tokens), try to close it
    # Count unclosed braces/brackets and close them
    open_braces = repaired2.count("{") - repaired2.count("}")
    open_brackets = repaired2.count("[") - repaired2.count("]")
    suffix = "]" * max(open_brackets, 0) + "}" * max(open_braces, 0)
    if suffix:
        try:
            return json.loads(repaired2 + suffix)
        except json.JSONDecodeError:
            pass

    # Last resort: raise with helpful context
    # Find the error position
    try:
        json.loads(text)
    except json.JSONDecodeError as e:
        # Show context around the error
        start = max(0, e.pos - 100)
        end = min(len(text), e.pos + 100)
        context = text[start:end]
        raise ValueError(
            f"Failed to parse AI JSON response: {e.msg} at position {e.pos}. "
            f"Context: ...{context}..."
        ) from e

    raise ValueError("Failed to parse AI JSON response after all repair attempts")


# --- Core generation ---------------------------------------------------------

async def generate_post_for_language(
    topic: str,
    keywords: list[str],
    language: str,
    word_count: int | None = None,
    ai_model: str | None = None,
    author_name: str = "Qvicko",
    author_bio: str = "",
    author_url: str = "/about",
) -> BlogPostContent:
    """Generate a single blog post in one language with full SEO compliance."""
    brand_guidelines = _load_all_brand_guidelines()
    model = ai_model or AI_MODEL
    wc = max(word_count or WORD_COUNT_TARGET, 1500)  # enforce minimum 1500
    keywords_str = ", ".join(keywords) if keywords else topic
    date_today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    user_prompt = _USER_PROMPT_TEMPLATE.format(
        topic=topic,
        keywords=keywords_str,
        language_name=_lang_name(language),
        language_code=language,
        word_count_target=wc,
        brand_guidelines=brand_guidelines,
        date_today=date_today,
        author_name=author_name,
        author_bio=author_bio or f"Content team at {author_name}",
        author_url=author_url,
    )

    client = _get_http_client()

    async def _call():
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 16000,
                "system": _SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_prompt}],
            },
        )
        resp.raise_for_status()
        return resp.json()

    start = time.monotonic()
    result = await _retry_api_call(_call)
    duration = time.monotonic() - start

    stop_reason = result.get("stop_reason", "unknown")
    if stop_reason == "max_tokens":
        logger.warning("AI response truncated (max_tokens) for [%s] — output may be incomplete", language)

    # Parse response — with repair for common AI JSON issues
    raw_text = result["content"][0]["text"]
    raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text.strip())
    raw_text = re.sub(r"\s*```$", "", raw_text.strip())

    data = _parse_json_robust(raw_text)

    # Extract fields
    slug = data["slug"]
    content_html = data["content"]
    word_count_actual = len(re.findall(r"\w+", re.sub(r"<[^>]+>", "", content_html)))
    reading_time = max(1, ceil(word_count_actual / 250))

    hreflang_links = get_hreflang_map(slug)
    canonical = f"/{language}/blog/{slug}"

    # Build breadcrumbs
    blog_label = "Blogg" if language == "sv" else "Blog"
    home_label = "Hem" if language == "sv" else "Home"
    breadcrumbs = [
        BreadcrumbItem(name=home_label, url=f"/{language}"),
        BreadcrumbItem(name=blog_label, url=f"/{language}/blog"),
        BreadcrumbItem(name=data["title"], url=canonical),
    ]

    # Build TOC
    toc = [TOCEntry(id=t["id"], text=t["text"], level=t.get("level", 2)) for t in data.get("toc", [])]

    # Build FAQ
    faq = [FAQItem(question=f["question"], answer=f["answer"]) for f in data.get("faq", [])]

    # Build links
    internal_links = [
        InternalLink(
            anchor_text=l["anchor_text"],
            suggested_url=l["suggested_url"],
            context=l.get("context", ""),
        )
        for l in data.get("internal_links", [])
    ]
    external_links = [
        ExternalLink(
            anchor_text=l["anchor_text"],
            url=l["url"],
            rel=l.get("rel", "noopener"),
        )
        for l in data.get("external_links", [])
    ]

    # Build OG data
    open_graph = OpenGraphData(
        og_title=data.get("og_title", data["meta_title"]),
        og_description=data.get("og_description", data["meta_description"]),
        og_type="article",
        twitter_card="summary_large_image",
    )

    # Build author
    author = AuthorInfo(
        name=author_name,
        bio=author_bio or data.get("schema_author", {}).get("description", ""),
        url=author_url,
    )

    meta = BlogPostMeta(
        title=data["title"],
        slug=slug,
        locale=language,
        excerpt=data["excerpt"],
        meta_title=data["meta_title"],
        meta_description=data["meta_description"],
        canonical_url=canonical,
        open_graph=open_graph,
        author=author,
        published_at=date_today,
        updated_at=date_today,
        reading_time_minutes=reading_time,
        word_count=word_count_actual,
        featured_image_alt=data.get("featured_image_alt", ""),
        tags=data.get("tags", []),
        primary_keyword=data.get("primary_keyword", keywords[0] if keywords else topic),
        secondary_keywords=data.get("secondary_keywords", []),
        toc=toc,
        faq=faq,
        internal_links=internal_links,
        external_links=external_links,
        breadcrumbs=breadcrumbs,
        hreflang_links=hreflang_links,
        schema_article=data.get("schema_article", {}),
        schema_faq=data.get("schema_faq", {}),
        schema_breadcrumb=data.get("schema_breadcrumb", {}),
        schema_author=data.get("schema_author", {}),
    )

    logger.info(
        "Generated SEO post [%s] '%s' (%d words, %d FAQ, %d TOC, %.1fs, model=%s)",
        language, data["title"], word_count_actual, len(faq), len(toc), duration, model,
    )

    return BlogPostContent(meta=meta, content=content_html)


async def generate_post_all_languages(
    topic: str,
    keywords: list[str],
    languages: list[str] | None = None,
    word_count: int | None = None,
    author_name: str = "Qvicko",
    author_bio: str = "",
    author_url: str = "/about",
) -> list[BlogPostContent]:
    """Generate a blog post in all specified languages (or all configured)."""
    langs = languages or get_language_codes()

    tasks = [
        generate_post_for_language(
            topic, keywords, lang, word_count,
            author_name=author_name,
            author_bio=author_bio,
            author_url=author_url,
        )
        for lang in langs
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    posts: list[BlogPostContent] = []
    for lang, result in zip(langs, results):
        if isinstance(result, Exception):
            logger.error("Failed to generate post in %s: %s", lang, result)
        else:
            posts.append(result)

    if not posts:
        raise RuntimeError("Failed to generate post in any language")

    # Normalize: all posts share the default language's slug for hreflang
    default_post = next((p for p in posts if p.meta.locale == DEFAULT_LANGUAGE), posts[0])
    canonical_slug = default_post.meta.slug

    for post in posts:
        post.meta.slug = canonical_slug
        post.meta.canonical_url = f"/{post.meta.locale}/blog/{canonical_slug}"
        post.meta.hreflang_links = get_hreflang_map(canonical_slug)

        # Fix schema URLs with correct slug
        if post.meta.schema_article:
            mep = post.meta.schema_article.get("mainEntityOfPage", {})
            if isinstance(mep, dict):
                mep["@id"] = f"/{post.meta.locale}/blog/{canonical_slug}"
        if post.meta.schema_breadcrumb:
            items = post.meta.schema_breadcrumb.get("itemListElement", [])
            if items and len(items) >= 3:
                items[-1]["item"] = f"/{post.meta.locale}/blog/{canonical_slug}"
                items[-1]["name"] = post.meta.title

        # Rebuild breadcrumbs with correct slug
        blog_label = "Blogg" if post.meta.locale == "sv" else "Blog"
        home_label = "Hem" if post.meta.locale == "sv" else "Home"
        post.meta.breadcrumbs = [
            BreadcrumbItem(name=home_label, url=f"/{post.meta.locale}"),
            BreadcrumbItem(name=blog_label, url=f"/{post.meta.locale}/blog"),
            BreadcrumbItem(name=post.meta.title, url=f"/{post.meta.locale}/blog/{canonical_slug}"),
        ]

    return posts
