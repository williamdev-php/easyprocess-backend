"""
Stripe Connect REST endpoints.
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.database import get_db
from app.config import settings

router = APIRouter(prefix="/api/payments", tags=["payments"])

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class OnboardingResponse(BaseModel):
    """Response for Connect onboarding initiation."""
    url: str
    account_id: str


class ConnectStatusResponse(BaseModel):
    """Response for Connect account status check."""
    connected: bool
    account_id: str | None = None
    onboarding_status: str | None = None
    charges_enabled: bool | None = None
    payouts_enabled: bool | None = None
    details_submitted: bool | None = None


class RefreshLinkResponse(BaseModel):
    """Response for refreshing an onboarding link."""
    url: str


class WebhookResponse(BaseModel):
    """Response for webhook acknowledgement."""
    received: bool = True


@router.post("/connect/onboard", response_model=OnboardingResponse)
async def start_connect_onboarding(
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OnboardingResponse:
    """Start Stripe Connect onboarding for a site."""
    from app.payments.models import ConnectedAccount
    from app.payments.service import create_connect_account, create_account_link
    from app.sites.models import GeneratedSite
    import uuid

    site_id = body.get("site_id")
    if not site_id:
        raise HTTPException(status_code=400, detail="site_id is required")

    # Verify site ownership
    result = await db.execute(
        select(GeneratedSite).where(GeneratedSite.id == site_id)
    )
    site = result.scalar_one_or_none()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    if not user.is_superuser and site.claimed_by != str(user.id):
        raise HTTPException(status_code=403, detail="You do not own this site")

    # Check if already connected
    existing = await db.execute(
        select(ConnectedAccount).where(ConnectedAccount.site_id == site_id)
    )
    account = existing.scalar_one_or_none()

    if account and account.onboarding_status == "complete":
        raise HTTPException(status_code=400, detail="Site already has a connected Stripe account")

    refresh_url = f"{settings.FRONTEND_URL}/dashboard/sites/{site_id}/apps/bookings/payment-methods?refresh=true"
    return_url = f"{settings.FRONTEND_URL}/dashboard/sites/{site_id}/apps/bookings/payment-methods?onboarding=complete"

    if account:
        # Re-generate onboarding link for existing incomplete account
        link_url = await create_account_link(
            account.stripe_account_id,
            refresh_url=refresh_url,
            return_url=return_url,
        )
        return OnboardingResponse(url=link_url, account_id=account.stripe_account_id)

    # Create new Connect account
    result = await create_connect_account(
        site_id=site_id,
        user_id=str(user.id),
        email=user.email,
    )

    # Save to DB
    from datetime import datetime, timezone
    account = ConnectedAccount(
        id=str(uuid.uuid4()),
        site_id=site_id,
        user_id=str(user.id),
        stripe_account_id=result["account_id"],
        onboarding_status="pending",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(account)
    await db.commit()

    # Generate onboarding link
    link_url = await create_account_link(
        result["account_id"],
        refresh_url=refresh_url,
        return_url=return_url,
    )

    return OnboardingResponse(url=link_url, account_id=result["account_id"])


@router.get("/connect/status/{site_id}", response_model=ConnectStatusResponse)
async def get_connect_status(
    site_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConnectStatusResponse:
    """Get Stripe Connect account status for a site."""
    from app.payments.models import ConnectedAccount
    from app.payments.service import get_account_status
    from app.sites.models import GeneratedSite

    # Verify ownership
    result = await db.execute(
        select(GeneratedSite).where(GeneratedSite.id == site_id)
    )
    site = result.scalar_one_or_none()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    if not user.is_superuser and site.claimed_by != str(user.id):
        raise HTTPException(status_code=403, detail="You do not own this site")

    account_result = await db.execute(
        select(ConnectedAccount).where(ConnectedAccount.site_id == site_id)
    )
    account = account_result.scalar_one_or_none()

    if not account:
        return ConnectStatusResponse(connected=False)

    # Update status from Stripe
    try:
        status = await get_account_status(account.stripe_account_id)
        account.charges_enabled = status["charges_enabled"]
        account.payouts_enabled = status["payouts_enabled"]
        account.details_submitted = status["details_submitted"]
        if status["details_submitted"] and status["charges_enabled"]:
            account.onboarding_status = "complete"
        from datetime import datetime, timezone
        account.updated_at = datetime.now(timezone.utc)
        await db.commit()
    except Exception:
        logger.exception("Failed to fetch Stripe account status")

    return ConnectStatusResponse(
        connected=True,
        account_id=account.stripe_account_id,
        onboarding_status=account.onboarding_status,
        charges_enabled=account.charges_enabled,
        payouts_enabled=account.payouts_enabled,
        details_submitted=account.details_submitted,
    )


@router.post("/connect/refresh-link", response_model=RefreshLinkResponse)
async def refresh_onboarding_link(
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RefreshLinkResponse:
    """Generate a new onboarding link for an incomplete Connect account."""
    from app.payments.models import ConnectedAccount
    from app.payments.service import create_account_link
    from app.sites.models import GeneratedSite

    site_id = body.get("site_id")
    if not site_id:
        raise HTTPException(status_code=400, detail="site_id is required")

    # Verify ownership
    result = await db.execute(
        select(GeneratedSite).where(GeneratedSite.id == site_id)
    )
    site = result.scalar_one_or_none()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    if not user.is_superuser and site.claimed_by != str(user.id):
        raise HTTPException(status_code=403, detail="You do not own this site")

    account_result = await db.execute(
        select(ConnectedAccount).where(ConnectedAccount.site_id == site_id)
    )
    account = account_result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="No Connect account found. Start onboarding first.")

    refresh_url = f"{settings.FRONTEND_URL}/dashboard/sites/{site_id}/apps/bookings/payment-methods?refresh=true"
    return_url = f"{settings.FRONTEND_URL}/dashboard/sites/{site_id}/apps/bookings/payment-methods?onboarding=complete"

    link_url = await create_account_link(
        account.stripe_account_id,
        refresh_url=refresh_url,
        return_url=return_url,
    )
    return RefreshLinkResponse(url=link_url)


@router.post("/webhook/connect", response_model=WebhookResponse)
async def handle_connect_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> WebhookResponse:
    """Handle Stripe Connect webhook events."""
    import stripe
    from app.payments.models import ConnectedAccount
    from datetime import datetime, timezone

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    if not settings.STRIPE_CONNECT_WEBHOOK_SECRET:
        logger.warning("STRIPE_CONNECT_WEBHOOK_SECRET not set, skipping webhook verification")
        raise HTTPException(status_code=500, detail="Webhook secret not configured")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_CONNECT_WEBHOOK_SECRET
        )
    except (ValueError, stripe.error.SignatureVerificationError) as e:
        logger.warning("Invalid webhook signature: %s", e)
        raise HTTPException(status_code=400, detail="Invalid signature")

    if event.type == "account.updated":
        account_data = event.data.object
        stripe_account_id = account_data.get("id")

        result = await db.execute(
            select(ConnectedAccount).where(
                ConnectedAccount.stripe_account_id == stripe_account_id
            )
        )
        account = result.scalar_one_or_none()
        if account:
            account.charges_enabled = account_data.get("charges_enabled", False)
            account.payouts_enabled = account_data.get("payouts_enabled", False)
            account.details_submitted = account_data.get("details_submitted", False)
            if account.details_submitted and account.charges_enabled:
                account.onboarding_status = "complete"
            elif not account.details_submitted:
                account.onboarding_status = "pending"
            else:
                account.onboarding_status = "restricted"
            account.updated_at = datetime.now(timezone.utc)
            await db.commit()
            logger.info("Updated Connect account %s: charges=%s payouts=%s",
                       stripe_account_id, account.charges_enabled, account.payouts_enabled)

    elif event.type in ("payment_intent.succeeded", "payment_intent.payment_failed"):
        # Handle payment completion
        pi = event.data.object
        pi_id = pi.get("id")
        pi_status = "succeeded" if event.type == "payment_intent.succeeded" else "failed"

        from app.apps.models import Booking, BookingPaymentStatus
        from app.payments.models import PlatformPayment

        # Update booking payment status
        booking_result = await db.execute(
            select(Booking).where(Booking.stripe_payment_intent_id == pi_id)
        )
        booking = booking_result.scalar_one_or_none()
        if booking:
            booking.payment_status = BookingPaymentStatus.PAID if pi_status == "succeeded" else BookingPaymentStatus.FAILED
            from datetime import datetime, timezone
            booking.updated_at = datetime.now(timezone.utc)

        # Update platform payment record
        pp_result = await db.execute(
            select(PlatformPayment).where(PlatformPayment.stripe_payment_intent_id == pi_id)
        )
        pp = pp_result.scalar_one_or_none()
        if pp:
            pp.status = pi_status
            if pi_status == "succeeded":
                pp.stripe_charge_id = pi.get("latest_charge")

        await db.commit()
        logger.info("Payment %s for PI %s", pi_status, pi_id)

        # Send payment email to customer
        if booking:
            try:
                from app.email.service import send_transactional_email
                from app.email.booking_templates import (
                    build_booking_payment_received_email,
                    build_booking_payment_failed_email,
                )
                from app.sites.models import GeneratedSite

                site_result = await db.execute(
                    select(GeneratedSite).where(GeneratedSite.id == booking.site_id)
                )
                site = site_result.scalar_one_or_none()
                site_name = "Hemsida"
                if site and site.site_data:
                    site_name = site.site_data.get("business", {}).get("name") or site.site_data.get("meta", {}).get("title") or site_name

                booking_date_str = booking.booking_date.strftime("%Y-%m-%d %H:%M") if booking.booking_date else "N/A"

                if pi_status == "succeeded":
                    subj, html, text = build_booking_payment_received_email(
                        customer_name=booking.customer_name,
                        site_name=site_name,
                        service_name=booking.service_name,
                        booking_date=booking_date_str,
                        amount=float(booking.amount),
                        currency=booking.currency,
                    )
                else:
                    subj, html, text = build_booking_payment_failed_email(
                        customer_name=booking.customer_name,
                        site_name=site_name,
                        service_name=booking.service_name,
                        booking_date=booking_date_str,
                        amount=float(booking.amount),
                        currency=booking.currency,
                    )

                await send_transactional_email(
                    to=booking.customer_email,
                    subject=subj,
                    html=html,
                    text=text,
                    from_name="Bookings by Qvicko",
                )
            except Exception:
                logger.exception("Failed to send payment status email to customer")

    elif event.type in ("payout.paid", "payout.failed"):
        # Handle payout events — notify site owner
        payout = event.data.object
        stripe_account_id = event.account  # Connected account ID

        try:
            from app.email.service import send_transactional_email
            from app.email.payment_templates import (
                build_payout_completed_email,
                build_payout_initiated_email,
                build_payout_failed_email,
            )
            from app.payments.models import ConnectedAccount
            from app.sites.models import GeneratedSite

            account_result = await db.execute(
                select(ConnectedAccount).where(
                    ConnectedAccount.stripe_account_id == stripe_account_id
                )
            )
            account = account_result.scalar_one_or_none()
            if account:
                site_result = await db.execute(
                    select(GeneratedSite).where(GeneratedSite.id == account.site_id)
                )
                site = site_result.scalar_one_or_none()
                site_name = "Hemsida"
                if site and site.site_data:
                    site_name = site.site_data.get("business", {}).get("name") or site.site_data.get("meta", {}).get("title") or site_name

                owner_result = await db.execute(
                    select(User).where(User.id == account.user_id)
                )
                owner = owner_result.scalar_one_or_none()

                if owner and owner.email:
                    payout_amount = payout.get("amount", 0) / 100  # Convert from öre/cents
                    payout_currency = (payout.get("currency") or "SEK").upper()
                    dashboard_url = f"{settings.FRONTEND_URL}/dashboard/payments"

                    if event.type == "payout.paid":
                        subj, html, text = build_payout_completed_email(
                            owner_name=owner.full_name or owner.email,
                            site_name=site_name,
                            amount=payout_amount,
                            currency=payout_currency,
                            dashboard_url=dashboard_url,
                        )
                    else:  # payout.failed
                        failure_reason = payout.get("failure_message")
                        subj, html, text = build_payout_failed_email(
                            owner_name=owner.full_name or owner.email,
                            site_name=site_name,
                            amount=payout_amount,
                            currency=payout_currency,
                            failure_reason=failure_reason,
                            dashboard_url=dashboard_url,
                        )

                    await send_transactional_email(
                        to=owner.email,
                        subject=subj,
                        html=html,
                        text=text,
                    )
        except Exception:
            logger.exception("Failed to send payout email")

    elif event.type == "payout.created":
        # Payout initiated — notify site owner
        payout = event.data.object
        stripe_account_id = event.account

        try:
            from app.email.service import send_transactional_email
            from app.email.payment_templates import build_payout_initiated_email
            from app.payments.models import ConnectedAccount
            from app.sites.models import GeneratedSite

            account_result = await db.execute(
                select(ConnectedAccount).where(
                    ConnectedAccount.stripe_account_id == stripe_account_id
                )
            )
            account = account_result.scalar_one_or_none()
            if account:
                site_result = await db.execute(
                    select(GeneratedSite).where(GeneratedSite.id == account.site_id)
                )
                site = site_result.scalar_one_or_none()
                site_name = "Hemsida"
                if site and site.site_data:
                    site_name = site.site_data.get("business", {}).get("name") or site.site_data.get("meta", {}).get("title") or site_name

                owner_result = await db.execute(
                    select(User).where(User.id == account.user_id)
                )
                owner = owner_result.scalar_one_or_none()

                if owner and owner.email:
                    payout_amount = payout.get("amount", 0) / 100
                    payout_currency = (payout.get("currency") or "SEK").upper()
                    arrival_date = payout.get("arrival_date")
                    estimated_arrival = "N/A"
                    if arrival_date:
                        from datetime import datetime as _dt
                        estimated_arrival = _dt.fromtimestamp(arrival_date).strftime("%Y-%m-%d")
                    dashboard_url = f"{settings.FRONTEND_URL}/dashboard/payments"

                    subj, html, text = build_payout_initiated_email(
                        owner_name=owner.full_name or owner.email,
                        site_name=site_name,
                        amount=payout_amount,
                        currency=payout_currency,
                        estimated_arrival=estimated_arrival,
                        dashboard_url=dashboard_url,
                    )
                    await send_transactional_email(
                        to=owner.email,
                        subject=subj,
                        html=html,
                        text=text,
                    )
        except Exception:
            logger.exception("Failed to send payout initiated email")

    elif event.type in ("charge.dispute.created", "charge.dispute.updated"):
        # Chargeback / dispute — notify site owner and handle negative balance
        dispute = event.data.object
        stripe_account_id = event.account

        try:
            from app.email.service import send_transactional_email
            from app.email.payment_templates import (
                build_chargeback_received_email,
                build_negative_balance_warning_email,
            )
            from app.payments.models import ConnectedAccount
            from app.payments.service import get_account_balance
            from app.sites.models import GeneratedSite
            from app.apps.models import Booking

            account_result = await db.execute(
                select(ConnectedAccount).where(
                    ConnectedAccount.stripe_account_id == stripe_account_id
                )
            )
            account = account_result.scalar_one_or_none()
            if account and event.type == "charge.dispute.created":
                site_result = await db.execute(
                    select(GeneratedSite).where(GeneratedSite.id == account.site_id)
                )
                site = site_result.scalar_one_or_none()
                site_name = "Hemsida"
                if site and site.site_data:
                    site_name = site.site_data.get("business", {}).get("name") or site.site_data.get("meta", {}).get("title") or site_name

                owner_result = await db.execute(
                    select(User).where(User.id == account.user_id)
                )
                owner = owner_result.scalar_one_or_none()

                if owner and owner.email:
                    dispute_amount = dispute.get("amount", 0) / 100
                    dispute_currency = (dispute.get("currency") or "SEK").upper()
                    dispute_reason = dispute.get("reason")
                    evidence_due = dispute.get("evidence_details", {}).get("due_by")
                    respond_by = None
                    if evidence_due:
                        from datetime import datetime as _dt
                        respond_by = _dt.fromtimestamp(evidence_due).strftime("%Y-%m-%d %H:%M")

                    # Try to get customer name from related booking
                    customer_name = "Okänd kund"
                    charge_id = dispute.get("charge")
                    if charge_id:
                        booking_result = await db.execute(
                            select(Booking).where(Booking.stripe_payment_intent_id == dispute.get("payment_intent"))
                        )
                        related_booking = booking_result.scalar_one_or_none()
                        if related_booking:
                            customer_name = related_booking.customer_name

                    dashboard_url = f"{settings.FRONTEND_URL}/dashboard/payments"

                    subj, html, text = build_chargeback_received_email(
                        owner_name=owner.full_name or owner.email,
                        site_name=site_name,
                        amount=dispute_amount,
                        currency=dispute_currency,
                        customer_name=customer_name,
                        reason=dispute_reason,
                        respond_by=respond_by,
                        dashboard_url=dashboard_url,
                    )
                    await send_transactional_email(
                        to=owner.email,
                        subject=subj,
                        html=html,
                        text=text,
                    )

                    # Check if balance is negative and send warning
                    try:
                        balance_data = await get_account_balance(stripe_account_id)
                        available_amount = balance_data.get("available_amount", 0)
                        if available_amount < 0:
                            neg_amount = available_amount / 100
                            neg_currency = (balance_data.get("currency") or "SEK").upper()
                            neg_subj, neg_html, neg_text = build_negative_balance_warning_email(
                                owner_name=owner.full_name or owner.email,
                                site_name=site_name,
                                balance=neg_amount,
                                currency=neg_currency,
                                dashboard_url=dashboard_url,
                            )
                            await send_transactional_email(
                                to=owner.email,
                                subject=neg_subj,
                                html=neg_html,
                                text=neg_text,
                            )
                    except Exception:
                        logger.exception("Failed to check balance after dispute")

        except Exception:
            logger.exception("Failed to send chargeback email")

    return WebhookResponse(received=True)
