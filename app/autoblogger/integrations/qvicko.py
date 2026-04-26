"""Qvicko integration -- publish blog posts via OAuth-protected API.

Uses the OAuth access token stored in platform_config to call the
Qvicko blog API endpoints (/api/oauth/blog/posts).
"""
from __future__ import annotations

import logging

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.autoblogger.encryption import decrypt_platform_config
from app.config import settings

logger = logging.getLogger(__name__)

# The backend's own URL for internal API calls
_BACKEND_URL = f"http://localhost:8000"

_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=30.0,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _http_client


async def publish_to_qvicko(db: AsyncSession, post, source) -> "PublishResult":
    """Publish a blog post to a Qvicko site via the OAuth blog API.

    Uses the OAuth access token stored (encrypted) in source.platform_config.
    Falls back to direct DB access if no OAuth token is present (legacy sources).
    """
    from app.autoblogger.publisher import PublishResult

    config = decrypt_platform_config(source.platform_config) or {}
    oauth_token = config.get("oauth_access_token")

    if oauth_token:
        return await _publish_via_api(post, oauth_token, config)
    else:
        # Legacy path: direct DB access for sources created before OAuth
        return await _publish_direct(db, post, config)


async def _publish_via_api(post, oauth_token: str, config: dict) -> "PublishResult":
    """Publish using the OAuth-protected blog API."""
    from app.autoblogger.publisher import PublishResult

    client = _get_http_client()

    payload = {
        "title": post.title,
        "slug": post.slug or "",
        "content": post.content or "",
        "excerpt": post.excerpt or "",
        "featured_image": post.featured_image_url,
        "author_name": "AutoBlogger",
        "status": "PUBLISHED",
    }

    try:
        resp = await client.post(
            f"{_BACKEND_URL}/api/oauth/blog/posts",
            json=payload,
            headers={"Authorization": f"Bearer {oauth_token}"},
        )

        if resp.status_code == 401:
            return PublishResult(
                success=False,
                error="Qvicko OAuth token is invalid or revoked. Please reconnect the source.",
            )

        resp.raise_for_status()
        data = resp.json()
        blog_post_id = data.get("id", "")

        logger.info(
            "Published to Qvicko via OAuth API: site=%s post=%s",
            config.get("site_id"), blog_post_id,
        )
        return PublishResult(
            success=True,
            platform_post_id=f"qvicko-{blog_post_id}",
        )

    except httpx.HTTPStatusError as e:
        error_body = e.response.text[:500]
        logger.error("Qvicko OAuth publish failed: %s — %s", e.response.status_code, error_body)
        return PublishResult(
            success=False,
            error=f"Qvicko API error {e.response.status_code}: {error_body}",
        )
    except Exception as e:
        logger.error("Qvicko publish error: %s", e)
        return PublishResult(success=False, error=str(e))


async def _publish_direct(db: AsyncSession, post, config: dict) -> "PublishResult":
    """Legacy fallback: publish via direct DB access for pre-OAuth sources."""
    import uuid
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.autoblogger.publisher import PublishResult
    from app.sites.models import GeneratedSite, SiteStatus

    site_id = config.get("site_id")
    if not site_id:
        return PublishResult(success=False, error="Qvicko site_id not configured")

    result = await db.execute(
        select(GeneratedSite).where(GeneratedSite.id == site_id)
    )
    site = result.scalar_one_or_none()

    if not site:
        return PublishResult(success=False, error=f"Qvicko site {site_id} not found")

    if site.status != SiteStatus.PUBLISHED:
        return PublishResult(success=False, error="Qvicko site is not published")

    site_data = dict(site.site_data) if site.site_data else {}
    blog_posts = list(site_data.get("blog_posts", []))

    blog_post_entry = {
        "id": str(uuid.uuid4()),
        "autoblogger_post_id": post.id,
        "title": post.title,
        "slug": post.slug or "",
        "content": post.content or "",
        "excerpt": post.excerpt or "",
        "meta_title": post.meta_title or "",
        "meta_description": post.meta_description or "",
        "featured_image_url": post.featured_image_url,
        "tags": post.tags or [],
        "published_at": datetime.now(timezone.utc).isoformat(),
        "schema_markup": post.schema_markup or {},
    }

    blog_posts.append(blog_post_entry)
    site_data["blog_posts"] = blog_posts
    site.site_data = site_data
    site.updated_at = datetime.now(timezone.utc)

    await db.flush()

    logger.info("Published to Qvicko site %s (legacy): post_id=%s", site_id, post.id)
    return PublishResult(
        success=True,
        platform_post_id=f"qvicko-{blog_post_entry['id']}",
    )
