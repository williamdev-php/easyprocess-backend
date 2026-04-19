"""
Background job: daily check of site expiration and grace period enforcement.

Grace period: 14 days after missed payment.
Warning emails: day 1 (payment failed), day 7 (reminder), day 12 (last warning), day 14 (archived).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.models import User
from app.billing.models import Subscription, SubscriptionStatus
from app.config import settings
from app.database import get_db_session
from app.sites.models import GeneratedSite, Lead, SiteStatus

logger = logging.getLogger(__name__)

GRACE_PERIOD_DAYS = 14


async def check_expired_sites() -> None:
    """
    Daily job: check all published sites with expires_at in the past.
    Enforce grace period and send warning emails.
    """
    now = datetime.now(timezone.utc)

    async with get_db_session() as db:
        # Find expired sites with lead and user eager-loaded (avoids N+1)
        result = await db.execute(
            select(GeneratedSite)
            .where(
                GeneratedSite.expires_at.isnot(None),
                GeneratedSite.expires_at < now,
                GeneratedSite.status.in_([SiteStatus.PUBLISHED, SiteStatus.PURCHASED]),
            )
            .options(selectinload(GeneratedSite.lead))
        )
        expired_sites = result.scalars().all()

        # Collect all user IDs to batch-load users and subscriptions
        user_ids = {site.lead.created_by for site in expired_sites if site.lead and site.lead.created_by}

        # Batch load users
        users_by_id: dict[str, User] = {}
        if user_ids:
            user_result = await db.execute(select(User).where(User.id.in_(user_ids)))
            users_by_id = {u.id: u for u in user_result.scalars().all()}

        # Batch load active subscriptions for these users
        active_subs_by_user: dict[str, Subscription] = {}
        if user_ids:
            sub_result = await db.execute(
                select(Subscription).where(
                    Subscription.user_id.in_(user_ids),
                    Subscription.status.in_([
                        SubscriptionStatus.ACTIVE,
                        SubscriptionStatus.TRIALING,
                    ]),
                )
            )
            for sub in sub_result.scalars().all():
                active_subs_by_user[sub.user_id] = sub

        for site in expired_sites:
            days_overdue = (now - site.expires_at).days

            lead = site.lead
            if not lead or not lead.created_by:
                continue

            user = users_by_id.get(lead.created_by)
            if not user:
                continue

            active_sub = active_subs_by_user.get(user.id)
            if active_sub:
                # User renewed — extend expires_at
                if active_sub.current_period_end:
                    site.expires_at = active_sub.current_period_end
                    db.add(site)
                continue

            if days_overdue >= GRACE_PERIOD_DAYS:
                # Archive the site
                site.status = SiteStatus.ARCHIVED
                db.add(site)
                logger.info("Archived site %s (overdue %d days)", site.id, days_overdue)
                await _send_site_archived_email(user, site)
            elif days_overdue >= 12:
                await _send_grace_warning_email(user, site, days_left=GRACE_PERIOD_DAYS - days_overdue)
            elif days_overdue >= 7:
                await _send_grace_warning_email(user, site, days_left=GRACE_PERIOD_DAYS - days_overdue)

        await db.commit()


async def _send_grace_warning_email(user: User, site: GeneratedSite, days_left: int) -> None:
    """Send grace period warning email."""
    if not settings.RESEND_API_KEY:
        return

    subject = f"Din hemsida arkiveras om {days_left} dagar — Qvicko"
    if days_left <= 2:
        subject = "SISTA VARNING: Din hemsida arkiveras snart — Qvicko"

    try:
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
                    "subject": subject,
                    "html": f"""
                    <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
                        <h2>Hej {user.full_name},</h2>
                        <p>Din betalning för Qvicko har misslyckats och din publicerade hemsida
                        ({site.subdomain or site.id}) kommer att arkiveras om <strong>{days_left} dagar</strong>.</p>
                        <p>Uppdatera ditt betalkort för att behålla din hemsida aktiv.</p>
                        <p><a href="{settings.FRONTEND_URL}/dashboard/billing"
                            style="background: #4F46E5; color: white; padding: 12px 24px;
                            text-decoration: none; border-radius: 8px; display: inline-block;">
                            Uppdatera betalning</a></p>
                        <p>Med vänlig hälsning,<br>Qvicko-teamet</p>
                    </div>
                    """,
                },
            )
    except Exception:
        logger.exception("Failed to send grace warning email to %s", user.email)


async def _send_site_archived_email(user: User, site: GeneratedSite) -> None:
    """Send site archived notification email."""
    if not settings.RESEND_API_KEY:
        return

    try:
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
                    "subject": "Din hemsida har arkiverats — Qvicko",
                    "html": f"""
                    <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
                        <h2>Hej {user.full_name},</h2>
                        <p>Din hemsida ({site.subdomain or site.id}) har arkiverats
                        på grund av utebliven betalning.</p>
                        <p>Du kan återaktivera din hemsida genom att teckna en ny prenumeration.</p>
                        <p><a href="{settings.FRONTEND_URL}/dashboard/billing"
                            style="background: #4F46E5; color: white; padding: 12px 24px;
                            text-decoration: none; border-radius: 8px; display: inline-block;">
                            Teckna prenumeration</a></p>
                        <p>Med vänlig hälsning,<br>Qvicko-teamet</p>
                    </div>
                    """,
                },
            )
    except Exception:
        logger.exception("Failed to send archived email to %s", user.email)
