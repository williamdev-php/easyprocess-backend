"""Aggregation queries for the analytics dashboard."""

from datetime import datetime

from sqlalchemy import cast, func, select, distinct, Float, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.models import Payment
from app.tracking.models import TrackingEvent


# ---------------------------------------------------------------------------
# Funnel stats
# ---------------------------------------------------------------------------

FUNNEL_STEPS = [
    "page_view",
    "cta_click",
    "create_site_started",
    "create_site_completed",
    "signup",
    "trial_started",
    "subscription_created",
]


async def get_funnel_stats(
    db: AsyncSession,
    start_date: datetime,
    end_date: datetime,
    utm_source: str | None = None,
    utm_campaign: str | None = None,
) -> list[dict]:
    """Return unique visitor counts for each funnel step."""
    results = []
    for step in FUNNEL_STEPS:
        q = select(func.count(distinct(TrackingEvent.visitor_id))).where(
            TrackingEvent.event_type == step,
            TrackingEvent.created_at >= start_date,
            TrackingEvent.created_at <= end_date,
        )
        if utm_source:
            q = q.where(TrackingEvent.utm_source == utm_source)
        if utm_campaign:
            q = q.where(TrackingEvent.utm_campaign == utm_campaign)

        count = (await db.execute(q)).scalar() or 0
        results.append({"name": step, "count": count})

    # Compute conversion rates between consecutive steps
    for i, step in enumerate(results):
        if i == 0 or results[i - 1]["count"] == 0:
            step["conversion_rate"] = None
        else:
            step["conversion_rate"] = round(
                step["count"] / results[i - 1]["count"] * 100, 1
            )

    return results


# ---------------------------------------------------------------------------
# Visitor stats (daily / weekly)
# ---------------------------------------------------------------------------

async def get_visitor_stats(
    db: AsyncSession,
    start_date: datetime,
    end_date: datetime,
) -> dict:
    """Return daily unique visitor counts."""
    q = (
        select(
            func.date(TrackingEvent.created_at).label("day"),
            func.count(distinct(TrackingEvent.visitor_id)).label("count"),
        )
        .where(
            TrackingEvent.event_type == "page_view",
            TrackingEvent.created_at >= start_date,
            TrackingEvent.created_at <= end_date,
        )
        .group_by("day")
        .order_by("day")
    )
    rows = (await db.execute(q)).all()

    total_q = select(func.count(distinct(TrackingEvent.visitor_id))).where(
        TrackingEvent.event_type == "page_view",
        TrackingEvent.created_at >= start_date,
        TrackingEvent.created_at <= end_date,
    )
    total = (await db.execute(total_q)).scalar() or 0

    return {
        "points": [{"date": str(r.day), "count": r.count} for r in rows],
        "total": total,
    }


# ---------------------------------------------------------------------------
# UTM stats
# ---------------------------------------------------------------------------

async def get_utm_stats(
    db: AsyncSession,
    start_date: datetime,
    end_date: datetime,
) -> list[dict]:
    """Return visitor counts grouped by UTM params."""
    q = (
        select(
            TrackingEvent.utm_source,
            TrackingEvent.utm_medium,
            TrackingEvent.utm_campaign,
            func.count(distinct(TrackingEvent.visitor_id)).label("count"),
        )
        .where(
            TrackingEvent.created_at >= start_date,
            TrackingEvent.created_at <= end_date,
            TrackingEvent.utm_source.is_not(None),
        )
        .group_by(
            TrackingEvent.utm_source,
            TrackingEvent.utm_medium,
            TrackingEvent.utm_campaign,
        )
        .order_by(func.count(distinct(TrackingEvent.visitor_id)).desc())
        .limit(50)
    )
    rows = (await db.execute(q)).all()
    return [
        {
            "source": r.utm_source,
            "medium": r.utm_medium,
            "campaign": r.utm_campaign,
            "count": r.count,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Top pages
# ---------------------------------------------------------------------------

async def get_top_pages(
    db: AsyncSession,
    start_date: datetime,
    end_date: datetime,
    limit: int = 20,
) -> list[dict]:
    """Return most visited pages by unique visitors."""
    q = (
        select(
            TrackingEvent.page_path,
            func.count(distinct(TrackingEvent.visitor_id)).label("count"),
        )
        .where(
            TrackingEvent.event_type == "page_view",
            TrackingEvent.created_at >= start_date,
            TrackingEvent.created_at <= end_date,
        )
        .group_by(TrackingEvent.page_path)
        .order_by(func.count(distinct(TrackingEvent.visitor_id)).desc())
        .limit(limit)
    )
    rows = (await db.execute(q)).all()
    return [{"path": r.page_path, "count": r.count} for r in rows]


# ---------------------------------------------------------------------------
# Analytics overview
# ---------------------------------------------------------------------------

async def get_analytics_overview(
    db: AsyncSession,
    start_date: datetime,
    end_date: datetime,
) -> dict:
    """Return key metrics for the analytics overview."""
    # Unique visitors
    visitors_q = select(func.count(distinct(TrackingEvent.visitor_id))).where(
        TrackingEvent.event_type == "page_view",
        TrackingEvent.created_at >= start_date,
        TrackingEvent.created_at <= end_date,
    )
    unique_visitors = (await db.execute(visitors_q)).scalar() or 0

    # Total signups
    signups_q = select(func.count(distinct(TrackingEvent.visitor_id))).where(
        TrackingEvent.event_type == "signup",
        TrackingEvent.created_at >= start_date,
        TrackingEvent.created_at <= end_date,
    )
    total_signups = (await db.execute(signups_q)).scalar() or 0

    # Trial starts
    trials_q = select(func.count(distinct(TrackingEvent.visitor_id))).where(
        TrackingEvent.event_type == "trial_started",
        TrackingEvent.created_at >= start_date,
        TrackingEvent.created_at <= end_date,
    )
    total_trials = (await db.execute(trials_q)).scalar() or 0

    # Paid subscriptions
    subs_q = select(func.count(distinct(TrackingEvent.visitor_id))).where(
        TrackingEvent.event_type == "subscription_created",
        TrackingEvent.created_at >= start_date,
        TrackingEvent.created_at <= end_date,
    )
    total_subs = (await db.execute(subs_q)).scalar() or 0

    # Total revenue (from payments table)
    revenue_q = select(func.coalesce(func.sum(Payment.amount_sek), 0)).where(
        Payment.status == "succeeded",
        Payment.created_at >= start_date,
        Payment.created_at <= end_date,
    )
    total_revenue = (await db.execute(revenue_q)).scalar() or 0

    # Rates
    trial_start_rate = round(total_trials / total_signups * 100, 1) if total_signups > 0 else 0.0
    trial_conversion_rate = round(total_subs / total_trials * 100, 1) if total_trials > 0 else 0.0

    # Average session duration (from session_end events with duration_seconds metadata)
    avg_duration = await get_avg_session_duration(db, start_date, end_date)

    return {
        "unique_visitors": unique_visitors,
        "total_signups": total_signups,
        "total_trials": total_trials,
        "total_subscriptions": total_subs,
        "trial_start_rate": trial_start_rate,
        "trial_conversion_rate": trial_conversion_rate,
        "total_revenue_sek": total_revenue,
        "avg_session_duration_seconds": avg_duration,
    }


# ---------------------------------------------------------------------------
# Session duration
# ---------------------------------------------------------------------------

async def get_avg_session_duration(
    db: AsyncSession,
    start_date: datetime,
    end_date: datetime,
) -> float:
    """Return average session duration in seconds from session_end events."""
    # Use PostgreSQL JSON extraction: (metadata->>'duration_seconds')::float
    duration_expr = cast(
        TrackingEvent.metadata_["duration_seconds"].as_string(),
        Float,
    )
    q = select(func.avg(duration_expr)).where(
        TrackingEvent.event_type == "session_end",
        TrackingEvent.created_at >= start_date,
        TrackingEvent.created_at <= end_date,
        TrackingEvent.metadata_.is_not(None),
    )
    result = (await db.execute(q)).scalar()
    return round(float(result), 1) if result else 0.0
