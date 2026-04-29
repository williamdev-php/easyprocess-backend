"""
Site data quality validator.

Scans a generated site_data dict for common quality issues, inconsistencies,
and problems that would result in a bad user experience.

Usage:
    from app.ai.site_validator import validate_site_data
    issues = validate_site_data(site_data, input_colors=colors)
    # Returns list of Issue(severity, category, message)
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Issue:
    severity: str    # "error", "warning", "info"
    category: str    # "seo", "content", "links", "colors", "toggles", "structure"
    message: str


def validate_site_data(
    site_data: dict,
    *,
    input_colors: dict | None = None,
    input_email: str | None = None,
    input_phone: str | None = None,
    input_address: str | None = None,
    input_business_name: str | None = None,
) -> list[Issue]:
    """Scan site_data for quality issues. Returns list of Issues."""
    issues: list[Issue] = []

    _check_hero(site_data, issues)
    _check_business(site_data, issues, input_email, input_phone, input_address, input_business_name)
    _check_colors(site_data, issues, input_colors)
    _check_seo(site_data, issues)
    _check_contact_toggles(site_data, issues)
    _check_cta_links(site_data, issues)
    _check_pages(site_data, issues)
    _check_content_quality(site_data, issues)
    _check_section_order(site_data, issues)

    return issues


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_hero(data: dict, issues: list[Issue]) -> None:
    hero = data.get("hero")
    if not hero:
        issues.append(Issue("error", "structure", "Hero section is missing"))
        return

    if not hero.get("headline"):
        issues.append(Issue("error", "content", "Hero headline is empty"))
    elif len(hero["headline"]) > 60:
        issues.append(Issue("warning", "content", f"Hero headline is too long ({len(hero['headline'])} chars, max ~60)"))

    cta = hero.get("cta")
    if cta and hero.get("show_cta") is False:
        issues.append(Issue("error", "toggles", "Hero has CTA defined but show_cta=false — button won't be visible"))

    if not cta and hero.get("show_cta") is not False:
        issues.append(Issue("warning", "content", "Hero has no CTA button — visitors have no clear next step"))


def _check_business(data: dict, issues: list[Issue],
                     input_email: str | None, input_phone: str | None,
                     input_address: str | None, input_name: str | None) -> None:
    biz = data.get("business") or {}

    if not biz.get("name"):
        issues.append(Issue("error", "content", "Business name is missing"))
    elif input_name and biz["name"].lower() != input_name.lower():
        issues.append(Issue("warning", "content", f"Business name changed: '{input_name}' → '{biz['name']}'"))

    if input_email and biz.get("email") != input_email:
        issues.append(Issue("warning", "content", f"Email changed: '{input_email}' → '{biz.get('email')}'"))

    if input_phone and biz.get("phone") != input_phone:
        issues.append(Issue("info", "content", f"Phone format changed: '{input_phone}' → '{biz.get('phone')}'"))

    if not biz.get("tagline"):
        issues.append(Issue("warning", "content", "Business tagline is missing"))


def _check_colors(data: dict, issues: list[Issue], input_colors: dict | None) -> None:
    branding = data.get("branding") or {}
    colors = branding.get("colors") or {}

    if not colors:
        issues.append(Issue("error", "colors", "Branding colors are missing"))
        return

    for key in ("primary", "secondary", "accent", "background", "text"):
        val = colors.get(key)
        if not val:
            issues.append(Issue("warning", "colors", f"Color '{key}' is missing"))
        elif not re.match(r"^#[0-9a-fA-F]{3,8}$", val):
            issues.append(Issue("error", "colors", f"Color '{key}' is not a valid hex: '{val}'"))

    if input_colors:
        for key in ("primary", "secondary", "accent", "background", "text"):
            if input_colors.get(key) and colors.get(key) != input_colors[key]:
                issues.append(Issue("error", "colors",
                    f"AI changed {key} color: input={input_colors[key]}, output={colors[key]}"))

    # Check contrast: text on background should be readable
    if colors.get("text") and colors.get("background"):
        t = colors["text"].lower()
        b = colors["background"].lower()
        if t == b:
            issues.append(Issue("error", "colors", f"Text and background are the same color: {t}"))


def _check_seo(data: dict, issues: list[Issue]) -> None:
    meta = data.get("meta") or {}

    if not meta.get("title"):
        issues.append(Issue("error", "seo", "Meta title is missing"))
    elif len(meta["title"]) > 60:
        issues.append(Issue("warning", "seo", f"Meta title is too long ({len(meta['title'])} chars, should be ≤60)"))

    if not meta.get("description"):
        issues.append(Issue("error", "seo", "Meta description is missing"))
    elif len(meta["description"]) > 170:
        issues.append(Issue("warning", "seo", f"Meta description is long ({len(meta['description'])} chars, recommended ≤160)"))
    elif ".." in meta["description"]:
        issues.append(Issue("warning", "seo", f"Meta description has double period: '{meta['description'][:60]}...'"))

    if not meta.get("keywords"):
        issues.append(Issue("warning", "seo", "Meta keywords are missing"))

    seo = data.get("seo") or {}
    sd = seo.get("structured_data") or {}
    if not sd.get("@graph"):
        issues.append(Issue("warning", "seo", "Structured data (@graph) is missing"))
    else:
        types = [g.get("@type") for g in sd["@graph"]]
        if "WebSite" not in types:
            issues.append(Issue("warning", "seo", "Structured data missing WebSite schema"))

    # Check page meta titles for duplication
    site_title = meta.get("title", "")
    pages = data.get("pages") or []
    for page in pages:
        if not isinstance(page, dict):
            continue
        pm = page.get("meta") or {}
        pt = pm.get("title", "")
        if site_title and pt and site_title in pt:
            issues.append(Issue("error", "seo",
                f"Page /{page.get('slug','?')} meta.title contains site title — will cause duplication: '{pt}'"))


def _check_contact_toggles(data: dict, issues: list[Issue]) -> None:
    """Check all contact sections (top-level + in pages) for toggle inconsistencies."""
    def _check_one(contact: dict, location: str) -> None:
        text = (contact.get("text") or "").lower()

        form_words = ["formulär", "form", "fyll i", "skicka meddelande", "skriv till"]
        info_words = ["ring", "telefon", "mejla", "besök oss", "adress", "hitta oss"]

        if any(w in text for w in form_words) and contact.get("show_form") is False:
            issues.append(Issue("error", "toggles",
                f"{location}: Text mentions form but show_form=false"))

        if any(w in text for w in info_words) and contact.get("show_info") is False:
            issues.append(Issue("error", "toggles",
                f"{location}: Text mentions contact info but show_info=false"))

        if contact.get("show_form") is False and contact.get("show_info") is False:
            issues.append(Issue("error", "toggles",
                f"{location}: Both show_form and show_info are false — section is empty"))

    # Top-level contact
    contact = data.get("contact")
    if isinstance(contact, dict):
        _check_one(contact, "Top-level contact")

    # Pages
    for page in (data.get("pages") or []):
        if not isinstance(page, dict):
            continue
        for sec in (page.get("sections") or []):
            if isinstance(sec, dict) and sec.get("type") == "contact":
                d = sec.get("data")
                if isinstance(d, dict):
                    _check_one(d, f"Page /{page.get('slug', '?')} contact")


def _check_cta_links(data: dict, issues: list[Issue]) -> None:
    """Check that all CTA links point to existing pages."""
    # Build set of valid targets
    valid = {"/", "/blog", "/bookings"}
    pages = data.get("pages") or []
    for p in pages:
        if isinstance(p, dict) and p.get("slug"):
            valid.add(f"/{p['slug']}")
            parent = p.get("parent_slug")
            if parent:
                valid.add(f"/{parent}/{p['slug']}")

    # Also add legacy section routes if those sections have data
    for key in ("about", "services", "gallery", "faq", "contact"):
        if data.get(key):
            valid.add(f"/{key}")

    def _check_href(href: str, location: str) -> None:
        if not href or not isinstance(href, str):
            return
        if href.startswith(("http://", "https://", "mailto:", "tel:")):
            return
        if href.startswith("#"):
            issues.append(Issue("warning", "links", f"{location}: Anchor link '{href}' — these don't work"))
            return
        normalized = href.rstrip("/") or "/"  # "/" stripped becomes "" — restore it
        if normalized not in valid:
            issues.append(Issue("warning", "links", f"{location}: href '{href}' points to non-existent page. Valid: {sorted(valid)}"))

    def _walk(obj, path="root"):
        if isinstance(obj, dict):
            if "href" in obj and ("label" in obj or "text" in obj):
                _check_href(obj["href"], path)
            for k, v in obj.items():
                _walk(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _walk(item, f"{path}[{i}]")

    _walk(data)


def _check_pages(data: dict, issues: list[Issue]) -> None:
    pages = data.get("pages") or []

    # Duplicate slugs
    slugs = [p.get("slug") for p in pages if isinstance(p, dict)]
    if len(slugs) != len(set(slugs)):
        dupes = [s for s in slugs if slugs.count(s) > 1]
        issues.append(Issue("error", "structure", f"Duplicate page slugs: {list(set(dupes))}"))

    # Duplicate purposes (similar pages)
    purposes = {}
    for p in pages:
        if not isinstance(p, dict):
            continue
        slug = p.get("slug", "?")
        for sec in (p.get("sections") or []):
            if isinstance(sec, dict):
                stype = sec.get("type")
                if stype == "contact":
                    purposes.setdefault("contact_form", []).append(slug)

    contact_pages = purposes.get("contact_form", [])
    if len(contact_pages) > 1:
        issues.append(Issue("warning", "structure",
            f"Multiple pages with contact forms: {contact_pages} — consider merging"))

    # Empty pages
    for p in pages:
        if not isinstance(p, dict):
            continue
        secs = p.get("sections") or []
        if not secs:
            issues.append(Issue("warning", "structure",
                f"Page /{p.get('slug', '?')} has no sections — will be empty"))

    # Navigation
    nav_pages = [p for p in pages if isinstance(p, dict) and p.get("show_in_nav")]
    if len(nav_pages) > 8:
        issues.append(Issue("warning", "structure",
            f"Too many nav items ({len(nav_pages)}) — max 8 recommended"))


def _check_content_quality(data: dict, issues: list[Issue]) -> None:
    """Check for low-quality or placeholder content."""
    # Check for Lorem ipsum
    def _has_placeholder(text: str) -> bool:
        if not text:
            return False
        low = text.lower()
        return "lorem ipsum" in low or "placeholder" in low or "example.com" in low

    def _walk_text(obj, path="root"):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, str) and _has_placeholder(v):
                    issues.append(Issue("error", "content", f"Placeholder text at {path}.{k}: '{v[:50]}...'"))
                _walk_text(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _walk_text(item, f"{path}[{i}]")

    _walk_text(data)

    # Check about text length on pages (should be substantial)
    for page in (data.get("pages") or []):
        if not isinstance(page, dict):
            continue
        for sec in (page.get("sections") or []):
            if isinstance(sec, dict) and sec.get("type") == "about":
                d = sec.get("data") or {}
                text = d.get("text", "")
                if text and len(text) < 80:
                    issues.append(Issue("warning", "content",
                        f"Page /{page.get('slug','?')} about text is very short ({len(text)} chars)"))


def _check_section_order(data: dict, issues: list[Issue]) -> None:
    order = data.get("section_order") or []
    if not order:
        issues.append(Issue("warning", "structure", "section_order is empty"))
        return

    if order[0] != "hero":
        issues.append(Issue("warning", "structure", f"section_order doesn't start with 'hero': {order}"))

    # Check that ordered sections actually have data
    section_keys = {
        "hero", "about", "features", "stats", "services", "process",
        "gallery", "team", "testimonials", "faq", "cta", "contact",
        "pricing", "video", "logo_cloud", "custom_content", "banner",
        "ranking", "quiz",
    }
    for key in order:
        if key in section_keys and data.get(key) is None:
            issues.append(Issue("warning", "structure",
                f"section_order includes '{key}' but section data is null"))


def format_issues(issues: list[Issue]) -> str:
    """Format issues as readable text."""
    if not issues:
        return "No issues found."

    lines = []
    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    infos = [i for i in issues if i.severity == "info"]

    if errors:
        lines.append(f"ERRORS ({len(errors)}):")
        for i in errors:
            lines.append(f"  [{i.category}] {i.message}")
    if warnings:
        lines.append(f"WARNINGS ({len(warnings)}):")
        for i in warnings:
            lines.append(f"  [{i.category}] {i.message}")
    if infos:
        lines.append(f"INFO ({len(infos)}):")
        for i in infos:
            lines.append(f"  [{i.category}] {i.message}")

    lines.append(f"\nTotal: {len(errors)} errors, {len(warnings)} warnings, {len(infos)} info")
    return "\n".join(lines)
