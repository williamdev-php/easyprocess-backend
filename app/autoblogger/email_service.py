"""
AutoBlogger email service.

Convenience functions that build an email from a template and send it
via the shared transactional email service (Resend).
Uses AUTOBLOGGER_MAIL_FROM_EMAIL / AUTOBLOGGER_MAIL_FROM_NAME from config.
"""

from __future__ import annotations

import logging
from datetime import date

from app.config import settings
from app.email.i18n import DEFAULT_LOCALE
from app.email.service import send_transactional_email

from app.autoblogger.email_templates import (
    build_credits_exhausted_email,
    build_credits_low_email,
    build_password_reset_email,
    build_payment_confirmation_email,
    build_payment_failed_email,
    build_plan_change_email,
    build_post_failed_email,
    build_post_generated_email,
    build_post_review_email,
    build_trial_ending_email,
    build_verification_email,
    build_weekly_summary_email,
    build_welcome_email,
)

logger = logging.getLogger(__name__)


def _from_name() -> str:
    return settings.AUTOBLOGGER_MAIL_FROM_NAME


def _from_email() -> str:
    return settings.AUTOBLOGGER_MAIL_FROM_EMAIL


def _frontend_url(path: str = "") -> str:
    """Build an AutoBlogger frontend URL."""
    base = settings.AUTOBLOGGER_FRONTEND_URL.rstrip("/")
    if path:
        return f"{base}/{path.lstrip('/')}"
    return base


async def _send(to: str, subject: str, html: str, text: str) -> str:
    """Send via the shared Resend service with AutoBlogger sender identity."""
    return await send_transactional_email(
        to=to,
        subject=subject,
        html=html,
        text=text,
        from_name=_from_name(),
        from_email=_from_email(),
    )


# ------------------------------------------------------------------
# 1. Post generated
# ------------------------------------------------------------------

async def send_post_generated_notification(
    user_email: str,
    post_title: str,
    post_id: str,
    locale: str = DEFAULT_LOCALE,
) -> str:
    post_url = _frontend_url(f"/dashboard/posts/{post_id}")
    subject, html, text = build_post_generated_email(post_title, post_url, locale)
    return await _send(user_email, subject, html, text)


# ------------------------------------------------------------------
# 2. Post generation failed
# ------------------------------------------------------------------

async def send_post_failed_notification(
    user_email: str,
    post_title: str,
    error_msg: str,
    post_id: str,
    locale: str = DEFAULT_LOCALE,
) -> str:
    retry_url = _frontend_url(f"/dashboard/posts/{post_id}")
    subject, html, text = build_post_failed_email(
        post_title, error_msg, retry_url, locale,
    )
    return await _send(user_email, subject, html, text)


# ------------------------------------------------------------------
# 3. Post awaiting review
# ------------------------------------------------------------------

async def send_post_review_notification(
    user_email: str,
    post_title: str,
    post_id: str,
    locale: str = DEFAULT_LOCALE,
) -> str:
    approve_url = _frontend_url(f"/dashboard/posts/{post_id}?action=approve")
    decline_url = _frontend_url(f"/dashboard/posts/{post_id}?action=decline")
    subject, html, text = build_post_review_email(
        post_title, approve_url, decline_url, locale,
    )
    return await _send(user_email, subject, html, text)


# ------------------------------------------------------------------
# 4. Weekly summary
# ------------------------------------------------------------------

async def send_weekly_summary(
    user_email: str,
    stats_dict: dict,
    locale: str = DEFAULT_LOCALE,
) -> str:
    """
    Send a weekly summary email.

    ``stats_dict`` should contain:
      - posts_generated (int)
      - posts_published (int)
      - credits_used (int)
      - credits_remaining (int)
    """
    subject, html, text = build_weekly_summary_email(
        posts_generated=stats_dict.get("posts_generated", 0),
        posts_published=stats_dict.get("posts_published", 0),
        credits_used=stats_dict.get("credits_used", 0),
        credits_remaining=stats_dict.get("credits_remaining", 0),
        locale=locale,
    )

    # Replace dashboard_url placeholder
    dashboard_url = _frontend_url("/dashboard")
    html = html.replace("{{dashboard_url}}", dashboard_url)
    text = text.replace("{{dashboard_url}}", dashboard_url)

    # Replace unsubscribe_url placeholder
    unsubscribe_url = _frontend_url("/dashboard/settings/notifications")
    html = html.replace("{{unsubscribe_url}}", unsubscribe_url)
    text = text.replace("{{unsubscribe_url}}", unsubscribe_url)

    return await _send(user_email, subject, html, text)


# ------------------------------------------------------------------
# 5. Credits running low
# ------------------------------------------------------------------

async def send_credits_low_warning(
    user_email: str,
    credits_remaining: int,
    total: int,
    locale: str = DEFAULT_LOCALE,
) -> str:
    subject, html, text = build_credits_low_email(
        credits_remaining, total, locale,
    )

    # Replace credits_url placeholder
    credits_url = _frontend_url("/dashboard/billing")
    html = html.replace("{{credits_url}}", credits_url)
    text = text.replace("{{credits_url}}", credits_url)

    return await _send(user_email, subject, html, text)


# ------------------------------------------------------------------
# 6. Credits exhausted
# ------------------------------------------------------------------

async def send_credits_exhausted_warning(
    user_email: str,
    locale: str = DEFAULT_LOCALE,
) -> str:
    upgrade_url = _frontend_url("/dashboard/billing")
    subject, html, text = build_credits_exhausted_email(upgrade_url, locale)
    return await _send(user_email, subject, html, text)


# ------------------------------------------------------------------
# 7. Trial ending reminder
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
# 9. Welcome email
# ------------------------------------------------------------------

async def send_welcome(
    user_email: str,
    user_name: str,
    locale: str = DEFAULT_LOCALE,
) -> str:
    getting_started_url = _frontend_url("/dashboard/sources")
    subject, html, text = build_welcome_email(
        user_name, getting_started_url, locale,
    )
    return await _send(user_email, subject, html, text)


# ------------------------------------------------------------------
# 10. Email verification
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
# 11. Password reset
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
# 12. Payment confirmation
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
# 13. Plan change confirmation
# ------------------------------------------------------------------

async def send_plan_change_confirmation(
    user_email: str,
    old_plan: str,
    new_plan: str,
    locale: str = DEFAULT_LOCALE,
) -> str:
    dashboard_url = _frontend_url("/dashboard/billing")
    subject, html, text = build_plan_change_email(
        old_plan, new_plan, dashboard_url, locale,
    )
    return await _send(user_email, subject, html, text)
