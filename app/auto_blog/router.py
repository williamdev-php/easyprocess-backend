"""
Auto-blog API router.

Endpoints for generating blog posts and building SSG content.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.auto_blog.config import LANGUAGES, CONTENT_OUTPUT_DIR, get_language_codes
from app.auto_blog.generator import generate_post_all_languages, close_http_client
from app.auto_blog.builder import write_post, rebuild_index
from app.auto_blog.schemas import (
    GenerateRequest,
    GenerateResponse,
    BuildResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auto-blog", tags=["auto-blog"])


@router.post("/generate", response_model=GenerateResponse)
async def generate_blog_post(req: GenerateRequest):
    """Generate a new blog post in all (or specified) languages and write to disk."""
    # Validate requested languages
    if req.languages:
        invalid = [l for l in req.languages if l not in LANGUAGES]
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported languages: {invalid}. Available: {list(LANGUAGES.keys())}",
            )
        langs = req.languages
    else:
        langs = get_language_codes()

    try:
        posts = await generate_post_all_languages(
            topic=req.topic,
            keywords=req.keywords,
            languages=langs,
            word_count=req.word_count,
            author_name=req.author_name,
            author_bio=req.author_bio,
            author_url=req.author_url,
        )
    except Exception as e:
        logger.exception("Blog generation failed")
        raise HTTPException(status_code=500, detail=str(e))

    # Write to disk as SSG content
    slug = write_post(posts)

    return GenerateResponse(
        slug=slug,
        languages_generated=[p.meta.locale for p in posts],
        posts=[p.meta for p in posts],
    )


@router.post("/rebuild-index", response_model=BuildResponse)
async def rebuild_blog_index():
    """Rebuild the blog index from existing content files."""
    try:
        count = rebuild_index()
    except Exception as e:
        logger.exception("Index rebuild failed")
        raise HTTPException(status_code=500, detail=str(e))

    return BuildResponse(
        posts_written=count,
        output_dir=str(CONTENT_OUTPUT_DIR),
    )


@router.get("/languages")
async def list_languages():
    """List all configured blog languages."""
    return {"languages": LANGUAGES, "default": list(LANGUAGES.keys())[0]}


@router.get("/posts")
async def list_posts(locale: str | None = None):
    """List all generated posts (optionally filtered by locale)."""
    import json
    index_file = CONTENT_OUTPUT_DIR / "index.json"
    if not index_file.exists():
        return {"posts": {}}

    index = json.loads(index_file.read_text(encoding="utf-8"))

    if locale:
        return {"posts": {locale: index.get(locale, [])}}

    return {"posts": index}


@router.get("/posts/{slug}")
async def get_post(slug: str, locale: str = "en"):
    """Get a specific blog post by slug and locale."""
    import json
    post_file = CONTENT_OUTPUT_DIR / "posts" / slug / f"{locale}.json"
    if not post_file.exists():
        raise HTTPException(status_code=404, detail=f"Post not found: {slug} ({locale})")

    data = json.loads(post_file.read_text(encoding="utf-8"))
    return data
