from __future__ import annotations

import logging
from datetime import datetime

import strawberry
from strawberry.types import Info

from app.auth.resolvers import _get_user_from_info, _require_user
from app.database import get_db_session
from app.tracking.graphql_types import (
    AnalyticsOverviewType,
    DailyVisitorPointType,
    FunnelStatsType,
    FunnelStepType,
    TopPageType,
    UtmEntryType,
    VisitorStatsType,
)
from app.tracking.service import (
    get_analytics_overview,
    get_funnel_stats,
    get_top_pages,
    get_utm_stats,
    get_visitor_stats,
)

logger = logging.getLogger(__name__)


def _require_superuser(user) -> None:
    if not user.is_superuser:
        raise PermissionError("Superuser access required")


@strawberry.type
class AnalyticsQuery:

    @strawberry.field
    async def funnel_stats(
        self,
        info: Info,
        start_date: str,
        end_date: str,
        utm_source: str | None = None,
        utm_campaign: str | None = None,
    ) -> FunnelStatsType:
        user = _require_user(await _get_user_from_info(info))
        _require_superuser(user)

        sd = datetime.fromisoformat(start_date)
        ed = datetime.fromisoformat(end_date)

        async with get_db_session() as db:
            steps = await get_funnel_stats(db, sd, ed, utm_source, utm_campaign)

        return FunnelStatsType(
            steps=[FunnelStepType(**s) for s in steps],
            start_date=start_date,
            end_date=end_date,
        )

    @strawberry.field
    async def visitor_stats(
        self,
        info: Info,
        start_date: str,
        end_date: str,
    ) -> VisitorStatsType:
        user = _require_user(await _get_user_from_info(info))
        _require_superuser(user)

        sd = datetime.fromisoformat(start_date)
        ed = datetime.fromisoformat(end_date)

        async with get_db_session() as db:
            data = await get_visitor_stats(db, sd, ed)

        return VisitorStatsType(
            points=[DailyVisitorPointType(**p) for p in data["points"]],
            total=data["total"],
        )

    @strawberry.field
    async def utm_stats(
        self,
        info: Info,
        start_date: str,
        end_date: str,
    ) -> list[UtmEntryType]:
        user = _require_user(await _get_user_from_info(info))
        _require_superuser(user)

        sd = datetime.fromisoformat(start_date)
        ed = datetime.fromisoformat(end_date)

        async with get_db_session() as db:
            entries = await get_utm_stats(db, sd, ed)

        return [UtmEntryType(**e) for e in entries]

    @strawberry.field
    async def top_pages(
        self,
        info: Info,
        start_date: str,
        end_date: str,
        limit: int = 20,
    ) -> list[TopPageType]:
        user = _require_user(await _get_user_from_info(info))
        _require_superuser(user)

        sd = datetime.fromisoformat(start_date)
        ed = datetime.fromisoformat(end_date)

        async with get_db_session() as db:
            pages = await get_top_pages(db, sd, ed, limit)

        return [TopPageType(**p) for p in pages]

    @strawberry.field
    async def analytics_overview(
        self,
        info: Info,
        start_date: str,
        end_date: str,
    ) -> AnalyticsOverviewType:
        user = _require_user(await _get_user_from_info(info))
        _require_superuser(user)

        sd = datetime.fromisoformat(start_date)
        ed = datetime.fromisoformat(end_date)

        async with get_db_session() as db:
            data = await get_analytics_overview(db, sd, ed)

        return AnalyticsOverviewType(**data)
