"""AutoBlogger health check endpoint."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.autoblogger.models import (
    BlogPostAB,
    ContentSchedule,
    PostStatus,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/autoblogger", tags=["autoblogger-health"])


@router.get("/health")
async def autoblogger_health(request: Request) -> dict:
    """Lightweight health check for AutoBlogger services.

    Returns status of database, scheduler, and failure rates.
    Unauthenticated endpoint for monitoring tools.
    """
    result: dict = {
        "status": "ok",
        "database": "unknown",
        "scheduler": "unknown",
        "failure_rate_1h": None,
        "alerts": [],
    }

    try:
        async with get_db_session() as db:
            # 1. Database connectivity
            try:
                await db.execute(text("SELECT 1"))
                result["database"] = "ok"
            except Exception:
                result["database"] = "error"
                result["status"] = "degraded"
                result["alerts"].append("Database connectivity issue")

            # 2. Scheduler status — check if any active schedule ran recently
            try:
                one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
                sched_q = await db.execute(
                    select(func.max(ContentSchedule.last_run_at)).where(
                        ContentSchedule.is_active.is_(True)
                    )
                )
                last_run = sched_q.scalar()
                if last_run is None:
                    result["scheduler"] = "no_active_schedules"
                elif last_run >= one_hour_ago:
                    result["scheduler"] = "ok"
                else:
                    # Might just mean no schedules were due
                    next_q = await db.execute(
                        select(func.min(ContentSchedule.next_run_at)).where(
                            ContentSchedule.is_active.is_(True)
                        )
                    )
                    next_run = next_q.scalar()
                    if next_run and next_run > datetime.now(timezone.utc):
                        result["scheduler"] = "ok"  # schedules exist, just not due yet
                    else:
                        result["scheduler"] = "stale"
                        result["alerts"].append("Scheduler may be stale — no recent execution")
            except Exception:
                result["scheduler"] = "error"

            # 3. Generation failure rate (last hour)
            try:
                one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
                total_q = await db.execute(
                    select(func.count(BlogPostAB.id)).where(
                        BlogPostAB.created_at >= one_hour_ago,
                        BlogPostAB.status.in_([PostStatus.PUBLISHED, PostStatus.FAILED, PostStatus.REVIEW]),
                    )
                )
                total = total_q.scalar() or 0

                failed_q = await db.execute(
                    select(func.count(BlogPostAB.id)).where(
                        BlogPostAB.created_at >= one_hour_ago,
                        BlogPostAB.status == PostStatus.FAILED,
                    )
                )
                failed = failed_q.scalar() or 0

                if total > 0:
                    rate = round((failed / total) * 100, 1)
                    result["failure_rate_1h"] = rate
                    if rate > 10:
                        result["status"] = "degraded"
                        result["alerts"].append(
                            f"High failure rate: {rate}% ({failed}/{total} posts in last hour)"
                        )
                else:
                    result["failure_rate_1h"] = 0.0
            except Exception:
                logger.exception("Health check: failure rate query failed")

    except Exception:
        result["status"] = "error"
        result["database"] = "error"
        result["alerts"].append("Could not connect to database")

    return result
