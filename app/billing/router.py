"""
Billing REST endpoints and Stripe webhook handler.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status
import re
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.billing.service import (
    cancel_subscription,
    create_setup_intent,
    create_subscription_after_setup,
    get_active_subscription,
    get_or_create_stripe_customer,
    handle_invoice_failed,
    handle_invoice_paid,
    handle_subscription_created,
    handle_subscription_deleted,
    handle_subscription_updated,
    handle_trial_will_end,
    list_payment_methods,
    reactivate_subscription,
)
from app.cache import cache
from app.config import settings
from app.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/billing", tags=["billing"])
webhook_router = APIRouter(tags=["stripe-webhooks"])


# ---------------------------------------------------------------------------
# Setup Intent — collect card without charging
# ---------------------------------------------------------------------------

@router.post("/setup-intent")
async def create_setup_intent_endpoint(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a Stripe SetupIntent for collecting card details."""
    result = await create_setup_intent(db, user)
    return result


# ---------------------------------------------------------------------------
# Subscribe — after card collected via SetupIntent
# ---------------------------------------------------------------------------

class SubscribeRequest(BaseModel):
    plan: str = "basic"  # "basic" or "pro"


@router.post("/subscribe")
async def subscribe_endpoint(
    body: SubscribeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a subscription using the customer's default payment method.
    Call this after a SetupIntent has been confirmed on the frontend.
    """
    if body.plan not in ("basic", "pro"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ogiltig plan. Välj 'basic' eller 'pro'.",
        )

    # Check if user already has an active subscription
    existing = await get_active_subscription(db, user.id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Du har redan en aktiv prenumeration.",
        )

    sub = await create_subscription_after_setup(db, user, plan=body.plan, with_trial=True)
    await cache.delete(f"subscription:{user.id}")
    await cache.delete(f"sub_active:{user.id}")
    return {
        "subscription_id": sub.id,
        "stripe_subscription_id": sub.stripe_subscription_id,
        "status": sub.status.value,
        "plan": body.plan,
        "trial_end": sub.trial_end.isoformat() if sub.trial_end else None,
    }


# ---------------------------------------------------------------------------
# Cancel / Reactivate
# ---------------------------------------------------------------------------

@router.post("/cancel")
async def cancel_subscription_endpoint(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    sub = await cancel_subscription(db, user)
    if not sub:
        raise HTTPException(status_code=404, detail="Ingen aktiv prenumeration hittades.")
    await cache.delete(f"subscription:{user.id}")
    await cache.delete(f"sub_active:{user.id}")
    return {"status": sub.status.value, "cancel_at_period_end": sub.cancel_at_period_end}


@router.post("/reactivate")
async def reactivate_subscription_endpoint(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    sub = await reactivate_subscription(db, user)
    if not sub:
        raise HTTPException(status_code=404, detail="Ingen prenumeration att återaktivera.")
    await cache.delete(f"subscription:{user.id}")
    await cache.delete(f"sub_active:{user.id}")
    return {"status": sub.status.value, "cancel_at_period_end": sub.cancel_at_period_end}


# ---------------------------------------------------------------------------
# Payment Methods
# ---------------------------------------------------------------------------

@router.get("/payment-methods")
async def get_payment_methods(
    user: User = Depends(get_current_user),
):
    methods = await list_payment_methods(user)
    return {"payment_methods": methods}


# ---------------------------------------------------------------------------
# Domain Purchase
# ---------------------------------------------------------------------------

@router.get("/domain/check")
async def check_domain(
    domain: str,
    user: User = Depends(get_current_user),
):
    """Check domain availability and price (with markup)."""
    from app.sites.vercel import check_domain_availability

    result = await check_domain_availability(domain)
    if not result:
        raise HTTPException(status_code=502, detail="Kunde inte kontrollera domäntillgänglighet")

    return result


_DOMAIN_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")


class DomainPurchaseRequest(BaseModel):
    domain: str
    site_id: str | None = None

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, v: str) -> str:
        d = v.strip().lower()
        if not _DOMAIN_RE.match(d):
            raise ValueError("Invalid domain format")
        return d


@router.post("/domain/purchase")
async def purchase_domain_endpoint(
    body: DomainPurchaseRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a Stripe PaymentIntent for domain purchase.

    Returns client_secret for Stripe Elements confirmation on frontend.
    After payment succeeds, the webhook handler completes the Vercel purchase.
    """
    from app.sites.vercel import check_domain_availability
    from app.sites.models import DomainPurchase, DomainPurchaseStatus

    domain = body.domain  # Already validated & lowered by Pydantic

    # Check availability and get price
    avail = await check_domain_availability(domain)
    if not avail or not avail.get("available"):
        raise HTTPException(status_code=400, detail=f"Domänen {domain} är inte tillgänglig")

    price_sek_ore = avail["price_sek"]
    price_usd = avail["price_usd"]

    # Check if already purchased or pending
    existing = await db.execute(
        select(DomainPurchase).where(
            DomainPurchase.domain == domain,
            DomainPurchase.status.in_([
                DomainPurchaseStatus.PURCHASED,
                DomainPurchaseStatus.PENDING_PAYMENT,
            ]),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Domänen {domain} är redan registrerad eller har en pågående betalning")

    # Ensure Stripe customer
    customer_id = await get_or_create_stripe_customer(db, user)

    # Create PaymentIntent
    payment_intent = stripe.PaymentIntent.create(
        amount=price_sek_ore,
        currency="sek",
        customer=customer_id,
        metadata={
            "qvicko_user_id": user.id,
            "qvicko_domain": domain,
            "qvicko_site_id": body.site_id or "",
            "qvicko_type": "domain_purchase",
            "price_usd": str(price_usd),
        },
        description=f"Domänregistrering: {domain}",
        automatic_payment_methods={"enabled": True},
    )

    # Save pending purchase
    purchase = DomainPurchase(
        user_id=user.id,
        domain=domain,
        price_sek=price_sek_ore,
        price_usd=price_usd,
        period_years=avail.get("period", 1),
        status=DomainPurchaseStatus.PENDING_PAYMENT,
        stripe_payment_intent_id=payment_intent.id,
    )
    db.add(purchase)
    await db.commit()

    return {
        "client_secret": payment_intent.client_secret,
        "payment_intent_id": payment_intent.id,
        "domain": domain,
        "price_sek": price_sek_ore,
        "price_sek_display": avail["price_sek_display"],
    }


# ---------------------------------------------------------------------------
# Stripe Webhook
# ---------------------------------------------------------------------------

@webhook_router.post("/api/webhooks/stripe")
async def stripe_webhook(request: Request):
    """
    Stripe webhook endpoint with signature verification.
    Handles subscription lifecycle and payment events.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not sig_header:
        raise HTTPException(status_code=400, detail="Missing Stripe signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    logger.info("Stripe webhook: %s (id=%s)", event.type, event.id)

    from app.database import get_db_session

    async with get_db_session() as db:
        try:
            # Check if this is an AutoBlogger event by inspecting metadata
            _obj = event.data.object
            _is_autoblogger = _check_autoblogger_event(_obj, event.type)

            if _is_autoblogger and event.type in (
                "customer.subscription.created",
                "customer.subscription.updated",
            ):
                await _handle_autoblogger_subscription_update(db, _obj)
            elif _is_autoblogger and event.type == "customer.subscription.deleted":
                await _handle_autoblogger_subscription_deleted(db, _obj)
            elif _is_autoblogger and event.type == "invoice.payment_succeeded":
                await _handle_autoblogger_invoice_paid(db, _obj)
            elif event.type == "customer.subscription.created":
                await handle_subscription_created(db, _obj)
            elif event.type == "customer.subscription.updated":
                await handle_subscription_updated(db, _obj)
            elif event.type == "customer.subscription.deleted":
                await handle_subscription_deleted(db, _obj)
            elif event.type == "invoice.payment_succeeded":
                await handle_invoice_paid(db, _obj)
            elif event.type == "invoice.payment_failed":
                await handle_invoice_failed(db, _obj)
            elif event.type == "customer.subscription.trial_will_end":
                await handle_trial_will_end(db, _obj)
            elif event.type == "payment_intent.succeeded":
                await _handle_domain_purchase_success(db, _obj)
            elif event.type == "payment_intent.payment_failed":
                await _handle_domain_purchase_failure(db, _obj)
            else:
                logger.debug("Unhandled Stripe event type: %s", event.type)

            await db.commit()

            # Invalidate subscription caches on any subscription event
            if event.type.startswith("customer.subscription."):
                sub_obj = event.data.object
                customer_id = sub_obj.get("customer") if isinstance(sub_obj, dict) else getattr(sub_obj, "customer", None)
                if customer_id:
                    # Find user by stripe_customer_id and invalidate
                    from app.billing.models import Subscription as SubModel
                    result = await db.execute(
                        select(SubModel.user_id).where(
                            SubModel.stripe_customer_id == customer_id
                        ).limit(1)
                    )
                    user_id = result.scalar_one_or_none()
                    if user_id:
                        await cache.delete(f"subscription:{user_id}")
                        await cache.delete(f"sub_active:{user_id}")

        except Exception:
            await db.rollback()
            logger.exception("Error processing Stripe webhook %s (id=%s)", event.type, event.id)
            # Return 500 so Stripe retries, but never expose internal details
            raise HTTPException(status_code=500, detail="Internal error")

    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Domain purchase webhook handlers
# ---------------------------------------------------------------------------

async def _handle_domain_purchase_success(db: AsyncSession, payment_intent) -> None:
    """Complete domain purchase after successful payment."""
    metadata = payment_intent.get("metadata", {})
    if metadata.get("qvicko_type") != "domain_purchase":
        return  # Not a domain purchase payment

    domain = metadata.get("qvicko_domain")
    user_id = metadata.get("qvicko_user_id")
    site_id = metadata.get("qvicko_site_id") or None
    pi_id = payment_intent.get("id")

    if not domain or not user_id:
        logger.warning("Domain purchase payment missing metadata: %s", pi_id)
        return

    from app.sites.models import (
        CustomDomain, DomainPurchase, DomainPurchaseStatus, DomainStatus,
        GeneratedSite,
    )
    from app.sites.vercel import purchase_domain as vercel_purchase, add_domain as vercel_add
    from app.billing.models import Payment, PaymentStatus

    # Find the pending purchase (locked to prevent race condition with concurrent webhooks)
    result = await db.execute(
        select(DomainPurchase).where(
            DomainPurchase.stripe_payment_intent_id == pi_id
        ).with_for_update()
    )
    purchase = result.scalar_one_or_none()
    if not purchase:
        logger.warning("No pending DomainPurchase found for PI %s", pi_id)
        return

    # Buy domain from Vercel
    vercel_result = await vercel_purchase(domain)
    if not vercel_result:
        purchase.status = DomainPurchaseStatus.FAILED
        await db.flush()
        logger.error("Vercel domain purchase failed for %s — payment was taken, needs manual refund", domain)
        return

    # Mark purchase as completed
    now = datetime.now(timezone.utc)
    purchase.status = DomainPurchaseStatus.PURCHASED
    purchase.purchased_at = now
    purchase.vercel_domain_id = vercel_result.get("uid") or vercel_result.get("id")

    # Set expiry (Vercel domains are typically 1 year)
    from dateutil.relativedelta import relativedelta
    purchase.expires_at = now + relativedelta(years=purchase.period_years)

    # Add domain to Vercel project for routing
    await vercel_add(domain)

    # Create CustomDomain record (auto-verified since we own it)
    existing_cd = await db.execute(
        select(CustomDomain).where(CustomDomain.domain == domain)
    )
    cd = existing_cd.scalar_one_or_none()
    if not cd:
        cd = CustomDomain(
            user_id=user_id,
            domain=domain,
            site_id=site_id,
            status=DomainStatus.ACTIVE,
            verified_at=now,
        )
        db.add(cd)
    else:
        cd.status = DomainStatus.ACTIVE
        cd.verified_at = now
        if site_id:
            cd.site_id = site_id

    # Update site's custom_domain field if site_id provided
    if site_id:
        site_result = await db.execute(
            select(GeneratedSite).where(GeneratedSite.id == site_id)
        )
        site = site_result.scalar_one_or_none()
        if site:
            site.custom_domain = domain

    # Record payment
    payment = Payment(
        user_id=user_id,
        subscription_id=None,
        stripe_payment_intent_id=pi_id,
        amount_sek=purchase.price_sek,
        currency="sek",
        status=PaymentStatus.SUCCEEDED,
    )
    db.add(payment)

    await db.flush()

    # Invalidate site caches after domain assignment
    if site_id:
        await cache.delete(f"site:{site_id}")
        await cache.delete(f"site:data:{site_id}")
        await cache.delete(f"site:meta:{site_id}")
        await cache.delete(f"resolve:dom:{domain}")

    logger.info("Domain purchase completed: %s for user %s", domain, user_id)


async def _handle_domain_purchase_failure(db: AsyncSession, payment_intent) -> None:
    """Mark domain purchase as failed."""
    metadata = payment_intent.get("metadata", {})
    if metadata.get("qvicko_type") != "domain_purchase":
        return

    pi_id = payment_intent.get("id")
    from app.sites.models import DomainPurchase, DomainPurchaseStatus

    result = await db.execute(
        select(DomainPurchase).where(
            DomainPurchase.stripe_payment_intent_id == pi_id
        )
    )
    purchase = result.scalar_one_or_none()
    if purchase:
        purchase.status = DomainPurchaseStatus.FAILED
        await db.flush()
        logger.info("Domain purchase payment failed for %s", purchase.domain)


# ---------------------------------------------------------------------------
# AutoBlogger webhook helpers
# ---------------------------------------------------------------------------

def _check_autoblogger_event(obj, event_type: str) -> bool:
    """Check if a Stripe event object belongs to AutoBlogger via metadata."""
    from app.billing.service import _get_metadata, _get_invoice_subscription_id

    # For subscription events, check metadata directly
    if event_type.startswith("customer.subscription."):
        return bool(_get_metadata(obj, "autoblogger_user_id"))

    # For invoice events, we need to look up the subscription's metadata
    if event_type.startswith("invoice."):
        sub_id = _get_invoice_subscription_id(obj)
        if sub_id:
            try:
                stripe_sub = stripe.Subscription.retrieve(sub_id)
                return bool(_get_metadata(stripe_sub, "autoblogger_user_id"))
            except Exception:
                pass
    return False


async def _handle_autoblogger_subscription_update(
    db: AsyncSession, stripe_sub
) -> None:
    """Handle subscription.created/updated for AutoBlogger."""
    from app.billing.service import _get_metadata, _get_period, _ts_to_dt
    from app.autoblogger.models import AutoBloggerSubscription, CreditBalance

    user_id = _get_metadata(stripe_sub, "autoblogger_user_id")
    plan = _get_metadata(stripe_sub, "autoblogger_plan") or "pro"

    if not user_id:
        logger.warning("AutoBlogger sub event missing user_id metadata: %s", stripe_sub.id)
        return

    stripe_sub_id = stripe_sub.id if hasattr(stripe_sub, "id") else stripe_sub.get("id")
    stripe_status = stripe_sub.status if hasattr(stripe_sub, "status") else stripe_sub.get("status")
    customer_id = stripe_sub.customer if hasattr(stripe_sub, "customer") else stripe_sub.get("customer")
    cancel_at_end = stripe_sub.cancel_at_period_end if hasattr(stripe_sub, "cancel_at_period_end") else stripe_sub.get("cancel_at_period_end", False)
    trial_start_ts = stripe_sub.trial_start if hasattr(stripe_sub, "trial_start") else stripe_sub.get("trial_start")
    trial_end_ts = stripe_sub.trial_end if hasattr(stripe_sub, "trial_end") else stripe_sub.get("trial_end")

    period_start, period_end = _get_period(stripe_sub)

    # Find existing record
    result = await db.execute(
        select(AutoBloggerSubscription).where(
            AutoBloggerSubscription.stripe_subscription_id == stripe_sub_id
        )
    )
    ab_sub = result.scalar_one_or_none()

    if ab_sub:
        ab_sub.status = stripe_status
        ab_sub.plan = plan
        ab_sub.current_period_start = _ts_to_dt(period_start)
        ab_sub.current_period_end = _ts_to_dt(period_end)
        ab_sub.cancel_at_period_end = cancel_at_end
        ab_sub.trial_start = _ts_to_dt(trial_start_ts) if trial_start_ts else None
        ab_sub.trial_end = _ts_to_dt(trial_end_ts) if trial_end_ts else None
    else:
        ab_sub = AutoBloggerSubscription(
            user_id=user_id,
            stripe_subscription_id=stripe_sub_id,
            stripe_customer_id=customer_id,
            plan=plan,
            status=stripe_status,
            current_period_start=_ts_to_dt(period_start),
            current_period_end=_ts_to_dt(period_end),
            cancel_at_period_end=cancel_at_end,
            trial_start=_ts_to_dt(trial_start_ts) if trial_start_ts else None,
            trial_end=_ts_to_dt(trial_end_ts) if trial_end_ts else None,
        )
        db.add(ab_sub)

    # If status becomes active (trial ended or payment succeeded), reset credits
    if stripe_status == "active":
        credits = {"pro": 50, "business": 9999}.get(plan, 5)
        bal_result = await db.execute(
            select(CreditBalance).where(CreditBalance.user_id == user_id)
        )
        balance = bal_result.scalar_one_or_none()
        if balance:
            balance.plan_credits_monthly = credits
            balance.credits_remaining = credits
            balance.last_reset_at = datetime.now(timezone.utc)

    await db.flush()
    logger.info("AutoBlogger subscription %s updated: status=%s plan=%s", stripe_sub_id, stripe_status, plan)


async def _handle_autoblogger_subscription_deleted(
    db: AsyncSession, stripe_sub
) -> None:
    """Handle subscription.deleted for AutoBlogger."""
    from app.autoblogger.models import AutoBloggerSubscription

    stripe_sub_id = stripe_sub.id if hasattr(stripe_sub, "id") else stripe_sub.get("id")

    result = await db.execute(
        select(AutoBloggerSubscription).where(
            AutoBloggerSubscription.stripe_subscription_id == stripe_sub_id
        )
    )
    ab_sub = result.scalar_one_or_none()
    if ab_sub:
        ab_sub.status = "canceled"
        ab_sub.cancel_at_period_end = False
        await db.flush()
        logger.info("AutoBlogger subscription %s canceled", stripe_sub_id)


async def _handle_autoblogger_invoice_paid(
    db: AsyncSession, invoice
) -> None:
    """Handle invoice.payment_succeeded for AutoBlogger — record payment & reset credits."""
    from app.billing.service import (
        _get_invoice_payment_intent_id,
        _get_invoice_subscription_id,
        _get_user_by_customer_id,
        _get_metadata,
    )
    from app.autoblogger.models import (
        AutoBloggerPayment,
        AutoBloggerSubscription,
        CreditBalance,
    )

    customer_id = invoice.customer if hasattr(invoice, "customer") else invoice.get("customer")
    user = await _get_user_by_customer_id(db, customer_id)
    if not user:
        logger.warning("AutoBlogger invoice paid — no user for customer %s", customer_id)
        return

    pi_id = _get_invoice_payment_intent_id(invoice)
    sub_stripe_id = _get_invoice_subscription_id(invoice)

    # Deduplicate
    if pi_id:
        existing = await db.execute(
            select(AutoBloggerPayment).where(AutoBloggerPayment.stripe_payment_intent_id == pi_id)
        )
        if existing.scalar_one_or_none():
            return

    # Find AutoBlogger subscription
    ab_sub = None
    if sub_stripe_id:
        result = await db.execute(
            select(AutoBloggerSubscription).where(
                AutoBloggerSubscription.stripe_subscription_id == sub_stripe_id
            )
        )
        ab_sub = result.scalar_one_or_none()

    amount = invoice.amount_paid if hasattr(invoice, "amount_paid") else invoice.get("amount_paid", 0)
    currency = (invoice.currency if hasattr(invoice, "currency") else invoice.get("currency")) or "sek"
    invoice_url = getattr(invoice, "hosted_invoice_url", None) or (invoice.get("hosted_invoice_url") if isinstance(invoice, dict) else None)
    invoice_id = invoice.id if hasattr(invoice, "id") else invoice.get("id")

    payment = AutoBloggerPayment(
        user_id=user.id,
        subscription_id=ab_sub.id if ab_sub else None,
        stripe_payment_intent_id=pi_id,
        stripe_invoice_id=invoice_id,
        amount=amount,
        currency=currency,
        status="succeeded",
        invoice_url=invoice_url,
    )
    db.add(payment)

    # Reset monthly credits
    if ab_sub:
        plan = ab_sub.plan
        credits = {"pro": 50, "business": 9999}.get(plan, 5)
        bal_result = await db.execute(
            select(CreditBalance).where(CreditBalance.user_id == user.id)
        )
        balance = bal_result.scalar_one_or_none()
        if balance:
            balance.plan_credits_monthly = credits
            balance.credits_remaining = credits
            balance.last_reset_at = datetime.now(timezone.utc)

    await db.flush()
    logger.info("AutoBlogger payment recorded for user %s (invoice %s)", user.id, invoice_id)
