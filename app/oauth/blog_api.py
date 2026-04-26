"""OAuth-protected blog API for Qvicko sites.

Third-party apps holding a valid OAuth access token with the right scopes
can read and write blog posts on the authorized site through these endpoints.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.apps.models import BlogCategory, BlogPost, BlogPostStatus
from app.database import get_db
from app.oauth.models import OAuthAccessToken
from app.oauth.service import validate_access_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/oauth/blog", tags=["oauth-blog"])


# ------------------------------------------------------------------
# Auth dependency
# ------------------------------------------------------------------

async def _get_token(
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
) -> OAuthAccessToken:
    """Extract and validate the OAuth Bearer token."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    raw = authorization[7:]
    token = await validate_access_token(db, raw)
    if not token:
        raise HTTPException(status_code=401, detail="Invalid or revoked access token")
    return token


def _require_scope(scope: str):
    """Return a dependency that checks for a specific scope."""
    async def dep(
        authorization: str = Header(...),
        db: AsyncSession = Depends(get_db),
    ) -> OAuthAccessToken:
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Invalid authorization header")
        raw = authorization[7:]
        token = await validate_access_token(db, raw, required_scope=scope)
        if not token:
            raise HTTPException(status_code=403, detail=f"Missing scope: {scope}")
        return token
    return dep


# ------------------------------------------------------------------
# Schemas
# ------------------------------------------------------------------

class BlogPostCreate(BaseModel):
    title: str
    slug: str | None = None
    content: str = ""
    excerpt: str | None = None
    featured_image: str | None = None
    author_name: str | None = None
    category_slug: str | None = None
    status: str = "DRAFT"  # DRAFT or PUBLISHED


class BlogPostUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    excerpt: str | None = None
    featured_image: str | None = None
    status: str | None = None


class BlogPostResponse(BaseModel):
    id: str
    title: str
    slug: str
    excerpt: str | None
    content: str
    featured_image: str | None
    author_name: str | None
    status: str
    published_at: str | None
    created_at: str
    updated_at: str
    category: dict | None = None


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.get("/posts")
async def list_posts(
    token: OAuthAccessToken = Depends(_require_scope("blog:read")),
    db: AsyncSession = Depends(get_db),
    page: int = 1,
    page_size: int = 25,
):
    """List blog posts for the authorized site."""
    offset = (page - 1) * page_size
    base = select(BlogPost).where(BlogPost.site_id == token.site_id)

    count_q = select(func.count(BlogPost.id)).where(BlogPost.site_id == token.site_id)
    total = (await db.execute(count_q)).scalar() or 0

    result = await db.execute(
        base.options(selectinload(BlogPost.category))
        .order_by(BlogPost.created_at.desc())
        .offset(offset)
        .limit(min(page_size, 100))
    )
    posts = result.scalars().all()

    return {
        "posts": [_serialize_post(p) for p in posts],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/posts/{post_id}")
async def get_post(
    post_id: str,
    token: OAuthAccessToken = Depends(_require_scope("blog:read")),
    db: AsyncSession = Depends(get_db),
):
    """Get a single blog post."""
    result = await db.execute(
        select(BlogPost)
        .options(selectinload(BlogPost.category))
        .where(BlogPost.id == post_id, BlogPost.site_id == token.site_id)
    )
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    return _serialize_post(post)


@router.post("/posts", status_code=201)
async def create_post(
    body: BlogPostCreate,
    token: OAuthAccessToken = Depends(_require_scope("blog:write")),
    db: AsyncSession = Depends(get_db),
):
    """Create a new blog post on the authorized site."""
    slug = body.slug or _slugify(body.title)

    # Ensure unique slug
    existing = await db.execute(
        select(BlogPost.id).where(
            BlogPost.site_id == token.site_id, BlogPost.slug == slug
        )
    )
    if existing.scalar_one_or_none():
        slug = f"{slug}-{uuid.uuid4().hex[:6]}"

    # Resolve category
    category_id = None
    if body.category_slug:
        cat_result = await db.execute(
            select(BlogCategory).where(
                BlogCategory.site_id == token.site_id,
                BlogCategory.slug == body.category_slug,
            )
        )
        cat = cat_result.scalar_one_or_none()
        if cat:
            category_id = cat.id

    post_status = BlogPostStatus.PUBLISHED if body.status == "PUBLISHED" else BlogPostStatus.DRAFT
    now = datetime.now(timezone.utc)

    post = BlogPost(
        site_id=token.site_id,
        category_id=category_id,
        title=body.title,
        slug=slug,
        content=body.content,
        excerpt=body.excerpt,
        featured_image=body.featured_image,
        author_name=body.author_name,
        status=post_status,
        published_at=now if post_status == BlogPostStatus.PUBLISHED else None,
    )
    db.add(post)
    await db.flush()
    await db.refresh(post)

    logger.info(
        "OAuth blog post created: site=%s post=%s client=%s",
        token.site_id, post.id, token.client_id,
    )
    return _serialize_post(post)


@router.patch("/posts/{post_id}")
async def update_post(
    post_id: str,
    body: BlogPostUpdate,
    token: OAuthAccessToken = Depends(_require_scope("blog:write")),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing blog post."""
    result = await db.execute(
        select(BlogPost).where(BlogPost.id == post_id, BlogPost.site_id == token.site_id)
    )
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    if body.title is not None:
        post.title = body.title
    if body.content is not None:
        post.content = body.content
    if body.excerpt is not None:
        post.excerpt = body.excerpt
    if body.featured_image is not None:
        post.featured_image = body.featured_image
    if body.status is not None:
        new_status = BlogPostStatus.PUBLISHED if body.status == "PUBLISHED" else BlogPostStatus.DRAFT
        if new_status == BlogPostStatus.PUBLISHED and post.status != BlogPostStatus.PUBLISHED:
            post.published_at = datetime.now(timezone.utc)
        post.status = new_status

    await db.flush()
    await db.refresh(post)
    return _serialize_post(post)


@router.delete("/posts/{post_id}", status_code=204)
async def delete_post(
    post_id: str,
    token: OAuthAccessToken = Depends(_require_scope("blog:write")),
    db: AsyncSession = Depends(get_db),
):
    """Delete a blog post."""
    result = await db.execute(
        select(BlogPost).where(BlogPost.id == post_id, BlogPost.site_id == token.site_id)
    )
    post = result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    await db.delete(post)
    await db.flush()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _serialize_post(post: BlogPost) -> dict:
    return {
        "id": post.id,
        "title": post.title,
        "slug": post.slug,
        "excerpt": post.excerpt,
        "content": post.content,
        "featured_image": post.featured_image,
        "author_name": post.author_name,
        "status": post.status.value if hasattr(post.status, "value") else str(post.status),
        "published_at": post.published_at.isoformat() if post.published_at else None,
        "created_at": post.created_at.isoformat(),
        "updated_at": post.updated_at.isoformat(),
        "category": {
            "id": post.category.id,
            "name": post.category.name,
            "slug": post.category.slug,
        } if post.category else None,
    }


def _slugify(text: str) -> str:
    import re
    slug = text.lower().strip()
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[-\s]+', '-', slug)
    return slug[:200]
