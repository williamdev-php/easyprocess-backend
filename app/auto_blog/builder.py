"""
SSG content builder.

Writes generated blog posts as JSON files into the frontend/content/blog/
directory. The Next.js frontend reads these at build time (SSG) to render
static blog pages.

Directory structure:
  frontend/content/blog/
    index.json                 # Master index of all posts
    posts/
      {slug}/
        en.json                # English version
        sv.json                # Swedish version
        meta.json              # Shared metadata + hreflang links
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.auto_blog.config import CONTENT_OUTPUT_DIR, get_language_codes
from app.auto_blog.schemas import BlogPostContent, BlogIndexEntry

logger = logging.getLogger(__name__)


def _ensure_dirs() -> Path:
    """Create output directories if they don't exist."""
    posts_dir = CONTENT_OUTPUT_DIR / "posts"
    posts_dir.mkdir(parents=True, exist_ok=True)
    return posts_dir


def write_post(posts: list[BlogPostContent]) -> str:
    """Write a set of language variants of a post to disk. Returns the slug."""
    if not posts:
        raise ValueError("No posts to write")

    slug = posts[0].meta.slug
    posts_dir = _ensure_dirs()
    post_dir = posts_dir / slug
    post_dir.mkdir(parents=True, exist_ok=True)

    # Write each language variant
    for post in posts:
        lang_file = post_dir / f"{post.meta.locale}.json"
        lang_file.write_text(
            json.dumps({
                "meta": post.meta.model_dump(),
                "content": post.content,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Wrote %s/%s.json", slug, post.meta.locale)

    # Write shared meta.json with hreflang links
    meta_file = post_dir / "meta.json"
    meta_data = {
        "slug": slug,
        "languages": [p.meta.locale for p in posts],
        "hreflang_links": posts[0].meta.hreflang_links,
        "published_at": posts[0].meta.published_at,
        "tags": posts[0].meta.tags,
    }
    meta_file.write_text(
        json.dumps(meta_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Rebuild the master index
    rebuild_index()

    return slug


def rebuild_index() -> int:
    """Rebuild the master blog index from all post directories. Returns post count."""
    posts_dir = _ensure_dirs()
    index: dict[str, list[BlogIndexEntry]] = {}

    for lang in get_language_codes():
        index[lang] = []

    for post_dir in sorted(posts_dir.iterdir()):
        if not post_dir.is_dir():
            continue

        for lang_file in post_dir.glob("*.json"):
            if lang_file.name == "meta.json":
                continue
            locale = lang_file.stem
            if locale not in index:
                index[locale] = []

            try:
                data = json.loads(lang_file.read_text(encoding="utf-8"))
                meta = data["meta"]
                index[locale].append(BlogIndexEntry(
                    slug=meta["slug"],
                    title=meta["title"],
                    excerpt=meta["excerpt"],
                    published_at=meta["published_at"],
                    tags=meta.get("tags", []),
                    reading_time_minutes=meta.get("reading_time_minutes", 0),
                    featured_image=meta.get("featured_image"),
                    featured_image_alt=meta.get("featured_image_alt", ""),
                    locale=locale,
                    primary_keyword=meta.get("primary_keyword", ""),
                ))
            except Exception as e:
                logger.warning("Failed to index %s: %s", lang_file, e)

    # Sort each language's posts by date descending
    for lang in index:
        index[lang].sort(key=lambda p: p.published_at, reverse=True)

    # Write index.json
    index_file = CONTENT_OUTPUT_DIR / "index.json"
    index_file.write_text(
        json.dumps(
            {lang: [entry.model_dump() for entry in entries] for lang, entries in index.items()},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    total = sum(len(entries) for entries in index.values())
    logger.info("Blog index rebuilt: %d entries across %d languages", total, len(index))
    return total
