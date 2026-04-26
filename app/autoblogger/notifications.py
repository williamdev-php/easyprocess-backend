"""Convenience helpers for creating AutoBlogger in-app notifications."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.autoblogger.models import Notification

logger = logging.getLogger(__name__)


async def create_notification(
    db: AsyncSession,
    user_id: str,
    type: str,
    title: str,
    message: str,
    link: str | None = None,
) -> Notification:
    """Create and persist a new notification."""
    notification = Notification(
        user_id=user_id,
        type=type,
        title=title,
        message=message,
        link=link,
    )
    db.add(notification)
    await db.flush()
    return notification


async def notify_post_generated(
    db: AsyncSession, user_id: str, post_title: str, post_id: str
) -> Notification:
    return await create_notification(
        db,
        user_id=user_id,
        type="post_generated",
        title="Post generated",
        message=f'Your blog post "{post_title}" has been generated and is ready for review.',
        link=f"/dashboard/posts/{post_id}",
    )


async def notify_post_failed(
    db: AsyncSession, user_id: str, post_title: str, post_id: str
) -> Notification:
    return await create_notification(
        db,
        user_id=user_id,
        type="post_failed",
        title="Post generation failed",
        message=f'Generation failed for "{post_title}". You can try regenerating it.',
        link=f"/dashboard/posts/{post_id}",
    )


async def notify_credits_low(
    db: AsyncSession, user_id: str, remaining: int
) -> Notification:
    return await create_notification(
        db,
        user_id=user_id,
        type="credits_low",
        title="Credits running low",
        message=f"You have {remaining} credit{'s' if remaining != 1 else ''} remaining this month. Consider upgrading your plan.",
        link="/dashboard/billing",
    )


async def notify_credits_exhausted(
    db: AsyncSession, user_id: str
) -> Notification:
    return await create_notification(
        db,
        user_id=user_id,
        type="credits_exhausted",
        title="Credits exhausted",
        message="You have no credits remaining this month. Upgrade your plan to continue generating posts.",
        link="/dashboard/billing",
    )


async def notify_source_connected(
    db: AsyncSession, user_id: str, source_name: str
) -> Notification:
    return await create_notification(
        db,
        user_id=user_id,
        type="source_connected",
        title="Source connected",
        message=f'"{source_name}" has been connected successfully. You can now create schedules for it.',
        link="/dashboard/sources",
    )
