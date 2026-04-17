"""
Automatic subdomain (slug) generation for sites.

Generates a URL-safe slug from a business name or website URL,
validates against the blacklist, and ensures uniqueness by appending
a numeric suffix if needed.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.sites.models import BLACKLISTED_SUBDOMAINS, GeneratedSite


def slugify(text: str) -> str:
    """Convert text to a URL-safe slug: lowercase, alphanumeric + hyphens."""
    text = text.strip().lower()
    # Replace Swedish/common chars
    replacements = {
        "å": "a", "ä": "a", "ö": "o",
        "ü": "u", "é": "e", "è": "e",
        "&": "och",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    # Replace non-alphanumeric with hyphens
    text = re.sub(r"[^a-z0-9]+", "-", text)
    # Collapse multiple hyphens, strip leading/trailing
    text = re.sub(r"-+", "-", text).strip("-")
    return text


def extract_domain_name(url: str) -> str:
    """Extract the main domain name from a URL (without TLD)."""
    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        hostname = parsed.hostname or ""
    except Exception:
        hostname = url
    # Remove www prefix
    hostname = re.sub(r"^www\.", "", hostname)
    # Take only the domain part (before first dot = TLD)
    parts = hostname.split(".")
    if len(parts) >= 2:
        return parts[0]
    return hostname


def generate_slug(business_name: str | None, website_url: str | None) -> str:
    """
    Generate a subdomain slug from business name or website URL.

    Priority:
    1. Business name (e.g. "Anderssons Bygg & Tak" → "anderssons-bygg-och-tak")
    2. Domain name from URL (e.g. "https://www.xnails.se" → "xnails")
    3. Fallback "site"
    """
    slug = ""
    if business_name:
        slug = slugify(business_name)
    if not slug and website_url:
        domain = extract_domain_name(website_url)
        slug = slugify(domain)
    if not slug:
        slug = "site"

    # Truncate to 63 chars (DNS label limit)
    if len(slug) > 63:
        slug = slug[:63].rstrip("-")

    # Ensure minimum 3 chars
    if len(slug) < 3:
        slug = slug + "-site"

    return slug


async def generate_unique_subdomain(
    db: AsyncSession,
    business_name: str | None,
    website_url: str | None,
    exclude_site_id: str | None = None,
) -> str:
    """
    Generate a unique subdomain slug that doesn't conflict with
    existing subdomains or the blacklist.
    """
    base_slug = generate_slug(business_name, website_url)

    # If slug is blacklisted, prefix with "my-"
    if base_slug in BLACKLISTED_SUBDOMAINS:
        base_slug = f"my-{base_slug}"

    # Check uniqueness and append counter if needed
    candidate = base_slug
    counter = 1

    while True:
        query = select(GeneratedSite.id).where(GeneratedSite.subdomain == candidate)
        if exclude_site_id:
            query = query.where(GeneratedSite.id != exclude_site_id)
        result = await db.execute(query)
        if not result.scalar_one_or_none():
            break
        counter += 1
        candidate = f"{base_slug}-{counter}"
        # Safety: don't loop forever
        if counter > 100:
            import uuid
            candidate = f"{base_slug}-{uuid.uuid4().hex[:6]}"
            break

    return candidate
