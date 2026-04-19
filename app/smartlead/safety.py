"""
Send safety guards for Smartlead outreach.

Enforces daily sending limits, warmup schedules, and domain blocklists
to protect sender reputation and avoid blacklisting.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.sites.models import OutreachEmail, EmailStatus
from app.smartlead.models import SmartleadEmailAccount

logger = logging.getLogger(__name__)

# Domains that should never receive cold outreach
DOMAIN_BLOCKLIST = frozenset({
    # Personal email providers — unlikely to be business decision-makers
    "gmail.com", "googlemail.com",
    "yahoo.com", "yahoo.se", "yahoo.co.uk",
    "hotmail.com", "hotmail.se",
    "outlook.com", "outlook.se",
    "live.com", "live.se",
    "msn.com",
    "icloud.com", "me.com", "mac.com",
    "aol.com",
    "protonmail.com", "proton.me",
    "tutanota.com", "tuta.io",
    "zoho.com",
    "yandex.com", "yandex.ru",
    "mail.com", "email.com",
    # Swedish ISP emails
    "telia.com", "bredband.net", "comhem.se", "spray.se",
    # Catch-all / disposable
    "tempmail.com", "guerrillamail.com", "throwaway.email",
    "mailinator.com", "sharklasers.com",
    # Our own domains
    "qvicko.com", "qvickosite.com",
})


def is_domain_blocked(email: str) -> bool:
    """Check if a recipient email domain is on the blocklist."""
    if not email or "@" not in email:
        return True
    domain = email.rsplit("@", 1)[1].lower()
    return domain in DOMAIN_BLOCKLIST


class SendGuard:
    """Enforces sending limits based on warmup schedule and domain reputation."""

    async def can_send(
        self, db: AsyncSession, recipient_email: str
    ) -> tuple[bool, str]:
        """
        Check if we can send right now.

        Returns (allowed, reason). If allowed is False, reason explains why.
        """
        # 1. Check recipient domain blocklist
        if is_domain_blocked(recipient_email):
            domain = recipient_email.rsplit("@", 1)[1] if "@" in recipient_email else "unknown"
            return False, f"Domänen {domain} är blockerad (personlig/blocklistad e-post)"

        # 2. Check daily send count vs limit
        stats = await self.get_daily_stats(db)
        if not stats["can_send"]:
            return False, (
                f"Daglig sändgräns nådd ({stats['sent_today']}/{stats['limit']}). "
                f"Försök igen imorgon."
            )

        return True, ""

    async def get_daily_stats(self, db: AsyncSession) -> dict:
        """Get today's send count vs limit."""
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        # Count emails sent today via Smartlead
        result = await db.execute(
            select(func.count(OutreachEmail.id)).where(
                OutreachEmail.sent_via == "smartlead",
                OutreachEmail.created_at >= today_start,
                OutreachEmail.status != EmailStatus.FAILED,
            )
        )
        sent_today = result.scalar() or 0

        # Get effective limit from account config or global setting
        limit = await self._get_effective_limit(db)

        return {
            "sent_today": sent_today,
            "limit": limit,
            "can_send": sent_today < limit,
        }

    async def _get_effective_limit(self, db: AsyncSession) -> int:
        """
        Calculate effective daily limit.

        Uses the lowest of: account-level limit, global setting.
        During warmup, the account limit ramps up gradually.
        """
        hard_limit = settings.SMARTLEAD_DAILY_SEND_LIMIT

        # Check if we have a local email account record
        result = await db.execute(
            select(SmartleadEmailAccount).where(
                SmartleadEmailAccount.is_active.is_(True)
            ).limit(1)
        )
        account = result.scalar_one_or_none()

        if not account:
            return hard_limit

        # During warmup, calculate ramped limit based on account age
        if account.warmup_enabled:
            days_active = (datetime.now(timezone.utc) - account.created_at).days
            ramped_limit = account.warmup_per_day + (days_active * account.daily_rampup)
            account_limit = min(ramped_limit, account.max_daily_sends)
        else:
            account_limit = account.max_daily_sends

        return min(account_limit, hard_limit)

    async def get_warmup_status(self, db: AsyncSession) -> dict:
        """Get warmup status for display in dashboard."""
        result = await db.execute(
            select(SmartleadEmailAccount).where(
                SmartleadEmailAccount.is_active.is_(True)
            ).limit(1)
        )
        account = result.scalar_one_or_none()

        if not account:
            return {
                "status": "not_configured",
                "current_day": 0,
                "warmup_days_target": 14,
                "daily_limit": settings.SMARTLEAD_DAILY_SEND_LIMIT,
            }

        days_active = (datetime.now(timezone.utc) - account.created_at).days
        warmup_complete = not account.warmup_enabled or days_active >= 14

        return {
            "status": "warmed" if warmup_complete else "warming_up",
            "current_day": min(days_active, 14),
            "warmup_days_target": 14,
            "daily_limit": await self._get_effective_limit(db),
            "email": account.email,
            "domain": account.domain,
        }
