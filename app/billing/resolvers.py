from __future__ import annotations

import logging
from datetime import datetime

import strawberry
from strawberry.types import Info

from app.auth.models import User
from app.auth.resolvers import _get_user_from_info, _require_user
from app.billing.graphql_types import (
    BillingDetailsType,
    PaymentListType,
    PaymentMethodType,
    PaymentType,
    PlanType,
    SubscriptionType,
    UpdateBillingDetailsInput,
)
from app.billing.models import BillingDetails, Payment, Subscription
from app.billing.service import (
    cancel_subscription as cancel_subscription_svc,
    get_active_subscription,
    get_billing_details,
    get_user_payments,
    list_payment_methods,
    reactivate_subscription as reactivate_subscription_svc,
    upsert_billing_details,
)
from app.cache import cache
from app.database import get_db_session

logger = logging.getLogger(__name__)

_SUBSCRIPTION_CACHE_TTL = 300  # 5 minutes
_BILLING_DETAILS_CACHE_TTL = 600  # 10 minutes

FREE_FEATURES = [
    "1 hemsida (utkast)",
    "Subdomän på qvickosite.com",
    "Grundläggande redigering",
]

BASIC_FEATURES = [
    "AI-genererade hemsidor",
    "Publicera hemsida",
    "Egen domän",
    "Grundläggande statistik",
    "SEO-verktyg",
]

PRO_FEATURES = [
    "Allt i Basic",
    "Obegränsat antal hemsidor",
    "Fullständig statistik",
    "Prioriterad support",
    "Avancerade SEO-verktyg",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sub_to_gql(sub: Subscription) -> SubscriptionType:
    return SubscriptionType(
        id=sub.id,
        status=sub.status.value,
        current_period_start=sub.current_period_start,
        current_period_end=sub.current_period_end,
        cancel_at_period_end=sub.cancel_at_period_end,
        trial_start=sub.trial_start,
        trial_end=sub.trial_end,
        created_at=sub.created_at,
    )


def _payment_to_gql(p: Payment) -> PaymentType:
    return PaymentType(
        id=p.id,
        amount_sek=p.amount_sek,
        currency=p.currency,
        status=p.status.value,
        invoice_url=p.invoice_url,
        created_at=p.created_at,
    )


def _billing_to_gql(b: BillingDetails) -> BillingDetailsType:
    return BillingDetailsType(
        id=b.id,
        billing_name=b.billing_name,
        billing_company=b.billing_company,
        billing_org_number=b.billing_org_number,
        billing_vat_number=b.billing_vat_number,
        billing_email=b.billing_email,
        billing_phone=b.billing_phone,
        address_line1=b.address_line1,
        address_line2=b.address_line2,
        zip=b.zip,
        city=b.city,
        country=b.country,
    )


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

@strawberry.type
class BillingQuery:
    @strawberry.field
    async def my_subscription(self, info: Info) -> SubscriptionType | None:
        user = _require_user(await _get_user_from_info(info))

        cache_key = f"subscription:{user.id}"
        cached = await cache.get(cache_key)
        if cached:
            # Restore ISO strings back to datetime objects
            for field in ("current_period_start", "current_period_end", "trial_start", "trial_end", "created_at"):
                if cached.get(field) and isinstance(cached[field], str):
                    cached[field] = datetime.fromisoformat(cached[field])
            return SubscriptionType(**cached)

        async with get_db_session() as db:
            sub = await get_active_subscription(db, user.id)
            if not sub:
                return None
            gql = _sub_to_gql(sub)
            await cache.set(cache_key, {
                "id": gql.id,
                "status": gql.status,
                "current_period_start": gql.current_period_start.isoformat() if gql.current_period_start else None,
                "current_period_end": gql.current_period_end.isoformat() if gql.current_period_end else None,
                "cancel_at_period_end": gql.cancel_at_period_end,
                "trial_start": gql.trial_start.isoformat() if gql.trial_start else None,
                "trial_end": gql.trial_end.isoformat() if gql.trial_end else None,
                "created_at": gql.created_at.isoformat() if gql.created_at else None,
            }, ttl=_SUBSCRIPTION_CACHE_TTL)
            return gql

    @strawberry.field
    async def my_payments(
        self, info: Info, limit: int = 20, offset: int = 0
    ) -> PaymentListType:
        user = _require_user(await _get_user_from_info(info))
        async with get_db_session() as db:
            payments, total = await get_user_payments(db, user.id, limit, offset)
            return PaymentListType(
                items=[_payment_to_gql(p) for p in payments],
                total=total,
            )

    @strawberry.field
    async def my_billing_details(self, info: Info) -> BillingDetailsType | None:
        user = _require_user(await _get_user_from_info(info))

        cache_key = f"billing_details:{user.id}"
        cached = await cache.get(cache_key)
        if cached:
            return BillingDetailsType(**cached)

        async with get_db_session() as db:
            details = await get_billing_details(db, user.id)
            if not details:
                return None
            gql = _billing_to_gql(details)
            await cache.set(cache_key, {
                "id": gql.id,
                "billing_name": gql.billing_name,
                "billing_company": gql.billing_company,
                "billing_org_number": gql.billing_org_number,
                "billing_vat_number": gql.billing_vat_number,
                "billing_email": gql.billing_email,
                "billing_phone": gql.billing_phone,
                "address_line1": gql.address_line1,
                "address_line2": gql.address_line2,
                "zip": gql.zip,
                "city": gql.city,
                "country": gql.country,
            }, ttl=_BILLING_DETAILS_CACHE_TTL)
            return gql

    @strawberry.field
    async def my_payment_methods(self, info: Info) -> list[PaymentMethodType]:
        user = _require_user(await _get_user_from_info(info))
        methods = await list_payment_methods(user)
        return [
            PaymentMethodType(
                id=m["id"],
                brand=m["brand"],
                last4=m["last4"],
                exp_month=m["exp_month"],
                exp_year=m["exp_year"],
            )
            for m in methods
        ]

    @strawberry.field
    async def available_plans(self) -> list[PlanType]:
        return [
            PlanType(
                key="free",
                name="Free",
                price_sek=0,
                trial_days=0,
                features=FREE_FEATURES,
            ),
            PlanType(
                key="basic",
                name="Basic",
                price_sek=19900,  # 199 SEK in öre
                trial_days=30,
                features=BASIC_FEATURES,
            ),
            PlanType(
                key="pro",
                name="Pro",
                price_sek=29900,  # 299 SEK in öre
                trial_days=30,
                features=PRO_FEATURES,
            ),
        ]


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------

@strawberry.type
class BillingMutation:
    @strawberry.mutation
    async def update_billing_details(
        self, info: Info, input: UpdateBillingDetailsInput
    ) -> BillingDetailsType:
        user = _require_user(await _get_user_from_info(info))
        data = {
            k: v
            for k, v in strawberry.asdict(input).items()
            if v is not None
        }
        async with get_db_session() as db:
            details = await upsert_billing_details(db, user.id, data)
            await db.commit()
            await cache.delete(f"billing_details:{user.id}")
            return _billing_to_gql(details)

    @strawberry.mutation
    async def cancel_subscription(self, info: Info) -> SubscriptionType | None:
        user = _require_user(await _get_user_from_info(info))
        async with get_db_session() as db:
            sub = await cancel_subscription_svc(db, user)
            if sub:
                await db.commit()
                await cache.delete(f"subscription:{user.id}")
                await cache.delete(f"sub_active:{user.id}")
                return _sub_to_gql(sub)
            return None

    @strawberry.mutation
    async def reactivate_subscription(self, info: Info) -> SubscriptionType | None:
        user = _require_user(await _get_user_from_info(info))
        async with get_db_session() as db:
            sub = await reactivate_subscription_svc(db, user)
            if sub:
                await db.commit()
                await cache.delete(f"subscription:{user.id}")
                await cache.delete(f"sub_active:{user.id}")
                return _sub_to_gql(sub)
            return None
