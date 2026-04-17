"""
Email service using Resend.

Handles sending outreach emails, tracking opens/clicks, and webhook processing.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.email.templates import build_outreach_email
from app.sites.models import EmailStatus, GeneratedSite, Lead, OutreachEmail

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com"


async def send_outreach_email(
    db: AsyncSession,
    lead: Lead,
    site: GeneratedSite,
    base_url: str = "http://localhost:3000",
) -> OutreachEmail:
    """
    Send an outreach email to a lead with their demo site link.
    Creates an OutreachEmail record and sends via Resend.
    """
    if not lead.email:
        raise ValueError("Lead has no email address")

    demo_url = f"{base_url}/sites/{site.id}"
    business_name = lead.business_name or "ert företag"

    subject, html_body, plain_text = build_outreach_email(
        business_name=business_name,
        demo_url=demo_url,
        from_name=settings.RESEND_FROM_NAME,
    )

    # Create DB record
    outreach = OutreachEmail(
        lead_id=lead.id,
        site_id=site.id,
        to_email=lead.email,
        subject=subject,
        body_html=html_body,
        status=EmailStatus.PENDING,
    )
    db.add(outreach)
    await db.flush()

    # Send via Resend
    try:
        resend_id = await _send_via_resend(
            to=lead.email,
            subject=subject,
            html=html_body,
            text=plain_text,
        )
        outreach.resend_id = resend_id
        outreach.status = EmailStatus.SENT
        outreach.sent_at = datetime.now(timezone.utc)
        logger.info("Email sent to %s (resend_id=%s)", lead.email, resend_id)
    except Exception as e:
        outreach.status = EmailStatus.FAILED
        logger.error("Failed to send email to %s: %s", lead.email, e)
        raise

    return outreach


async def _send_via_resend(
    to: str,
    subject: str,
    html: str,
    text: str,
) -> str:
    """Send email via Resend API. Returns the Resend message ID."""
    if not settings.RESEND_API_KEY:
        raise RuntimeError("RESEND_API_KEY not configured")

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{RESEND_API_URL}/emails",
            headers={
                "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": f"{settings.RESEND_FROM_NAME} <{settings.RESEND_FROM_EMAIL}>",
                "to": [to],
                "subject": subject,
                "html": html,
                "text": text,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["id"]


async def process_resend_webhook(db: AsyncSession, payload: dict) -> None:
    """
    Process a Resend webhook event.
    Updates the OutreachEmail status based on the event type.
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
