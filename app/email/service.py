"""
Email service.

- Outreach emails: Sent via Smartlead (cold outreach with warmup/tracking).
- Transactional emails: Sent via Resend (password reset, verification, billing).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.sites.models import EmailStatus, GeneratedSite, Lead, OutreachEmail

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com"


# ------------------------------------------------------------------
# Outreach emails (via Smartlead)
# ------------------------------------------------------------------

async def send_outreach_email(
    db: AsyncSession,
    lead: Lead,
    site: GeneratedSite,
    base_url: str = "http://localhost:3000",
) -> OutreachEmail:
    """
    Send an outreach email to a lead with their demo site link.

    Delegates to Smartlead for actual delivery, warmup, and tracking.
    """
    from app.smartlead.service import add_lead_to_campaign

    return await add_lead_to_campaign(db, lead, site)


# ------------------------------------------------------------------
# Transactional emails (via Resend)
# ------------------------------------------------------------------

async def send_transactional_email(
    to: str,
    subject: str,
    html: str,
    text: str | None = None,
    from_name: str | None = None,
    from_email: str | None = None,
) -> str:
    """
    Send a transactional email via Resend.

    Used for password resets, verification, billing alerts, site lifecycle.
    Returns the Resend message ID.
    """
    return await _send_via_resend(
        to=to,
        subject=subject,
        html=html,
        text=text or "",
        from_name=from_name,
        from_email=from_email,
    )


async def _send_via_resend(
    to: str,
    subject: str,
    html: str,
    text: str,
    from_name: str | None = None,
    from_email: str | None = None,
) -> str:
    """Send email via Resend API. Returns the Resend message ID."""
    if not settings.RESEND_API_KEY:
        raise RuntimeError("RESEND_API_KEY not configured")

    sender_name = from_name or settings.RESEND_FROM_NAME
    sender_email = from_email or settings.RESEND_FROM_EMAIL

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{RESEND_API_URL}/emails",
            headers={
                "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": f"{sender_name} <{sender_email}>",
                "to": [to],
                "subject": subject,
                "html": html,
                "text": text,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["id"]


# ------------------------------------------------------------------
# Resend webhook processing (transactional email tracking)
# ------------------------------------------------------------------

async def process_resend_webhook(db: AsyncSession, payload: dict) -> None:
    """
    Process a Resend webhook event.
    Updates the OutreachEmail status based on the event type.

    Note: This only handles legacy Resend-sent outreach emails.
    Smartlead emails are tracked via the background poller.
    """
    event_type = payload.get("type", "")
    data = payload.get("data", {})
    email_id = data.get("email_id")

    if not email_id:
        return

    result = await db.execute(
        select(OutreachEmail).where(OutreachEmail.resend_id == email_id)
    )
    outreach = result.scalar_one_or_none()
    if not outreach:
        logger.warning("Webhook for unknown email_id: %s", email_id)
        return

    now = datetime.now(timezone.utc)
    event_map = {
        "email.delivered": EmailStatus.DELIVERED,
        "email.opened": EmailStatus.OPENED,
        "email.clicked": EmailStatus.CLICKED,
        "email.bounced": EmailStatus.BOUNCED,
    }

    new_status = event_map.get(event_type)
    if not new_status:
        return

    outreach.status = new_status

    if new_status == EmailStatus.OPENED and not outreach.opened_at:
        outreach.opened_at = now
    elif new_status == EmailStatus.CLICKED and not outreach.clicked_at:
        outreach.clicked_at = now

    logger.info("Email %s: %s -> %s", email_id, event_type, new_status.value)
