"""Unified publishing service — routes blog posts to the correct platform integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.autoblogger.models import BlogPostAB, PlatformType, PostStatus, Source

logger = logging.getLogger(__name__)

_MAX_PUBLISH_RETRIES = 3
_BASE_BACKOFF = 2.0


class PublishResult:
    """Result of a publish attempt."""
    def __init__(self, success: bool, platform_post_id: str | None = None, error: str | None = None):
        self.success = success
        self.platform_post_id = platform_post_id
        self.error = error


async def publish_post(db: AsyncSession, post: BlogPostAB, source: Source) -> PublishResult:
    """Publish a post to the platform configured on its source.

    Routes to the correct integration based on source.platform.
    Returns PublishResult with success/failure info.
    """
    platform = source.platform

    if platform == PlatformType.MANUAL:
        # Manual platform — no actual publishing needed, just mark as published
        return PublishResult(success=True, platform_post_id=f"manual-{post.id[:8]}")

    if platform == PlatformType.SHOPIFY:
        from app.autoblogger.integrations.shopify import publish_to_shopify
        return await publish_to_shopify(post, source)

    if platform == PlatformType.QVICKO:
        from app.autoblogger.integrations.qvicko import publish_to_qvicko
        return await publish_to_qvicko(db, post, source)

    if platform == PlatformType.CUSTOM:
        from app.autoblogger.integrations.wordpress import publish_to_wordpress
        return await publish_to_wordpress(post, source)

    return PublishResult(success=False, error=f"Unknown platform: {platform}")


async def publish_post_with_retry(
    db: AsyncSession, post: BlogPostAB, source: Source
) -> PublishResult:
    """Publish with retry logic (max 3 attempts with exponential backoff).

    For MANUAL platform, no retry is needed.
    """
    if source.platform == PlatformType.MANUAL:
        return await publish_post(db, post, source)

    last_result = PublishResult(success=False, error="No attempts made")

    for attempt in range(_MAX_PUBLISH_RETRIES):
        result = await publish_post(db, post, source)
        if result.success:
            return result

        last_result = result
        if attempt < _MAX_PUBLISH_RETRIES - 1:
            wait = _BASE_BACKOFF * (2 ** attempt)
            logger.warning(
                "Publish attempt %d/%d failed for post %s: %s. Retrying in %.1fs",
                attempt + 1, _MAX_PUBLISH_RETRIES, post.id, result.error, wait,
            )
            await asyncio.sleep(wait)

    logger.error(
        "Publishing failed after %d attempts for post %s: %s",
        _MAX_PUBLISH_RETRIES, post.id, last_result.error,
    )
    return last_result


async def execute_publish(db: AsyncSession, post_id: str) -> PublishResult:
    """Full publish workflow: load post + source, publish with retry, update DB state.

    Called by the approve endpoint and by the auto-publish flow.
    """
    result_q = await db.execute(
        select(BlogPostAB).where(BlogPostAB.id == post_id)
    )
    post = result_q.scalar_one_or_none()
    if not post:
        return PublishResult(success=False, error="Post not found")

    source_q = await db.execute(
        select(Source).where(Source.id == post.source_id)
    )
    source = source_q.scalar_one_or_none()
    if not source:
        return PublishResult(success=False, error="Source not found")

    publish_result = await publish_post_with_retry(db, post, source)

    now = datetime.now(timezone.utc)
    if publish_result.success:
        post.status = PostStatus.PUBLISHED
        post.published_at = now
        post.platform_post_id = publish_result.platform_post_id
        post.error_message = None
    else:
        post.status = PostStatus.FAILED
        post.error_message = f"Publish failed: {publish_result.error}"

    post.updated_at = now

    # Track POST_PUBLISHED analytics event
    from app.autoblogger.analytics import track_event
    from app.autoblogger.models import AnalyticsEventType
    await track_event(db, post.user_id, AnalyticsEventType.POST_PUBLISHED, {
        "post_id": post_id,
        "platform": source.platform.value if hasattr(source.platform, 'value') else str(source.platform),
        "success": publish_result.success,
        "error": publish_result.error,
    })

    await db.flush()

    return publish_result
