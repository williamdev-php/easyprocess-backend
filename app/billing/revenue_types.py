from __future__ import annotations

from datetime import datetime
from typing import Optional

import strawberry


@strawberry.type
class RevenueChargeType:
    id: str
    amount_sek: int
    currency: str
    status: str
    description: Optional[str]
    customer_email: Optional[str]
    customer_name: Optional[str]
    card_brand: Optional[str]
    card_last4: Optional[str]
    created_at: datetime


@strawberry.type
class RevenueStatsType:
    mrr_sek: int
    total_revenue_sek: int
    active_subscriptions: int
    trialing_subscriptions: int
    charges_count: int
    refunded_sek: int
    recent_charges: list[RevenueChargeType]
