from __future__ import annotations

from datetime import datetime
from typing import Optional

import strawberry


@strawberry.type
class AdminSubscriptionType:
    id: str
    user_id: str
    user_email: Optional[str]
    user_name: Optional[str]
    company_name: Optional[str]
    stripe_subscription_id: str
    stripe_customer_id: str
    status: str
    current_period_start: Optional[datetime]
    current_period_end: Optional[datetime]
    cancel_at_period_end: bool
    trial_start: Optional[datetime]
    trial_end: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    payments_count: int
    total_paid_sek: int


@strawberry.type
class AdminSubscriptionListType:
    items: list[AdminSubscriptionType]
    total: int
    page: int
    page_size: int


@strawberry.type
class AdminSubscriptionStatsType:
    total_subscriptions: int
    active: int
    trialing: int
    past_due: int
    canceled: int
    incomplete: int


@strawberry.input
class AdminSubscriptionFilterInput:
    search: Optional[str] = None
    status: Optional[str] = None
    page: int = 1
    page_size: int = 20
