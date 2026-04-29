"""
Auto-blog configuration.

Defines supported languages, output paths, and generation settings.
Edit `LANGUAGES` to add or remove blog languages.
"""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Language configuration
# Each entry: locale code -> { name, hreflang, dir (ltr/rtl) }
# The first language is treated as the default / x-default hreflang.
# ---------------------------------------------------------------------------
LANGUAGES: dict[str, dict] = {
    "en": {"name": "English", "hreflang": "en", "dir": "ltr"},
    "sv": {"name": "Svenska", "hreflang": "sv", "dir": "ltr"},
    # Add more languages here, e.g.:
    # "de": {"name": "Deutsch", "hreflang": "de", "dir": "ltr"},
    # "es": {"name": "Espanol", "hreflang": "es", "dir": "ltr"},
    # "ar": {"name": "Arabic", "hreflang": "ar", "dir": "rtl"},
}

DEFAULT_LANGUAGE: str = "en"

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_THIS_DIR = Path(__file__).resolve().parent
BRAND_DIR = _THIS_DIR / "brand"

# Where generated SSG content is written (frontend/content/blog/)
FRONTEND_ROOT = Path(os.getenv(
    "AUTO_BLOG_FRONTEND_ROOT",
    str(_THIS_DIR.parent.parent.parent / "frontend"),
))
CONTENT_OUTPUT_DIR = FRONTEND_ROOT / "content" / "blog"

# ---------------------------------------------------------------------------
# Generation defaults
# ---------------------------------------------------------------------------
AI_MODEL: str = os.getenv("AUTO_BLOG_AI_MODEL", "claude-sonnet-4-20250514")
WORD_COUNT_TARGET: int = int(os.getenv("AUTO_BLOG_WORD_COUNT", "1200"))
MAX_CONCURRENT_GENERATIONS: int = int(os.getenv("AUTO_BLOG_MAX_CONCURRENT", "3"))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_language_codes() -> list[str]:
    """Return all configured locale codes."""
    return list(LANGUAGES.keys())


def get_hreflang_map(slug: str, base_url: str = "") -> list[dict[str, str]]:
    """Build hreflang link entries for a given blog post slug.

    Returns a list like:
    [
        {"hreflang": "en", "href": "/en/blog/my-post"},
        {"hreflang": "sv", "href": "/sv/blog/my-post"},
        {"hreflang": "x-default", "href": "/en/blog/my-post"},
    ]
    """
    links: list[dict[str, str]] = []
    for code, lang in LANGUAGES.items():
        href = f"{base_url}/{code}/blog/{slug}"
        links.append({"hreflang": lang["hreflang"], "href": href})

    # x-default points to the default language
    default_href = f"{base_url}/{DEFAULT_LANGUAGE}/blog/{slug}"
    links.append({"hreflang": "x-default", "href": default_href})

    return links
