from __future__ import annotations

import logging

import strawberry
from strawberry.types import Info

from app.auth.resolvers import _get_user_from_info, _require_user
from app.billing.revenue_service import get_revenue_stats
from app.billing.revenue_types import RevenueChargeType, RevenueStatsType

logger = logging.getLogger(__name__)


def _require_superuser(user) -> None:
    if not user.is_superuser:
        raise PermissionError("Superuser access required")


@strawberry.type
class RevenueQuery:

    @strawberry.field
    async def revenue_stats(
        self,
        info: Info,
        limit: int = 30,
    ) -> RevenueStatsType:
        user = _require_user(await _get_user_from_info(info))
        _require_superuser(user)

        data = await get_revenue_stats(limit=limit)

        return RevenueStatsType(
            mrr_sek=data["mrr_sek"],
            total_revenue_sek=data["total_revenue_sek"],
            active_subscriptions=data["active_subscriptions"],
            trialing_subscriptions=data["trialing_subscriptions"],
            charges_count=data["charges_count"],
            refunded_sek=data["refunded_sek"],
            recent_charges=[
                RevenueChargeType(**ch) for ch in data["recent_charges"]
            ],
        )
