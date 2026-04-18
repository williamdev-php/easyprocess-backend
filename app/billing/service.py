"""
Stripe billing service for Qvicko subscriptions.

Plans:
- Basic: 199 SEK/month with 30-day free trial
- Pro: 299 SEK/month with 30-day free trial
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import stripe
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.billing.models import (
    BillingDetails,
    Payment,
    PaymentStatus,
    Subscription,
    SubscriptionStatus,
)
from app.config import settings

logger = logging.getLogger(__name__)

# Initialize Stripe
stripe.api_key = settings.STRIPE_SECRET_KEY
stripe.max_network_retries = 2
stripe.default_http_client = stripe.HTTPXClient(timeout=30, allow_sync_methods=True)

TRIAL_DAYS = 30

VALID_PLANS = {"basic", "pro"}


def _get_price_id_for_plan(plan: str) -> str:
    """Return the Stripe Price ID for a given plan key."""
    if plan == "basic":
        return settings.STRIPE_BASIC_PRICE_ID or settings.STRIPE_PRICE_ID
    elif plan == "pro":
        return settings.STRIPE_PRO_PRICE_ID
    raise ValueError(f"Unknown plan: {plan}")


# ---------------------------------------------------------------------------
# Stripe Customer
# ---------------------------------------------------------------------------

async def get_or_create_stripe_customer(db: AsyncSession, user: User) -> str:
    """Ensure user has a Stripe customer ID. Creates one if missing."""
    if user.stripe_customer_id:
        return user.stripe_customer_id

    customer = stripe.Customer.create(
        email=user.email,
        name=user.full_name,
        metadata={"qvicko_user_id": user.id},
    )
    user.stripe_customer_id = customer.id
    db.add(user)
    await db.flush()
    return customer.id


# ---------------------------------------------------------------------------
# Setup Intent (for collecting card without charging)
# ---------------------------------------------------------------------------

async def create_setup_intent(db: AsyncSession, user: User) -> dict:
    """Create a Stripe SetupIntent for collecting a payment method."""
    customer_id = await get_or_create_stripe_customer(db, user)

    setup_intent = stripe.SetupIntent.create(
        customer=customer_id,
        payment_method_types=["card"],
        metadata={"qvicko_user_id": user.id},
    )

    return {
        "client_secret": setup_intent.client_secret,
        "setup_intent_id": setup_intent.id,
    }


# ---------------------------------------------------------------------------
# Subscription
# ---------------------------------------------------------------------------

async def create_subscription(
    db: AsyncSession,
    user: User,
    payment_method_id: str,
    plan: str = "basic",
    with_trial: bool = True,
) -> Subscription:
    """
    Create a Stripe subscription for the user.
    Attaches payment method, sets as default, creates subscription with optional trial.
    """
    price_id = _get_price_id_for_plan(plan)
    customer_id = await get_or_create_stripe_customer(db, user)

    # Attach payment method to customer and set as default
    stripe.PaymentMethod.attach(payment_method_id, customer=customer_id)
    stripe.Customer.modify(
        customer_id,
        invoice_settings={"default_payment_method": payment_method_id},
    )

    # Create subscription
    sub_params: dict = {
        "customer": customer_id,
        "items": [{"price": price_id}],
        "payment_behavior": "default_incomplete",
        "payment_settings": {
            "payment_method_types": ["card"],
            "save_default_payment_method": "on_subscription",
        },
        "expand": ["latest_invoice.payment_intent"],
        "metadata": {"qvicko_user_id": user.id, "qvicko_plan": plan},
    }

    if with_trial:
        sub_params["trial_period_days"] = TRIAL_DAYS

    stripe_sub = stripe.Subscription.create(**sub_params)

    # Save subscription to DB
    period_start, period_end = _get_period(stripe_sub)
    subscription = Subscription(
        user_id=user.id,
        stripe_subscription_id=stripe_sub.id,
        stripe_customer_id=customer_id,
        status=_map_stripe_status(stripe_sub.status),
        current_period_start=_ts_to_dt(period_start),
        current_period_end=_ts_to_dt(period_end),
        cancel_at_period_end=stripe_sub.cancel_at_period_end,
        trial_start=_ts_to_dt(stripe_sub.trial_start) if stripe_sub.trial_start else None,
        trial_end=_ts_to_dt(stripe_sub.trial_end) if stripe_sub.trial_end else None,
    )
    db.add(subscription)
    await db.flush()

    # Link subscription to user
    user.subscription_id = subscription.id
    db.add(user)
    await db.flush()

    return subscription


async def create_subscription_after_setup(
    db: AsyncSession,
    user: User,
    plan: str = "basic",
    with_trial: bool = True,
) -> Subscription:
    """
    Create a subscription using the customer's default payment method
    (set via SetupIntent confirmation).
    """
    price_id = _get_price_id_for_plan(plan)
    customer_id = await get_or_create_stripe_customer(db, user)

    sub_params: dict = {
        "customer": customer_id,
        "items": [{"price": price_id}],
        "payment_settings": {
            "payment_method_types": ["card"],
            "save_default_payment_method": "on_subscription",
        },
        "expand": ["latest_invoice.payment_intent"],
        "metadata": {"qvicko_user_id": user.id, "qvicko_plan": plan},
    }

    if with_trial:
        sub_params["trial_period_days"] = TRIAL_DAYS

    stripe_sub = stripe.Subscription.create(**sub_params)

    period_start, period_end = _get_period(stripe_sub)
    subscription = Subscription(
        user_id=user.id,
        stripe_subscription_id=stripe_sub.id,
        stripe_customer_id=customer_id,
        status=_map_stripe_status(stripe_sub.status),
        current_period_start=_ts_to_dt(period_start),
        current_period_end=_ts_to_dt(period_end),
        cancel_at_period_end=stripe_sub.cancel_at_period_end,
        trial_start=_ts_to_dt(stripe_sub.trial_start) if stripe_sub.trial_start else None,
        trial_end=_ts_to_dt(stripe_sub.trial_end) if stripe_sub.trial_end else None,
    )
    db.add(subscription)
    await db.flush()

    user.subscription_id = subscription.id
    db.add(user)
    await db.flush()

    return subscription


async def cancel_subscription(db: AsyncSession, user: User) -> Subscription | None:
    """Cancel subscription at end of current period."""
    sub = await get_active_subscription(db, user.id)
    if not sub:
        return None

    stripe.Subscription.modify(
        sub.stripe_subscription_id,
        cancel_at_period_end=True,
    )

    sub.cancel_at_period_end = True
    db.add(sub)
    await db.flush()
    return sub


async def reactivate_subscription(db: AsyncSession, user: User) -> Subscription | None:
    """Reactivate a subscription that was set to cancel at period end."""
    sub = await get_active_subscription(db, user.id)
    if not sub or not sub.cancel_at_period_end:
        return None

    stripe.Subscription.modify(
        sub.stripe_subscription_id,
        cancel_at_period_end=False,
    )

    sub.cancel_at_period_end = False
    db.add(sub)
    await db.flush()
    return sub


async def get_active_subscription(db: AsyncSession, user_id: str) -> Subscription | None:
    """Get user's active or trialing subscription."""
    result = await db.execute(
        select(Subscription)
        .where(
            Subscription.user_id == user_id,
            Subscription.status.in_([
                SubscriptionStatus.ACTIVE,
                SubscriptionStatus.TRIALING,
                SubscriptionStatus.PAST_DUE,
            ]),
        )
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_subscription_by_stripe_id(
    db: AsyncSession, stripe_sub_id: str
) -> Subscription | None:
    result = await db.execute(
        select(Subscription).where(
            Subscription.stripe_subscription_id == stripe_sub_id
        )
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Payment Methods
# ---------------------------------------------------------------------------

async def list_payment_methods(user: User) -> list[dict]:
    """List card payment methods for the user."""
    if not user.stripe_customer_id:
        return []

    methods = stripe.PaymentMethod.list(
        customer=user.stripe_customer_id,
        type="card",
        limit=10,
    )

    return [
        {
            "id": pm.id,
            "brand": pm.card.brand,
            "last4": pm.card.last4,
            "exp_month": pm.card.exp_month,
            "exp_year": pm.card.exp_year,
        }
        for pm in methods.data
    ]


async def detach_payment_method(payment_method_id: str) -> None:
    """Detach a payment method from its customer."""
    stripe.PaymentMethod.detach(payment_method_id)


# ---------------------------------------------------------------------------
# Payments / History
# ---------------------------------------------------------------------------

async def get_user_payments(
    db: AsyncSession, user_id: str, limit: int = 20, offset: int = 0
) -> tuple[list[Payment], int]:
    """Get paginated payment history for a user."""
    count_result = await db.execute(
        select(Payment).where(Payment.user_id == user_id)
    )
    total = len(count_result.all())

    result = await db.execute(
        select(Payment)
        .where(Payment.user_id == user_id)
        .order_by(Payment.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all()), total


# ---------------------------------------------------------------------------
# Billing Details
# ---------------------------------------------------------------------------

async def get_billing_details(db: AsyncSession, user_id: str) -> BillingDetails | None:
    result = await db.execute(
        select(BillingDetails).where(BillingDetails.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def upsert_billing_details(
    db: AsyncSession,
    user_id: str,
    data: dict,
) -> BillingDetails:
    """Create or update billing details for a user."""
    existing = await get_billing_details(db, user_id)

    if existing:
        for key, value in data.items():
            if hasattr(existing, key):
                setattr(existing, key, value)
        db.add(existing)
    else:
        existing = BillingDetails(user_id=user_id, **data)
        db.add(existing)

    await db.flush()
    return existing


# ---------------------------------------------------------------------------
# Webhook processing
# ---------------------------------------------------------------------------

async def handle_subscription_created(db: AsyncSession, stripe_sub: stripe.Subscription) -> None:
    """Handle customer.subscription.created event."""
    user_id = _get_metadata(stripe_sub, "qvicko_user_id")
    if not user_id:
        # Try to find user by customer ID
        user = await _get_user_by_customer_id(db, stripe_sub.customer)
        if not user:
            logger.warning("No user found for subscription %s", stripe_sub.id)
            return
        user_id = user.id

    existing = await get_subscription_by_stripe_id(db, stripe_sub.id)
    if existing:
        _update_sub_from_stripe(existing, stripe_sub)
        db.add(existing)
    else:
        period_start, period_end = _get_period(stripe_sub)
        sub = Subscription(
            user_id=user_id,
            stripe_subscription_id=stripe_sub.id,
            stripe_customer_id=stripe_sub.customer,
            status=_map_stripe_status(stripe_sub.status),
            current_period_start=_ts_to_dt(period_start),
            current_period_end=_ts_to_dt(period_end),
            cancel_at_period_end=stripe_sub.cancel_at_period_end,
            trial_start=_ts_to_dt(stripe_sub.trial_start) if stripe_sub.trial_start else None,
            trial_end=_ts_to_dt(stripe_sub.trial_end) if stripe_sub.trial_end else None,
        )
        db.add(sub)
        await db.flush()

        # Link to user
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user:
            user.subscription_id = sub.id
            db.add(user)

    await db.flush()


async def handle_subscription_updated(db: AsyncSession, stripe_sub: stripe.Subscription) -> None:
    """Handle customer.subscription.updated event."""
    sub = await get_subscription_by_stripe_id(db, stripe_sub.id)
    if not sub:
        logger.warning("Subscription %s not found in DB for update", stripe_sub.id)
        return

    _update_sub_from_stripe(sub, stripe_sub)
    db.add(sub)
    await db.flush()


async def handle_subscription_deleted(db: AsyncSession, stripe_sub: stripe.Subscription) -> None:
    """Handle customer.subscription.deleted event."""
    sub = await get_subscription_by_stripe_id(db, stripe_sub.id)
    if not sub:
        return

    sub.status = SubscriptionStatus.CANCELED
    sub.cancel_at_period_end = False
    db.add(sub)
    await db.flush()


async def handle_invoice_paid(db: AsyncSession, invoice: stripe.Invoice) -> None:
    """Handle invoice.payment_succeeded event — save payment, renew expires_at."""
    user = await _get_user_by_customer_id(db, invoice.customer)
    if not user:
        logger.warning("No user for customer %s on invoice %s", invoice.customer, invoice.id)
        return

    pi_id = _get_invoice_payment_intent_id(invoice)

    # Deduplicate
    if pi_id:
        existing = await db.execute(
            select(Payment).where(Payment.stripe_payment_intent_id == pi_id)
        )
        if existing.scalar_one_or_none():
            return

    # Find subscription
    sub_id = _get_invoice_subscription_id(invoice)
    sub = None
    if sub_id:
        sub = await get_subscription_by_stripe_id(db, sub_id)

    payment = Payment(
        user_id=user.id,
        subscription_id=sub.id if sub else None,
        stripe_payment_intent_id=pi_id,
        stripe_invoice_id=invoice.id,
        amount_sek=invoice.amount_paid,
        currency=invoice.currency or "sek",
        status=PaymentStatus.SUCCEEDED,
        invoice_url=getattr(invoice, "hosted_invoice_url", None),
    )
    db.add(payment)

    # Renew expires_at on all user's published sites
    if sub:
        from app.sites.models import GeneratedSite, SiteStatus
        result = await db.execute(
            select(GeneratedSite).where(
                GeneratedSite.lead.has(created_by=user.id),
                GeneratedSite.status.in_([SiteStatus.PUBLISHED, SiteStatus.PURCHASED]),
            )
        )
        sites = result.scalars().all()
        period_end = sub.current_period_end or _ts_to_dt(
            invoice.lines.data[0].period.end if invoice.lines.data else None
        )
        for site in sites:
            if period_end:
                site.expires_at = period_end
                db.add(site)

    await db.flush()


async def handle_invoice_failed(db: AsyncSession, invoice: stripe.Invoice) -> None:
    """Handle invoice.payment_failed event."""
    user = await _get_user_by_customer_id(db, invoice.customer)
    if not user:
        return

    pi_id = _get_invoice_payment_intent_id(invoice)
    sub_stripe_id = _get_invoice_subscription_id(invoice)

    sub = None
    if sub_stripe_id:
        sub = await get_subscription_by_stripe_id(db, sub_stripe_id)
        if sub:
            sub.status = SubscriptionStatus.PAST_DUE
            db.add(sub)

    payment = Payment(
        user_id=user.id,
        subscription_id=sub.id if sub else None,
        stripe_payment_intent_id=pi_id,
        stripe_invoice_id=invoice.id,
        amount_sek=invoice.amount_due,
        currency=invoice.currency or "sek",
        status=PaymentStatus.FAILED,
        invoice_url=getattr(invoice, "hosted_invoice_url", None),
    )
    db.add(payment)
    await db.flush()

    # Send warning email
    try:
        await _send_payment_failed_email(user)
    except Exception:
        logger.exception("Failed to send payment failed email to %s", user.email)


async def handle_trial_will_end(db: AsyncSession, stripe_sub: stripe.Subscription) -> None:
    """Handle customer.subscription.trial_will_end event (3 days before trial ends)."""
    user_id = _get_metadata(stripe_sub, "qvicko_user_id")
    if not user_id:
        user = await _get_user_by_customer_id(db, stripe_sub.customer)
        if not user:
            return
        user_id = user.id
    else:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

    if user:
        try:
            await _send_trial_ending_email(user)
        except Exception:
            logger.exception("Failed to send trial ending email to %s", user.email)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _map_stripe_status(status: str) -> SubscriptionStatus:
    mapping = {
        "trialing": SubscriptionStatus.TRIALING,
        "active": SubscriptionStatus.ACTIVE,
        "past_due": SubscriptionStatus.PAST_DUE,
        "canceled": SubscriptionStatus.CANCELED,
        "incomplete": SubscriptionStatus.INCOMPLETE,
        "incomplete_expired": SubscriptionStatus.CANCELED,
        "unpaid": SubscriptionStatus.PAST_DUE,
    }
    return mapping.get(status, SubscriptionStatus.INCOMPLETE)


def _ts_to_dt(ts: int | None) -> datetime | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def _get_period(stripe_sub) -> tuple[int | None, int | None]:
    """Extract current_period_start/end from a Stripe subscription.

    In Stripe SDK v15+ (API 2025+), these fields moved from the
    top-level subscription to items.data[*].
    """
    # Try top-level first (older API / SimpleNamespace in tests)
    start = getattr(stripe_sub, "current_period_start", None)
    end = getattr(stripe_sub, "current_period_end", None)
    if start is not None and end is not None:
        return start, end

    # Fall back to items.data[0]
    try:
        item = stripe_sub.items.data[0] if hasattr(stripe_sub, "items") else None
        if item:
            return (
                getattr(item, "current_period_start", None),
                getattr(item, "current_period_end", None),
            )
    except (IndexError, AttributeError):
        pass

    return None, None


def _get_metadata(obj, key: str, default=None):
    """Safely get a metadata value from a Stripe object or dict."""
    meta = getattr(obj, "metadata", None) or {}
    if isinstance(meta, dict):
        return meta.get(key, default)
    # StripeObject — use bracket access
    try:
        return meta[key]
    except (KeyError, AttributeError):
        return default


def _update_sub_from_stripe(sub: Subscription, stripe_sub: stripe.Subscription) -> None:
    sub.status = _map_stripe_status(stripe_sub.status)
    period_start, period_end = _get_period(stripe_sub)
    sub.current_period_start = _ts_to_dt(period_start)
    sub.current_period_end = _ts_to_dt(period_end)
    sub.cancel_at_period_end = stripe_sub.cancel_at_period_end
    sub.trial_start = _ts_to_dt(stripe_sub.trial_start) if stripe_sub.trial_start else None
    sub.trial_end = _ts_to_dt(stripe_sub.trial_end) if stripe_sub.trial_end else None


def _get_invoice_payment_intent_id(invoice) -> str | None:
    """Extract payment_intent ID from an invoice.

    In Stripe API 2025+, `invoice.payment_intent` was removed.
    The PI is now under `invoice.payments.data[0].payment.payment_intent.id`.
    """
    # Legacy / SimpleNamespace (old API or mocks)
    pi = getattr(invoice, "_data", {}).get("payment_intent") if hasattr(invoice, "_data") else getattr(invoice, "payment_intent", None)
    if pi:
        return pi if isinstance(pi, str) else getattr(pi, "id", pi)

    # New API: payments.data[*].payment.payment_intent
    try:
        payments = invoice.payments
        if payments and payments.data:
            payment_obj = payments.data[0].payment
            pi_obj = payment_obj.payment_intent if hasattr(payment_obj, "payment_intent") else None
            if pi_obj:
                return pi_obj.id if hasattr(pi_obj, "id") else pi_obj
    except (AttributeError, IndexError):
        pass

    return None


def _get_invoice_subscription_id(invoice) -> str | None:
    """Extract subscription ID from an invoice.

    In Stripe API 2025+, `invoice.subscription` was removed.
    It's now under `invoice.parent.subscription_details.subscription`.
    """
    # Legacy / SimpleNamespace
    sub = getattr(invoice, "_data", {}).get("subscription") if hasattr(invoice, "_data") else getattr(invoice, "subscription", None)
    if sub:
        return sub if isinstance(sub, str) else getattr(sub, "id", sub)

    # New API: parent.subscription_details.subscription
    try:
        parent = invoice.parent
        if parent and hasattr(parent, "subscription_details"):
            sd = parent.subscription_details
            if sd:
                sub_val = sd.subscription if hasattr(sd, "subscription") else sd.get("subscription")
                return sub_val
    except (AttributeError, KeyError):
        pass

    return None


async def _get_user_by_customer_id(db: AsyncSession, customer_id: str) -> User | None:
    result = await db.execute(
        select(User).where(User.stripe_customer_id == customer_id)
    )
    return result.scalar_one_or_none()


async def _send_payment_failed_email(user: User) -> None:
    """Send payment failed notification email via Resend."""
    import httpx
    if not settings.RESEND_API_KEY:
        return

    async with httpx.AsyncClient(timeout=15.0) as client:
        await client.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": f"{settings.RESEND_FROM_NAME} <{settings.RESEND_FROM_EMAIL}>",
                "to": [user.email],
                "subject": "Betalningen misslyckades — Qvicko",
                "html": f"""
                <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
                    <h2>Hej {user.full_name},</h2>
                    <p>Vi kunde inte genomföra din senaste betalning för ditt Qvicko-abonnemang.</p>
                    <p>Vänligen uppdatera ditt betalkort i din dashboard under <strong>Betalning</strong> för att undvika avbrott i tjänsten.</p>
                    <p>Om din betalning inte uppdateras inom 14 dagar kommer dina publicerade sidor att arkiveras.</p>
                    <p><a href="{settings.FRONTEND_URL}/dashboard/billing" style="background: #4F46E5; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; display: inline-block;">Uppdatera betalkort</a></p>
                    <p>Med vänlig hälsning,<br>Qvicko-teamet</p>
                </div>
                """,
            },
        )


async def _send_trial_ending_email(user: User) -> None:
    """Send trial ending reminder email."""
    import httpx
    if not settings.RESEND_API_KEY:
        return

    async with httpx.AsyncClient(timeout=15.0) as client:
        await client.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": f"{settings.RESEND_FROM_NAME} <{settings.RESEND_FROM_EMAIL}>",
                "to": [user.email],
                "subject": "Din provperiod går snart ut — Qvicko",
                "html": f"""
                <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
                    <h2>Hej {user.full_name},</h2>
                    <p>Din kostnadsfria provperiod på Qvicko går ut om 3 dagar.</p>
                    <p>Därefter debiteras 199 kr/månad automatiskt med det betalkort du har registrerat.</p>
                    <p>Om du inte vill fortsätta kan du avsluta prenumerationen under <strong>Betalning</strong> i din dashboard.</p>
                    <p><a href="{settings.FRONTEND_URL}/dashboard/billing" style="background: #4F46E5; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; display: inline-block;">Hantera abonnemang</a></p>
                    <p>Med vänlig hälsning,<br>Qvicko-teamet</p>
                </div>
                """,
            },
        )
