"""Background cleanup tasks for AutoBlogger.

Recovers stuck posts and cleans up stale data.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.autoblogger.models import (
    AutoBloggerSession,
    BlogPostAB,
    ContentSchedule,
    PostStatus,
)
from app.autoblogger.scheduler import calculate_next_run_at

logger = logging.getLogger(__name__)


async def cleanup_stuck_generating_posts(db: AsyncSession, timeout_minutes: int = 10) -> int:
    """Mark posts stuck in GENERATING status for longer than timeout as FAILED.

    Returns the number of posts recovered.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)

    result = await db.execute(
        select(BlogPostAB).where(
            BlogPostAB.status == PostStatus.GENERATING,
            BlogPostAB.updated_at < cutoff,
        )
    )
    stuck_posts = result.scalars().all()

    for post in stuck_posts:
        post.status = PostStatus.FAILED
        post.error_message = f"Generation timed out after {timeout_minutes} minutes"
        post.updated_at = datetime.now(timezone.utc)
        logger.warning("Marked stuck post %s as FAILED (was GENERATING since %s)", post.id, post.updated_at)

    if stuck_posts:
        await db.flush()

    return len(stuck_posts)


async def cleanup_stuck_schedules(db: AsyncSession) -> int:
    """Re-calculate next_run_at for schedules stuck in the past by more than 1 hour.

    Returns the number of schedules fixed.
    """
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)

    result = await db.execute(
        select(ContentSchedule).where(
            ContentSchedule.is_active.is_(True),
            ContentSchedule.next_run_at.isnot(None),
            ContentSchedule.next_run_at < one_hour_ago,
        )
    )
    stuck = result.scalars().all()

    fixed = 0
    for schedule in stuck:
        new_next = calculate_next_run_at(
            frequency=schedule.frequency,
            preferred_time=schedule.preferred_time,
            timezone_str=schedule.timezone,
            days_of_week=schedule.days_of_week,
            last_run_at=schedule.last_run_at,
        )
        if new_next:
            schedule.next_run_at = new_next
            schedule.updated_at = datetime.now(timezone.utc)
            fixed += 1
            logger.warning(
                "Fixed stuck schedule %s: next_run_at was %s, now %s",
                schedule.id, schedule.next_run_at, new_next,
            )

    if fixed:
        await db.flush()

    return fixed


async def cleanup_expired_sessions(db: AsyncSession, days_old: int = 90) -> int:
    """Delete revoked sessions older than the specified number of days.

    Returns the number of sessions cleaned up.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_old)

    result = await db.execute(
        select(AutoBloggerSession).where(
            AutoBloggerSession.revoked_at.isnot(None),
            AutoBloggerSession.revoked_at < cutoff,
        )
    )
    old_sessions = result.scalars().all()

    for session in old_sessions:
        await db.delete(session)

    if old_sessions:
        await db.flush()
        logger.info("Cleaned up %d expired sessions older than %d days", len(old_sessions), days_old)

    return len(old_sessions)


async def run_all_cleanup(db: AsyncSession) -> dict:
    """Run all cleanup tasks. Returns a summary."""
    stuck_posts = await cleanup_stuck_generating_posts(db)
    stuck_schedules = await cleanup_stuck_schedules(db)
    expired_sessions = await cleanup_expired_sessions(db)

    return {
        "stuck_posts_recovered": stuck_posts,
        "stuck_schedules_fixed": stuck_schedules,
        "expired_sessions_cleaned": expired_sessions,
    }
