"""
REST endpoints for the app system — consumed by the viewer (public, no auth).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import cache
from app.database import get_db
from app.apps.models import App, AppInstallation, BlogCategory, BlogPost, BlogPostStatus

router = APIRouter(prefix="/api/sites", tags=["apps"])

BLOG_CACHE_TTL = 300  # 5 minutes


# ---------------------------------------------------------------------------
# Public: Installed apps for a site
# ---------------------------------------------------------------------------

@router.get("/{site_id}/apps/installed")
async def get_installed_apps(
    site_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[str]:
    """Return list of installed app slugs for a site."""
    cache_key = f"site:apps:{site_id}"
    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

    result = await db.execute(
        select(App.slug)
        .join(AppInstallation, AppInstallation.app_id == App.id)
        .where(
            AppInstallation.site_id == site_id,
            AppInstallation.is_active == True,  # noqa: E712
        )
    )
    slugs = [row[0] for row in result.all()]
    await cache.set(cache_key, slugs, ttl=BLOG_CACHE_TTL)
    return slugs


# ---------------------------------------------------------------------------
# Public: Blog posts
# ---------------------------------------------------------------------------

@router.get("/{site_id}/blog/posts")
async def list_blog_posts(
    site_id: str,
    page: int = 1,
    page_size: int = 10,
    category: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List published blog posts for a site (public)."""
    page_size = min(page_size, 50)
    cache_key = f"blog:posts:{site_id}:p{page}:s{page_size}:c{category or ''}"
    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

    base = select(BlogPost).where(
        BlogPost.site_id == site_id,
        BlogPost.status == BlogPostStatus.PUBLISHED,
    )
    count_base = select(func.count(BlogPost.id)).where(
        BlogPost.site_id == site_id,
        BlogPost.status == BlogPostStatus.PUBLISHED,
    )

    if category:
        base = base.join(BlogCategory, BlogPost.category_id == BlogCategory.id).where(
            BlogCategory.slug == category
        )
        count_base = count_base.join(BlogCategory, BlogPost.category_id == BlogCategory.id).where(
            BlogCategory.slug == category
        )

    total_result = await db.execute(count_base)
    total = total_result.scalar() or 0

    offset = (page - 1) * page_size
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        base.options(selectinload(BlogPost.category))
        .order_by(BlogPost.published_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    posts = result.scalars().all()

    data = {
        "items": [
            {
                "id": p.id,
                "title": p.title,
                "slug": p.slug,
                "excerpt": p.excerpt,
                "featured_image": p.featured_image,
                "author_name": p.author_name,
                "category_name": p.category.name if p.category else None,
                "category_slug": p.category.slug if p.category else None,
                "published_at": p.published_at.isoformat() if p.published_at else None,
            }
            for p in posts
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
    await cache.set(cache_key, data, ttl=BLOG_CACHE_TTL)
    return data


@router.get("/{site_id}/blog/posts/{slug}")
async def get_blog_post(
    site_id: str,
    slug: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get a single published blog post by slug (public)."""
    cache_key = f"blog:post:{site_id}:{slug}"
    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(BlogPost)
        .options(selectinload(BlogPost.category))
        .where(
            BlogPost.site_id == site_id,
            BlogPost.slug == slug,
            BlogPost.status == BlogPostStatus.PUBLISHED,
        )
    )
    post = result.scalar_one_or_none()
    if post is None:
        raise HTTPException(status_code=404, detail="Blog post not found")

    data = {
        "id": post.id,
        "title": post.title,
        "slug": post.slug,
        "excerpt": post.excerpt,
        "content": post.content,
        "featured_image": post.featured_image,
        "author_name": post.author_name,
        "category_name": post.category.name if post.category else None,
        "category_slug": post.category.slug if post.category else None,
        "published_at": post.published_at.isoformat() if post.published_at else None,
        "created_at": post.created_at.isoformat() if post.created_at else None,
    }
    await cache.set(cache_key, data, ttl=BLOG_CACHE_TTL)
    return data


# ---------------------------------------------------------------------------
# Public: Blog categories
# ---------------------------------------------------------------------------

@router.get("/{site_id}/blog/categories")
async def list_blog_categories(
    site_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List blog categories with post counts (public)."""
    cache_key = f"blog:categories:{site_id}"
    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

    result = await db.execute(
        select(BlogCategory, func.count(BlogPost.id).label("post_count"))
        .outerjoin(
            BlogPost,
            (BlogPost.category_id == BlogCategory.id)
            & (BlogPost.status == BlogPostStatus.PUBLISHED),
        )
        .where(BlogCategory.site_id == site_id)
        .group_by(BlogCategory.id)
        .order_by(BlogCategory.sort_order, BlogCategory.name)
    )

    data = [
        {
            "id": cat.id,
            "name": cat.name,
            "slug": cat.slug,
            "description": cat.description,
            "post_count": count,
        }
        for cat, count in result.all()
    ]
    await cache.set(cache_key, data, ttl=BLOG_CACHE_TTL)
    return data
