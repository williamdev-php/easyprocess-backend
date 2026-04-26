"""AutoBlogger billing endpoints — Stripe subscriptions for AutoBlogger plans.

Uses the same Stripe account and customer IDs as Qvicko, but tracks
subscriptions/payments in the 'autoblogger' schema.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.autoblogger.auth_dependencies import get_current_autoblogger_user
from app.autoblogger.models import AutoBloggerUser
from app.billing.service import (
    get_or_create_stripe_customer,
    stripe,
    _get_period,
    _ts_to_dt,
    _get_metadata,
)
from app.config import settings
from app.database import get_db

from app.autoblogger.credits import reset_credits_for_user, PLAN_CREDITS
from app.autoblogger.models import (
    AutoBloggerPayment,
    AutoBloggerSubscription,
    CreditBalance,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/autoblogger/billing", tags=["autoblogger-billing"])

VALID_PLANS = {"pro", "business"}


def _get_ab_price_id(plan: str) -> str:
    if plan == "pro":
        return settings.STRIPE_AUTOBLOGGER_PRO_PRICE_ID
    elif plan == "business":
        return settings.STRIPE_AUTOBLOGGER_BUSINESS_PRICE_ID
    raise ValueError(f"Unknown AutoBlogger plan: {plan}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_active_ab_subscription(
    db: AsyncSession, user_id: str
) -> AutoBloggerSubscription | None:
    result = await db.execute(
        select(AutoBloggerSubscription).where(
            AutoBloggerSubscription.user_id == user_id,
            AutoBloggerSubscription.status.in_(["trialing", "active", "past_due"]),
        )
    )
    return result.scalar_one_or_none()


async def _get_or_create_credit_balance(db: AsyncSession, user_id: str) -> CreditBalance:
    result = await db.execute(
        select(CreditBalance).where(CreditBalance.user_id == user_id)
    )
    balance = result.scalar_one_or_none()
    if balance is None:
        balance = CreditBalance(user_id=user_id)
        db.add(balance)
        await db.flush()
    return balance


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class SubscribeRequest(BaseModel):
    plan: str  # "pro" or "business"


class SubscriptionResponse(BaseModel):
    id: str
    user_id: str
    stripe_subscription_id: str
    plan: str
    status: str
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    trial_start: datetime | None = None
    trial_end: datetime | None = None
    cancel_at_period_end: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PaymentResponse(BaseModel):
    id: str
    user_id: str
    amount: int
    currency: str
    status: str
    stripe_invoice_id: str | None = None
    invoice_url: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# POST /setup-intent
# ---------------------------------------------------------------------------

@router.post("/setup-intent")
async def create_setup_intent(
    user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a Stripe SetupIntent for collecting card details."""
    customer_id = await get_or_create_stripe_customer(db, user)

    setup_intent = stripe.SetupIntent.create(
        customer=customer_id,
        payment_method_types=["card"],
        metadata={"autoblogger_user_id": user.id},
    )

    return {"client_secret": setup_intent.client_secret}


# ---------------------------------------------------------------------------
# POST /subscribe
# ---------------------------------------------------------------------------

@router.post("/subscribe")
async def subscribe(
    body: SubscribeRequest,
    user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
):
    """Create an AutoBlogger subscription with a 14-day trial."""
    if body.plan not in VALID_PLANS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid plan. Choose 'pro' or 'business'.",
        )

    # Check for existing active subscription
    existing = await _get_active_ab_subscription(db, user.id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You already have an active AutoBlogger subscription.",
        )

    price_id = _get_ab_price_id(body.plan)
    if not price_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Price ID not configured for this plan.",
        )

    customer_id = await get_or_create_stripe_customer(db, user)

    # Create Stripe subscription
    stripe_sub = stripe.Subscription.create(
        customer=customer_id,
        items=[{"price": price_id}],
        trial_period_days=14,
        payment_settings={
            "payment_method_types": ["card"],
            "save_default_payment_method": "on_subscription",
        },
        metadata={
            "autoblogger_user_id": user.id,
            "autoblogger_plan": body.plan,
        },
    )

    # Save to DB
    period_start, period_end = _get_period(stripe_sub)
    ab_sub = AutoBloggerSubscription(
        user_id=user.id,
        stripe_subscription_id=stripe_sub.id,
        stripe_customer_id=customer_id,
        plan=body.plan,
        status=stripe_sub.status,
        current_period_start=_ts_to_dt(period_start),
        current_period_end=_ts_to_dt(period_end),
        trial_start=_ts_to_dt(stripe_sub.trial_start) if stripe_sub.trial_start else None,
        trial_end=_ts_to_dt(stripe_sub.trial_end) if stripe_sub.trial_end else None,
        cancel_at_period_end=stripe_sub.cancel_at_period_end,
    )
    db.add(ab_sub)
    await db.flush()

    # Update credit balance
    credits = PLAN_CREDITS.get(body.plan, 5)
    balance = await _get_or_create_credit_balance(db, user.id)
    balance.plan_credits_monthly = credits
    balance.credits_remaining = credits
    balance.last_reset_at = datetime.now(timezone.utc)
    await db.flush()

    return {
        "subscription_id": ab_sub.id,
        "stripe_subscription_id": ab_sub.stripe_subscription_id,
        "status": ab_sub.status,
        "plan": ab_sub.plan,
        "trial_end": ab_sub.trial_end.isoformat() if ab_sub.trial_end else None,
    }


# ---------------------------------------------------------------------------
# GET /subscription
# ---------------------------------------------------------------------------

@router.get("/subscription")
async def get_subscription(
    user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the current AutoBlogger subscription or null."""
    sub = await _get_active_ab_subscription(db, user.id)
    if not sub:
        return None
    return SubscriptionResponse.model_validate(sub)


# ---------------------------------------------------------------------------
# GET /payment-methods
# ---------------------------------------------------------------------------

@router.get("/payment-methods")
async def get_payment_methods(
    user: AutoBloggerUser = Depends(get_current_autoblogger_user),
):
    """List card payment methods for the user."""
    if not user.stripe_customer_id:
        return {"payment_methods": []}

    methods = stripe.PaymentMethod.list(
        customer=user.stripe_customer_id,
        type="card",
        limit=10,
    )

    return {
        "payment_methods": [
            {
                "brand": pm.card.brand,
                "last4": pm.card.last4,
                "exp_month": pm.card.exp_month,
                "exp_year": pm.card.exp_year,
            }
            for pm in methods.data
        ]
    }


# ---------------------------------------------------------------------------
# POST /cancel
# ---------------------------------------------------------------------------

@router.post("/cancel")
async def cancel_subscription(
    user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel AutoBlogger subscription at end of current period."""
    sub = await _get_active_ab_subscription(db, user.id)
    if not sub:
        raise HTTPException(status_code=404, detail="No active AutoBlogger subscription found.")

    stripe.Subscription.modify(
        sub.stripe_subscription_id,
        cancel_at_period_end=True,
    )

    sub.cancel_at_period_end = True
    await db.flush()

    return {"status": sub.status, "cancel_at_period_end": sub.cancel_at_period_end}


# ---------------------------------------------------------------------------
# POST /reactivate
# ---------------------------------------------------------------------------

@router.post("/reactivate")
async def reactivate_subscription(
    user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove cancel_at_period_end on the AutoBlogger subscription."""
    sub = await _get_active_ab_subscription(db, user.id)
    if not sub or not sub.cancel_at_period_end:
        raise HTTPException(status_code=404, detail="No subscription to reactivate.")

    stripe.Subscription.modify(
        sub.stripe_subscription_id,
        cancel_at_period_end=False,
    )

    sub.cancel_at_period_end = False
    await db.flush()

    return {"status": sub.status, "cancel_at_period_end": sub.cancel_at_period_end}


# ---------------------------------------------------------------------------
# GET /payments
# ---------------------------------------------------------------------------

@router.get("/payments")
async def list_payments(
    user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
):
    """List AutoBlogger payment history."""
    result = await db.execute(
        select(AutoBloggerPayment)
        .where(AutoBloggerPayment.user_id == user.id)
        .order_by(AutoBloggerPayment.created_at.desc())
        .limit(20)
    )
    payments = result.scalars().all()
    return {"payments": [PaymentResponse.model_validate(p) for p in payments]}


# ---------------------------------------------------------------------------
# POST /webhook  — Stripe webhook for AutoBlogger subscription events
# ---------------------------------------------------------------------------

@router.post("/webhook")
async def stripe_autoblogger_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Handle Stripe webhook events for AutoBlogger subscriptions."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload,
            sig_header,
            settings.STRIPE_WEBHOOK_SECRET,  # Same Stripe account
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event["type"]
    data_object = event["data"]["object"]

    if event_type == "invoice.payment_succeeded":
        user_id = _get_metadata(data_object, "autoblogger_user_id")
        plan = _get_metadata(data_object, "autoblogger_plan", "pro")
        if user_id:
            await reset_credits_for_user(db, user_id, plan)
            logger.info("AutoBlogger credits reset for user %s (invoice paid, plan=%s)", user_id, plan)

    elif event_type == "customer.subscription.updated":
        stripe_sub_id = data_object.get("id")
        result = await db.execute(
            select(AutoBloggerSubscription).where(
                AutoBloggerSubscription.stripe_subscription_id == stripe_sub_id
            )
        )
        sub = result.scalar_one_or_none()
        if sub:
            sub.status = data_object.get("status", sub.status)
            period_start, period_end = _get_period(data_object)
            sub.current_period_start = _ts_to_dt(period_start)
            sub.current_period_end = _ts_to_dt(period_end)
            sub.cancel_at_period_end = data_object.get("cancel_at_period_end", False)
            sub.updated_at = datetime.now(timezone.utc)
            await db.flush()
            logger.info("AutoBlogger subscription %s updated — status=%s", stripe_sub_id, sub.status)

    elif event_type == "customer.subscription.deleted":
        stripe_sub_id = data_object.get("id")
        result = await db.execute(
            select(AutoBloggerSubscription).where(
                AutoBloggerSubscription.stripe_subscription_id == stripe_sub_id
            )
        )
        sub = result.scalar_one_or_none()
        if sub:
            sub.status = "canceled"
            sub.updated_at = datetime.now(timezone.utc)
            await db.flush()

            # Reset to free tier credits
            balance = await _get_or_create_credit_balance(db, sub.user_id)
            balance.plan_credits_monthly = 5
            balance.credits_remaining = min(balance.credits_remaining, 5)
            await db.flush()
            logger.info("AutoBlogger subscription %s canceled — user %s reset to free tier", stripe_sub_id, sub.user_id)

    return {"status": "ok"}
