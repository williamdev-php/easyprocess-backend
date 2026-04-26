"""
Feyra email service.

Convenience functions that build an email from a template and send it
via the shared transactional email service (Resend).
Uses FEYRA_MAIL_FROM_EMAIL / FEYRA_MAIL_FROM_NAME from config.
"""

from __future__ import annotations

import logging
from datetime import date

from app.config import settings
from app.email.i18n import DEFAULT_LOCALE
from app.email.service import send_transactional_email

from app.feyra.email_templates import (
    build_campaign_sent_email,
    build_lead_import_complete_email,
    build_password_reset_email,
    build_payment_confirmation_email,
    build_payment_failed_email,
    build_trial_ending_email,
    build_verification_email,
    build_warmup_status_email,
    build_welcome_email,
)

logger = logging.getLogger(__name__)


def _from_name() -> str:
    return settings.FEYRA_MAIL_FROM_NAME


def _from_email() -> str:
    return settings.FEYRA_MAIL_FROM_EMAIL


def _frontend_url(path: str = "") -> str:
    """Build a Feyra frontend URL."""
    base = settings.FEYRA_FRONTEND_URL.rstrip("/")
    if path:
        return f"{base}/{path.lstrip('/')}"
    return base


async def _send(to: str, subject: str, html: str, text: str) -> str:
    """Send via the shared Resend service with Feyra sender identity."""
    return await send_transactional_email(
        to=to,
        subject=subject,
        html=html,
        text=text,
        from_name=_from_name(),
        from_email=_from_email(),
    )


# ------------------------------------------------------------------
# 1. Email verification
# ------------------------------------------------------------------

async def send_verification_email(
    user_email: str,
    verify_url: str,
    user_name: str | None = None,
    locale: str = DEFAULT_LOCALE,
) -> str:
    subject, html, text = build_verification_email(verify_url, user_name, locale)
    return await _send(user_email, subject, html, text)


# ------------------------------------------------------------------
# 2. Password reset
# ------------------------------------------------------------------

async def send_password_reset_email(
    user_email: str,
    reset_url: str,
    user_name: str | None = None,
    locale: str = DEFAULT_LOCALE,
) -> str:
    subject, html, text = build_password_reset_email(reset_url, user_name, locale)
    return await _send(user_email, subject, html, text)


# ------------------------------------------------------------------
# 3. Welcome email
# ------------------------------------------------------------------

async def send_welcome(
    user_email: str,
    user_name: str,
    locale: str = DEFAULT_LOCALE,
) -> str:
    getting_started_url = _frontend_url("/dashboard")
    subject, html, text = build_welcome_email(
        user_name, getting_started_url, locale,
    )
    return await _send(user_email, subject, html, text)


# ------------------------------------------------------------------
# 4. Campaign sent
# ------------------------------------------------------------------

async def send_campaign_sent_notification(
    user_email: str,
    campaign_name: str,
    campaign_id: str,
    recipient_count: int,
    locale: str = DEFAULT_LOCALE,
) -> str:
    campaign_url = _frontend_url(f"/dashboard/campaigns/{campaign_id}")
    subject, html, text = build_campaign_sent_email(
        campaign_name, recipient_count, campaign_url, locale,
    )
    return await _send(user_email, subject, html, text)


# ------------------------------------------------------------------
# 5. Lead import complete
# ------------------------------------------------------------------

async def send_lead_import_complete_notification(
    user_email: str,
    imported_count: int,
    locale: str = DEFAULT_LOCALE,
) -> str:
    leads_url = _frontend_url("/dashboard/leads")
    subject, html, text = build_lead_import_complete_email(
        imported_count, leads_url, locale,
    )
    return await _send(user_email, subject, html, text)


# ------------------------------------------------------------------
# 6. Warmup status update
# ------------------------------------------------------------------

async def send_warmup_status_notification(
    user_email: str,
    email_account: str,
    warmup_status: str,
    locale: str = DEFAULT_LOCALE,
) -> str:
    warmup_url = _frontend_url("/dashboard/warmup")
    subject, html, text = build_warmup_status_email(
        email_account, warmup_status, warmup_url, locale,
    )
    return await _send(user_email, subject, html, text)


# ------------------------------------------------------------------
# 7. Payment confirmation
# ------------------------------------------------------------------

async def send_payment_confirmation(
    user_email: str,
    amount: str,
    next_billing_date: str,
    locale: str = DEFAULT_LOCALE,
) -> str:
    dashboard_url = _frontend_url("/dashboard/billing")
    subject, html, text = build_payment_confirmation_email(
        amount, next_billing_date, dashboard_url, locale,
    )
    return await _send(user_email, subject, html, text)


# ------------------------------------------------------------------
# 8. Payment failed
# ------------------------------------------------------------------

async def send_payment_failed_notice(
    user_email: str,
    invoice_url: str,
    locale: str = DEFAULT_LOCALE,
) -> str:
    subject, html, text = build_payment_failed_email(invoice_url, locale)
    return await _send(user_email, subject, html, text)


# ------------------------------------------------------------------
# 9. Trial ending
# ------------------------------------------------------------------

async def send_trial_ending_reminder(
    user_email: str,
    trial_end: date | str,
    locale: str = DEFAULT_LOCALE,
) -> str:
    trial_end_str = (
        trial_end.isoformat() if isinstance(trial_end, date) else str(trial_end)
    )
    upgrade_url = _frontend_url("/dashboard/billing")
    subject, html, text = build_trial_ending_email(
        trial_end_str, upgrade_url, locale,
    )
    return await _send(user_email, subject, html, text)
