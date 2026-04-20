from __future__ import annotations

import logging
from typing import Optional

import strawberry
from sqlalchemy import case, func, select, or_
from strawberry.types import Info

from app.auth.models import User
from app.auth.resolvers import _get_user_from_info, _require_user
from app.billing.admin_subscriptions_types import (
    AdminSubscriptionFilterInput,
    AdminSubscriptionListType,
    AdminSubscriptionStatsType,
    AdminSubscriptionType,
)
from app.billing.models import Payment, PaymentStatus, Subscription, SubscriptionStatus
from app.database import get_db_session

logger = logging.getLogger(__name__)


def _require_superuser(user: User) -> None:
    if not user.is_superuser:
        raise PermissionError("Superuser access required")


@strawberry.type
class AdminSubscriptionQuery:

    @strawberry.field
    async def admin_subscriptions(
        self,
        info: Info,
        filter: Optional[AdminSubscriptionFilterInput] = None,
    ) -> AdminSubscriptionListType:
        user = _require_user(await _get_user_from_info(info))
        _require_superuser(user)

        f = filter or AdminSubscriptionFilterInput()
        page = max(1, f.page)
        page_size = min(100, max(1, f.page_size))
        offset = (page - 1) * page_size

        async with get_db_session() as db:
            # Build base query with user join
            paid_subq = (
                select(
                    Payment.subscription_id,
                    func.count(Payment.id).label("payments_count"),
                    func.coalesce(
                        func.sum(
                            case(
                                (Payment.status == PaymentStatus.SUCCEEDED, Payment.amount_sek),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("total_paid_sek"),
                )
                .group_by(Payment.subscription_id)
                .subquery()
            )

            base = (
                select(
                    Subscription,
                    User.email.label("user_email"),
                    User.full_name.label("user_name"),
                    User.company_name.label("company_name"),
                    func.coalesce(paid_subq.c.payments_count, 0).label("payments_count"),
                    func.coalesce(paid_subq.c.total_paid_sek, 0).label("total_paid_sek"),
                )
                .join(User, User.id == Subscription.user_id)
                .outerjoin(paid_subq, paid_subq.c.subscription_id == Subscription.id)
            )

            # Filters
            if f.status:
                try:
                    status_enum = SubscriptionStatus(f.status.upper())
                    base = base.where(Subscription.status == status_enum)
                except ValueError:
                    pass

            if f.search:
                term = f"%{f.search}%"
                base = base.where(
                    or_(
                        User.email.ilike(term),
                        User.full_name.ilike(term),
                        User.company_name.ilike(term),
                        Subscription.stripe_subscription_id.ilike(term),
                    )
                )

            # Count
            count_q = select(func.count()).select_from(base.subquery())
            total = (await db.execute(count_q)).scalar() or 0

            # Fetch page
            rows = (
                await db.execute(
                    base.order_by(Subscription.created_at.desc())
                    .offset(offset)
                    .limit(page_size)
                )
            ).all()

            items = [
                AdminSubscriptionType(
                    id=row.Subscription.id,
                    user_id=row.Subscription.user_id,
                    user_email=row.user_email,
                    user_name=row.user_name,
                    company_name=row.company_name,
                    stripe_subscription_id=row.Subscription.stripe_subscription_id,
                    stripe_customer_id=row.Subscription.stripe_customer_id,
                    status=row.Subscription.status.value,
                    current_period_start=row.Subscription.current_period_start,
                    current_period_end=row.Subscription.current_period_end,
                    cancel_at_period_end=row.Subscription.cancel_at_period_end,
                    trial_start=row.Subscription.trial_start,
                    trial_end=row.Subscription.trial_end,
                    created_at=row.Subscription.created_at,
                    updated_at=row.Subscription.updated_at,
                    payments_count=row.payments_count,
                    total_paid_sek=row.total_paid_sek,
                )
                for row in rows
            ]

            return AdminSubscriptionListType(
                items=items,
                total=total,
                page=page,
                page_size=page_size,
            )

    @strawberry.field
    async def admin_subscription_stats(self, info: Info) -> AdminSubscriptionStatsType:
        user = _require_user(await _get_user_from_info(info))
        _require_superuser(user)

        async with get_db_session() as db:
            q = select(
                func.count(Subscription.id).label("total"),
                func.count(func.nullif(Subscription.status != SubscriptionStatus.ACTIVE, True)).label("active"),
                func.count(func.nullif(Subscription.status != SubscriptionStatus.TRIALING, True)).label("trialing"),
                func.count(func.nullif(Subscription.status != SubscriptionStatus.PAST_DUE, True)).label("past_due"),
                func.count(func.nullif(Subscription.status != SubscriptionStatus.CANCELED, True)).label("canceled"),
                func.count(func.nullif(Subscription.status != SubscriptionStatus.INCOMPLETE, True)).label("incomplete"),
            )
            row = (await db.execute(q)).one()

            return AdminSubscriptionStatsType(
                total_subscriptions=row.total,
                active=row.active,
                trialing=row.trialing,
                past_due=row.past_due,
                canceled=row.canceled,
                incomplete=row.incomplete,
            )

    @strawberry.field
    async def admin_subscription(self, info: Info, id: str) -> AdminSubscriptionType | None:
        user = _require_user(await _get_user_from_info(info))
        _require_superuser(user)

        async with get_db_session() as db:
            paid_subq = (
                select(
                    Payment.subscription_id,
                    func.count(Payment.id).label("payments_count"),
                    func.coalesce(
                        func.sum(
                            case(
                                (Payment.status == PaymentStatus.SUCCEEDED, Payment.amount_sek),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("total_paid_sek"),
                )
                .where(Payment.subscription_id == id)
                .group_by(Payment.subscription_id)
                .subquery()
            )

            q = (
                select(
                    Subscription,
                    User.email.label("user_email"),
                    User.full_name.label("user_name"),
                    User.company_name.label("company_name"),
                    func.coalesce(paid_subq.c.payments_count, 0).label("payments_count"),
                    func.coalesce(paid_subq.c.total_paid_sek, 0).label("total_paid_sek"),
                )
                .join(User, User.id == Subscription.user_id)
                .outerjoin(paid_subq, paid_subq.c.subscription_id == Subscription.id)
                .where(Subscription.id == id)
            )

            row = (await db.execute(q)).first()
            if not row:
                return None

            return AdminSubscriptionType(
                id=row.Subscription.id,
                user_id=row.Subscription.user_id,
                user_email=row.user_email,
                user_name=row.user_name,
                company_name=row.company_name,
                stripe_subscription_id=row.Subscription.stripe_subscription_id,
                stripe_customer_id=row.Subscription.stripe_customer_id,
                status=row.Subscription.status.value,
                current_period_start=row.Subscription.current_period_start,
                current_period_end=row.Subscription.current_period_end,
                cancel_at_period_end=row.Subscription.cancel_at_period_end,
                trial_start=row.Subscription.trial_start,
                trial_end=row.Subscription.trial_end,
                created_at=row.Subscription.created_at,
                updated_at=row.Subscription.updated_at,
                payments_count=row.payments_count,
                total_paid_sek=row.total_paid_sek,
            )
