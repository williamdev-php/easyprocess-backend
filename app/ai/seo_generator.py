"""
Auto-SEO post-processor.

Generates meta title, description, keywords, structured data, and per-page
meta fields from AI-generated content. Runs AFTER the AI generation so the
model can focus on creative content instead of SEO boilerplate.
"""

from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_seo(site_data: dict) -> None:
    """Populate SEO fields from existing content. Mutates site_data in-place.

    Called after AI generation but before Pydantic validation.
    Only fills fields that are missing or empty — never overwrites AI-provided
    SEO if the model happened to include it.
    """
    _ensure_meta(site_data)
    _generate_meta_title(site_data)
    _generate_meta_description(site_data)
    _generate_meta_keywords(site_data)
    _generate_structured_data(site_data)
    _generate_page_meta(site_data)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_meta(site_data: dict) -> None:
    """Ensure meta and seo dicts exist."""
    if not isinstance(site_data.get("meta"), dict):
        site_data["meta"] = {}
    if not isinstance(site_data.get("seo"), dict):
        site_data["seo"] = {}


def _truncate(text: str, max_len: int) -> str:
    """Truncate text to max_len, preferring sentence boundaries."""
    if not text or len(text) <= max_len:
        return text

    # Try to break at sentence boundary within limit
    candidate = text[:max_len]
    for end_char in (".", "!", "?"):
        last_sentence = candidate.rfind(end_char)
        if last_sentence > max_len // 3:  # At least 1/3 of max_len used
            return text[:last_sentence + 1]

    # Fallback: break at word boundary
    truncated = candidate.rsplit(" ", 1)[0]
    return truncated.rstrip(".,;: ") + "…"


def _extract_text(obj: dict | None, *keys: str) -> str:
    """Get the first non-empty string from nested dict keys."""
    if not isinstance(obj, dict):
        return ""
    for key in keys:
        val = obj.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _get_business_name(site_data: dict) -> str:
    biz = site_data.get("business") or {}
    return _extract_text(biz, "name") or "Untitled"


def _get_business_tagline(site_data: dict) -> str:
    biz = site_data.get("business") or {}
    return _extract_text(biz, "tagline")


# ---------------------------------------------------------------------------
# Meta title
# ---------------------------------------------------------------------------

def _generate_meta_title(site_data: dict) -> None:
    """Generate site-level meta title.

    This title is used as the SUFFIX in page titles by the viewer:
      "${page.title} | ${site.meta.title}"
    So it should be the business identity — not a full SEO sentence.
    """
    meta = site_data["meta"]
    if meta.get("title"):
        return  # AI already provided

    name = _get_business_name(site_data)
    tagline = _get_business_tagline(site_data)

    # Keep it short — this gets appended to every page title
    if tagline and len(f"{name} — {tagline}") <= 50:
        title = f"{name} — {tagline}"
    else:
        title = name

    meta["title"] = _truncate(title, 50)


# ---------------------------------------------------------------------------
# Meta description
# ---------------------------------------------------------------------------

def _generate_meta_description(site_data: dict) -> None:
    meta = site_data["meta"]
    if meta.get("description"):
        return

    # Try hero subtitle first — it's usually the best one-liner
    hero = site_data.get("hero") or {}
    subtitle = _extract_text(hero, "subtitle")

    about = site_data.get("about") or {}
    about_text = _extract_text(about, "text")

    if subtitle and about_text:
        # Combine subtitle + first sentence of about, avoid duplication
        first_sentence = re.split(r"[.!?]", about_text, maxsplit=1)[0].strip()
        if first_sentence and first_sentence.lower() != subtitle.lower():
            # Ensure subtitle ends with punctuation before joining
            sub = subtitle.rstrip(".")
            description = f"{sub}. {first_sentence}."
        else:
            description = subtitle if subtitle.endswith(".") else subtitle + "."
    elif subtitle:
        description = subtitle if subtitle.endswith(".") else subtitle + "."
    elif about_text:
        first_sentence = re.split(r"[.!?]", about_text, maxsplit=1)[0].strip()
        description = first_sentence + "." if first_sentence else ""
    else:
        tagline = _get_business_tagline(site_data)
        description = tagline + "." if tagline else ""

    if description:
        meta["description"] = _truncate(description, 160)


# ---------------------------------------------------------------------------
# Meta keywords
# ---------------------------------------------------------------------------

def _generate_meta_keywords(site_data: dict) -> None:
    meta = site_data["meta"]
    if meta.get("keywords"):
        return

    keywords: list[str] = []

    # Business name
    name = _get_business_name(site_data)
    if name and name != "Untitled":
        keywords.append(name.lower())

    # Service titles
    services = site_data.get("services") or {}
    for item in (services.get("items") or [])[:6]:
        title = _extract_text(item, "title")
        if title:
            keywords.append(title.lower())

    # Feature titles
    features = site_data.get("features") or {}
    for item in (features.get("items") or [])[:4]:
        title = _extract_text(item, "title")
        if title:
            keywords.append(title.lower())

    # FAQ questions — extract key nouns
    faq = site_data.get("faq") or {}
    for item in (faq.get("items") or [])[:3]:
        q = _extract_text(item, "question")
        if q:
            # Strip common question words
            cleaned = re.sub(
                r"^(vad|hur|vilka|varför|när|kan|är|har)\s+",
                "", q.lower(),
            )
            cleaned = cleaned.rstrip("?").strip()
            if cleaned and len(cleaned) < 40:
                keywords.append(cleaned)

    # Page titles from sub-pages
    pages = site_data.get("pages") or []
    for page in pages[:4]:
        if isinstance(page, dict):
            title = _extract_text(page, "title")
            if title and title.lower() not in keywords:
                keywords.append(title.lower())

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for kw in keywords:
        if kw not in seen:
            seen.add(kw)
            unique.append(kw)

    meta["keywords"] = unique[:15]


# ---------------------------------------------------------------------------
# Structured data (JSON-LD)
# ---------------------------------------------------------------------------

def _generate_structured_data(site_data: dict) -> None:
    seo = site_data["seo"]
    if seo.get("structured_data"):
        return

    biz = site_data.get("business") or {}
    meta = site_data.get("meta") or {}
    name = _extract_text(biz, "name") or "Untitled"

    graph: list[dict] = []

    # WebSite schema — always
    graph.append({
        "@type": "WebSite",
        "name": name,
        "url": "",  # Filled by viewer at render time
    })

    # LocalBusiness or Organization
    address = _extract_text(biz, "address")
    phone = _extract_text(biz, "phone")
    email = _extract_text(biz, "email")

    if address or phone:
        lb: dict = {
            "@type": "LocalBusiness",
            "name": name,
            "url": "",
        }
        if meta.get("description"):
            lb["description"] = meta["description"]
        if phone:
            lb["telephone"] = phone
        if email:
            lb["email"] = email
        if address:
            lb["address"] = {
                "@type": "PostalAddress",
                "streetAddress": address,
                "addressCountry": "SE",
            }

        # Logo
        branding = site_data.get("branding") or {}
        logo = _extract_text(branding, "logo_url")
        if logo:
            lb["logo"] = logo

        graph.append(lb)
    else:
        org: dict = {
            "@type": "Organization",
            "name": name,
            "url": "",
        }
        if email:
            org["contactPoint"] = {
                "@type": "ContactPoint",
                "email": email,
                "contactType": "customer service",
            }
        branding = site_data.get("branding") or {}
        logo = _extract_text(branding, "logo_url")
        if logo:
            org["logo"] = logo
        graph.append(org)

    # FAQPage — if FAQ section exists with items
    faq = site_data.get("faq") or {}
    faq_items = faq.get("items") or []
    if faq_items:
        faq_entities = []
        for item in faq_items:
            if not isinstance(item, dict):
                continue
            q = _extract_text(item, "question")
            a = _extract_text(item, "answer")
            if q and a:
                faq_entities.append({
                    "@type": "Question",
                    "name": q,
                    "acceptedAnswer": {
                        "@type": "Answer",
                        "text": a,
                    },
                })
        if faq_entities:
            graph.append({
                "@type": "FAQPage",
                "mainEntity": faq_entities,
            })

    seo["structured_data"] = {
        "@context": "https://schema.org",
        "@graph": graph,
    }


# ---------------------------------------------------------------------------
# Per-page meta
# ---------------------------------------------------------------------------

def _generate_page_meta(site_data: dict) -> None:
    """Generate meta title/description for each sub-page."""
    pages = site_data.get("pages")
    if not isinstance(pages, list):
        return

    biz_name = _get_business_name(site_data)

    for page in pages:
        if not isinstance(page, dict):
            continue

        if not isinstance(page.get("meta"), dict):
            page["meta"] = {}

        page_meta = page["meta"]
        page_title = _extract_text(page, "title")

        # Meta title — ONLY the page's own title, never business name.
        # The viewer combines: "${page.meta.title} | ${site.meta.title}"
        # so including business name here would cause duplication like:
        # "Kontakt | Firma AB | Firma AB | Tagline"
        if not page_meta.get("title"):
            if page_title:
                page_meta["title"] = _truncate(page_title, 40)

        # Meta description — extract from the page's first text-heavy section
        if not page_meta.get("description"):
            desc = _extract_page_description(page)
            if desc:
                page_meta["description"] = _truncate(desc, 160)


def _extract_page_description(page: dict) -> str:
    """Extract a description from the page's section content."""
    sections = page.get("sections")
    if not isinstance(sections, list):
        return ""

    for section in sections:
        if not isinstance(section, dict):
            continue
        data = section.get("data")
        if not isinstance(data, dict):
            continue

        stype = section.get("type", "")

        # Try text-heavy sections first
        if stype in ("about", "custom_content"):
            text = _extract_text(data, "text")
            if text:
                first = re.split(r"[.!?]", text, maxsplit=1)[0].strip()
                if first:
                    return first + "."

        # Hero subtitle
        if stype == "hero":
            subtitle = _extract_text(data, "subtitle")
            if subtitle:
                return subtitle

        # Contact text
        if stype == "contact":
            text = _extract_text(data, "text")
            if text:
                return text

        # Services — summarize
        if stype == "services":
            items = data.get("items") or []
            titles = [_extract_text(it, "title") for it in items[:4] if isinstance(it, dict)]
            titles = [t for t in titles if t]
            if titles:
                return "Tjänster: " + ", ".join(titles) + "."

        # FAQ — mention count
        if stype == "faq":
            items = data.get("items") or []
            if items:
                return f"Vanliga frågor och svar — {len(items)} frågor besvarade."

    return ""
