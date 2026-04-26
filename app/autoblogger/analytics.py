"""AutoBlogger analytics — event tracking helpers and API endpoints."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import and_, cast, func, select, Date
from sqlalchemy.ext.asyncio import AsyncSession

from app.autoblogger.auth_dependencies import get_current_autoblogger_user
from app.database import get_db
from app.rate_limit import limiter

from app.autoblogger.models import (
    AnalyticsEvent,
    AnalyticsEventType,
    AutoBloggerSubscription,
    AutoBloggerUser,
    BlogPostAB,
    ContentSchedule,
    CreditBalance,
    CreditTransaction,
    PostStatus,
    Source,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/autoblogger/analytics", tags=["autoblogger-analytics"])


# ─── Tracking helpers (called from generator, publisher, etc.) ──────────────


async def track_event(
    db: AsyncSession,
    user_id: str,
    event_type: AnalyticsEventType,
    event_data: dict | None = None,
) -> None:
    """Insert an analytics event. Fire-and-forget — errors are logged, not raised."""
    try:
        event = AnalyticsEvent(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_type=event_type,
            event_data=event_data,
        )
        db.add(event)
        await db.flush()
    except Exception:
        logger.exception("Failed to track analytics event %s for user %s", event_type, user_id)


# ─── Pydantic response schemas ─────────────────────────────────────────────


class AnalyticsOverview(BaseModel):
    total_posts: int
    published_posts: int
    failed_posts: int
    total_credits_used: int
    credits_remaining: int
    success_rate: float  # 0.0 – 100.0
    active_sources: int
    active_schedules: int


class TimeSeriesPoint(BaseModel):
    date: str  # YYYY-MM-DD
    count: int


class PlatformDistribution(BaseModel):
    platform: str
    count: int


class SuccessRatePoint(BaseModel):
    date: str
    success_rate: float
    total: int


# ─── API Endpoints ──────────────────────────────────────────────────────────


def _period_start(period: str) -> datetime:
    """Convert a period string like '30d' or '7d' to a UTC start datetime."""
    days = 30
    if period.endswith("d") and period[:-1].isdigit():
        days = int(period[:-1])
    return datetime.now(timezone.utc) - timedelta(days=days)


@router.get("/overview", response_model=AnalyticsOverview)
@limiter.limit("30/minute")
async def analytics_overview(
    request: Request,
    current_user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
) -> AnalyticsOverview:
    """Summary analytics stats for the authenticated user."""
    uid = current_user.id

    # Total posts
    total_q = await db.execute(
        select(func.count(BlogPostAB.id)).where(BlogPostAB.user_id == uid)
    )
    total_posts = total_q.scalar() or 0

    # Published
    pub_q = await db.execute(
        select(func.count(BlogPostAB.id)).where(
            BlogPostAB.user_id == uid, BlogPostAB.status == PostStatus.PUBLISHED
        )
    )
    published_posts = pub_q.scalar() or 0

    # Failed
    fail_q = await db.execute(
        select(func.count(BlogPostAB.id)).where(
            BlogPostAB.user_id == uid, BlogPostAB.status == PostStatus.FAILED
        )
    )
    failed_posts = fail_q.scalar() or 0

    # Credits
    bal_q = await db.execute(
        select(CreditBalance).where(CreditBalance.user_id == uid)
    )
    balance = bal_q.scalar_one_or_none()
    credits_remaining = balance.credits_remaining if balance else 0
    total_credits_used = balance.credits_used_total if balance else 0

    # Success rate (of all finished posts: PUBLISHED + FAILED)
    finished = published_posts + failed_posts
    success_rate = round((published_posts / finished) * 100, 1) if finished > 0 else 100.0

    # Active sources
    src_q = await db.execute(
        select(func.count(Source.id)).where(Source.user_id == uid, Source.is_active.is_(True))
    )
    active_sources = src_q.scalar() or 0

    # Active schedules
    sched_q = await db.execute(
        select(func.count(ContentSchedule.id)).where(
            ContentSchedule.user_id == uid, ContentSchedule.is_active.is_(True)
        )
    )
    active_schedules = sched_q.scalar() or 0

    return AnalyticsOverview(
        total_posts=total_posts,
        published_posts=published_posts,
        failed_posts=failed_posts,
        total_credits_used=total_credits_used,
        credits_remaining=credits_remaining,
        success_rate=success_rate,
        active_sources=active_sources,
        active_schedules=active_schedules,
    )


@router.get("/posts-over-time", response_model=list[TimeSeriesPoint])
@limiter.limit("30/minute")
async def posts_over_time(
    request: Request,
    period: str = Query("30d", pattern=r"^\d+d$"),
    current_user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
) -> list[TimeSeriesPoint]:
    """Posts generated per day within the given period."""
    start = _period_start(period)
    uid = current_user.id

    result = await db.execute(
        select(
            cast(BlogPostAB.created_at, Date).label("day"),
            func.count(BlogPostAB.id).label("cnt"),
        )
        .where(BlogPostAB.user_id == uid, BlogPostAB.created_at >= start)
        .group_by("day")
        .order_by("day")
    )
    rows = result.all()
    return [TimeSeriesPoint(date=str(r.day), count=r.cnt) for r in rows]


@router.get("/credits-trend", response_model=list[TimeSeriesPoint])
@limiter.limit("30/minute")
async def credits_trend(
    request: Request,
    period: str = Query("30d", pattern=r"^\d+d$"),
    current_user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
) -> list[TimeSeriesPoint]:
    """Credit usage (deductions) per day within the given period."""
    start = _period_start(period)
    uid = current_user.id

    result = await db.execute(
        select(
            cast(CreditTransaction.created_at, Date).label("day"),
            func.sum(func.abs(CreditTransaction.amount)).label("total"),
        )
        .where(
            CreditTransaction.user_id == uid,
            CreditTransaction.created_at >= start,
            CreditTransaction.amount < 0,  # only deductions
        )
        .group_by("day")
        .order_by("day")
    )
    rows = result.all()
    return [TimeSeriesPoint(date=str(r.day), count=int(r.total or 0)) for r in rows]


@router.get("/platforms", response_model=list[PlatformDistribution])
@limiter.limit("30/minute")
async def platform_distribution(
    request: Request,
    current_user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
) -> list[PlatformDistribution]:
    """Distribution of published posts by platform."""
    uid = current_user.id

    result = await db.execute(
        select(
            Source.platform,
            func.count(BlogPostAB.id).label("cnt"),
        )
        .join(Source, BlogPostAB.source_id == Source.id)
        .where(
            BlogPostAB.user_id == uid,
            BlogPostAB.status == PostStatus.PUBLISHED,
        )
        .group_by(Source.platform)
    )
    rows = result.all()
    return [PlatformDistribution(platform=str(r.platform.value if hasattr(r.platform, 'value') else r.platform), count=r.cnt) for r in rows]


@router.get("/success-rate", response_model=list[SuccessRatePoint])
@limiter.limit("30/minute")
async def success_rate_over_time(
    request: Request,
    period: str = Query("30d", pattern=r"^\d+d$"),
    current_user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
) -> list[SuccessRatePoint]:
    """Generation success rate per day within the given period."""
    start = _period_start(period)
    uid = current_user.id

    # Get all finished posts (PUBLISHED or FAILED) per day
    result = await db.execute(
        select(
            cast(BlogPostAB.created_at, Date).label("day"),
            func.count(BlogPostAB.id).label("total"),
            func.count(BlogPostAB.id).filter(
                BlogPostAB.status == PostStatus.PUBLISHED
            ).label("success"),
        )
        .where(
            BlogPostAB.user_id == uid,
            BlogPostAB.created_at >= start,
            BlogPostAB.status.in_([PostStatus.PUBLISHED, PostStatus.FAILED]),
        )
        .group_by("day")
        .order_by("day")
    )
    rows = result.all()
    return [
        SuccessRatePoint(
            date=str(r.day),
            success_rate=round((r.success / r.total) * 100, 1) if r.total > 0 else 100.0,
            total=r.total,
        )
        for r in rows
    ]
