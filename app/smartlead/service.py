"""
Smartlead business logic.

Orchestrates campaign management, lead syncing, status polling,
and message history retrieval.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import cache
from app.config import settings
from app.email.templates import build_outreach_email
from app.sites.models import (
    EmailStatus,
    GeneratedSite,
    Lead,
    LeadStatus,
    OutreachEmail,
)
from app.smartlead.client import SmartleadClient, SmartleadError
from app.smartlead.models import SmartleadCampaign, SmartleadEmailAccount
from app.smartlead.safety import SendGuard

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Campaign management
# ------------------------------------------------------------------

async def get_or_create_campaign(db: AsyncSession) -> SmartleadCampaign:
    """Get the active outreach campaign, or create one in Smartlead."""
    # Check for existing active campaign
    result = await db.execute(
        select(SmartleadCampaign).where(
            SmartleadCampaign.status.in_(["ACTIVE", "DRAFTED"])
        ).order_by(SmartleadCampaign.created_at.desc()).limit(1)
    )
    campaign = result.scalar_one_or_none()
    if campaign:
        return campaign

    # Create a new campaign in Smartlead
    client = SmartleadClient()
    sl_campaign = await client.create_campaign("Qvicko Outreach")

    sl_id = sl_campaign.get("id") or sl_campaign.get("campaign_id")
    if not sl_id:
        raise RuntimeError(f"Smartlead create_campaign returned no ID: {sl_campaign}")

    # Set schedule: Mon-Fri 09:00-17:00 Stockholm time
    await client.set_campaign_schedule(sl_id)

    # Configure campaign settings
    await client.update_campaign_settings(sl_id, {
        "send_as_plain_text": True,
        "stop_lead_settings": "REPLY_TO_AN_EMAIL",
    })

    # Save the initial outreach sequence
    subject, _, plain_text = build_outreach_email(
        business_name="{{company_name}}",
        demo_url="{{demo_url}}",
        from_name="William",
    )
    await client.save_sequences(sl_id, [
        {
            "id": None,
            "seq_number": 1,
            "subject": subject.replace("{{company_name}}", "{{company_name}}"),
            "email_body": plain_text.replace("{{company_name}}", "{{company_name}}").replace("{{demo_url}}", "{{demo_url}}"),
            "seq_delay_details": {"delay_in_days": 0},
        },
        {
            "id": None,
            "seq_number": 2,
            "subject": None,
            "email_body": (
                "Hej igen,\n\n"
                "Jag ville bara följa upp mitt förra meddelande. "
                "Vi har tagit fram ett förslag på en ny hemsida åt {{company_name}} "
                "som jag tror ni kommer gilla.\n\n"
                "Ni kan se förslaget här: {{demo_url}}\n\n"
                "Hör gärna av er om ni har frågor!\n\n"
                "Vänliga hälsningar,\nWilliam"
            ),
            "seq_delay_details": {"delay_in_days": 3},
        },
    ])

    # Link email account if we have one
    acct_result = await db.execute(
        select(SmartleadEmailAccount).where(
            SmartleadEmailAccount.is_active.is_(True)
        ).limit(1)
    )
    account = acct_result.scalar_one_or_none()
    if account:
        try:
            await client.add_email_account_to_campaign(
                sl_id, [account.smartlead_account_id]
            )
        except SmartleadError:
            logger.warning("Could not link email account %s to campaign %s", account.email, sl_id)

    # Store locally
    campaign = SmartleadCampaign(
        smartlead_campaign_id=sl_id,
        name="Qvicko Outreach",
        status="DRAFTED",
        sending_account_email=account.email if account else None,
    )
    db.add(campaign)
    await db.flush()
    return campaign


# ------------------------------------------------------------------
# Outreach sending (via Smartlead)
# ------------------------------------------------------------------

async def add_lead_to_campaign(
    db: AsyncSession,
    lead: Lead,
    site: GeneratedSite,
) -> OutreachEmail:
    """
    Add a lead to the Smartlead campaign for outreach.

    This replaces the old Resend-based send_outreach_email for cold outreach.
    The email is not sent immediately — Smartlead handles scheduling and delivery.
    """
    if not lead.email:
        raise ValueError("Lead har ingen e-postadress")

    # Safety check
    guard = SendGuard()
    can_send, reason = await guard.can_send(db, lead.email)
    if not can_send:
        raise ValueError(reason)

    campaign = await get_or_create_campaign(db)

    # Build demo URL
    demo_url = f"https://{site.subdomain}.{settings.BASE_DOMAIN}" if site.subdomain else f"{settings.FRONTEND_URL}/sites/{site.id}"

    # Prepare lead data for Smartlead
    business_name = lead.business_name or "ert företag"
    sl_lead = {
        "email": lead.email,
        "first_name": business_name,
        "company_name": business_name,
        "website": lead.website_url,
        "custom_fields": {
            "demo_url": demo_url,
            "lead_id": lead.id,
            "site_id": site.id,
            "business_name": business_name,
        },
    }
    if lead.phone:
        sl_lead["phone_number"] = lead.phone

    # Add to Smartlead campaign
    client = SmartleadClient()
    result = await client.add_leads(campaign.smartlead_campaign_id, [sl_lead])

    added = result.get("added_count", 0) if isinstance(result, dict) else 0
    if added == 0:
        skipped = result.get("skipped_leads", []) if isinstance(result, dict) else []
        reason = skipped[0].get("reason", "unknown") if skipped else "unknown"
        raise ValueError(f"Smartlead rejected lead: {reason}")

    # Activate campaign if drafted
    if campaign.status == "DRAFTED":
        try:
            await client.update_campaign_status(
                campaign.smartlead_campaign_id, "ACTIVE"
            )
            campaign.status = "ACTIVE"
        except SmartleadError:
            logger.warning("Could not activate campaign %s", campaign.smartlead_campaign_id)

    # Build email text for our local record
    subject, html_body, _ = build_outreach_email(
        business_name=business_name,
        demo_url=demo_url,
        from_name="William",
    )

    # Create local OutreachEmail record
    outreach = OutreachEmail(
        lead_id=lead.id,
        site_id=site.id,
        to_email=lead.email,
        subject=subject,
        body_html=html_body,
        status=EmailStatus.PENDING,
        sent_via="smartlead",
        smartlead_campaign_id=campaign.smartlead_campaign_id,
    )
    db.add(outreach)
    await db.flush()

    logger.info(
        "Lead %s (%s) added to Smartlead campaign %s",
        lead.id, lead.email, campaign.smartlead_campaign_id,
    )
    return outreach


# ------------------------------------------------------------------
# Status sync (background polling)
# ------------------------------------------------------------------

async def sync_lead_statuses(db: AsyncSession) -> None:
    """
    Poll Smartlead for status updates on all pending/sent outreach emails.

    Called by background task every 15 minutes.
    """
    # Get all outreach emails sent via Smartlead that might have status updates
    result = await db.execute(
        select(OutreachEmail).where(
            OutreachEmail.sent_via == "smartlead",
            OutreachEmail.status.in_([
                EmailStatus.PENDING,
                EmailStatus.SENT,
                EmailStatus.DELIVERED,
                EmailStatus.OPENED,
                EmailStatus.CLICKED,
            ]),
            OutreachEmail.smartlead_campaign_id.isnot(None),
        )
    )
    outreach_emails = result.scalars().all()

    if not outreach_emails:
        return

    client = SmartleadClient()

    # Group by campaign for efficient API usage
    by_campaign: dict[int, list[OutreachEmail]] = {}
    for oe in outreach_emails:
        by_campaign.setdefault(oe.smartlead_campaign_id, []).append(oe)

    now = datetime.now(timezone.utc)
    updated_count = 0

    for campaign_id, emails in by_campaign.items():
        try:
            analytics = await client.get_campaign_analytics(campaign_id)
        except SmartleadError as e:
            logger.warning("Failed to fetch analytics for campaign %d: %s", campaign_id, e)
            continue

        # Also try to get per-lead status from campaign leads endpoint
        try:
            sl_leads = await client.get_campaign_leads(campaign_id)
        except SmartleadError:
            sl_leads = []

        # Build email → Smartlead lead status mapping
        sl_lead_map: dict[str, dict] = {}
        if isinstance(sl_leads, list):
            for sl_lead in sl_leads:
                email = sl_lead.get("email", "").lower()
                if email:
                    sl_lead_map[email] = sl_lead

        for oe in emails:
            sl_data = sl_lead_map.get(oe.to_email.lower())
            if not sl_data:
                continue

            sl_status = sl_data.get("lead_status", "").upper()
            sl_id = sl_data.get("id")

            # Update Smartlead lead ID if we don't have it
            if sl_id and not oe.smartlead_lead_id:
                oe.smartlead_lead_id = sl_id

            # Map Smartlead statuses to our EmailStatus
            new_status = _map_smartlead_status(sl_status)
            if new_status and _is_status_progression(oe.status, new_status):
                oe.status = new_status
                updated_count += 1

                if new_status == EmailStatus.SENT and not oe.sent_at:
                    oe.sent_at = now
                elif new_status == EmailStatus.OPENED and not oe.opened_at:
                    oe.opened_at = now
                elif new_status == EmailStatus.CLICKED and not oe.clicked_at:
                    oe.clicked_at = now
                elif new_status == EmailStatus.REPLIED and not oe.replied_at:
                    oe.replied_at = now

                # Update lead status for important transitions
                lead = await db.get(Lead, oe.lead_id)
                if lead:
                    if new_status == EmailStatus.OPENED and lead.status == LeadStatus.EMAIL_SENT:
                        lead.status = LeadStatus.OPENED
                    elif new_status == EmailStatus.REPLIED and lead.status in (
                        LeadStatus.EMAIL_SENT, LeadStatus.OPENED
                    ):
                        lead.status = LeadStatus.REPLIED

    if updated_count > 0:
        await db.commit()
        await cache.delete("admin:dashboard_stats")
        logger.info("Synced %d outreach email statuses from Smartlead", updated_count)


def _map_smartlead_status(sl_status: str) -> EmailStatus | None:
    """Map Smartlead lead status strings to our EmailStatus."""
    mapping = {
        "SENT": EmailStatus.SENT,
        "EMAIL_SENT": EmailStatus.SENT,
        "DELIVERED": EmailStatus.DELIVERED,
        "OPENED": EmailStatus.OPENED,
        "EMAIL_OPEN": EmailStatus.OPENED,
        "CLICKED": EmailStatus.CLICKED,
        "EMAIL_LINK_CLICK": EmailStatus.CLICKED,
        "REPLIED": EmailStatus.REPLIED,
        "EMAIL_REPLY": EmailStatus.REPLIED,
        "BOUNCED": EmailStatus.BOUNCED,
        "BOUNCE": EmailStatus.BOUNCED,
    }
    return mapping.get(sl_status)


# Status progression order — only move forward, never backward
_STATUS_ORDER = {
    EmailStatus.PENDING: 0,
    EmailStatus.SENT: 1,
    EmailStatus.DELIVERED: 2,
    EmailStatus.OPENED: 3,
    EmailStatus.CLICKED: 4,
    EmailStatus.REPLIED: 5,
    EmailStatus.BOUNCED: 1,  # Bounce can happen at any point
    EmailStatus.FAILED: 0,
}


def _is_status_progression(current: EmailStatus, new: EmailStatus) -> bool:
    """Only allow status to move forward in the funnel."""
    if new == EmailStatus.BOUNCED:
        return current not in (EmailStatus.REPLIED, EmailStatus.BOUNCED)
    return _STATUS_ORDER.get(new, 0) > _STATUS_ORDER.get(current, 0)


# ------------------------------------------------------------------
# Message history
# ------------------------------------------------------------------

async def fetch_message_history(db: AsyncSession, lead_id: str) -> list[dict]:
    """
    Fetch Smartlead message history for a lead.

    Returns a list of messages (sent and received) sorted by timestamp.
    Cached for 5 minutes.
    """
    cache_key = f"sl:messages:{lead_id}"
    cached = await cache.get(cache_key)
    if cached:
        return json.loads(cached)

    # Find the outreach email for this lead to get campaign/lead IDs
    result = await db.execute(
        select(OutreachEmail).where(
            OutreachEmail.lead_id == lead_id,
            OutreachEmail.sent_via == "smartlead",
            OutreachEmail.smartlead_campaign_id.isnot(None),
            OutreachEmail.smartlead_lead_id.isnot(None),
        ).order_by(OutreachEmail.created_at.desc()).limit(1)
    )
    outreach = result.scalar_one_or_none()
    if not outreach:
        return []

    client = SmartleadClient()
    try:
        raw_messages = await client.get_message_history(
            outreach.smartlead_campaign_id,
            outreach.smartlead_lead_id,
        )
    except SmartleadError as e:
        logger.warning("Failed to fetch message history for lead %s: %s", lead_id, e)
        return []

    messages = []
    if isinstance(raw_messages, list):
        for msg in raw_messages:
            messages.append({
                "id": str(msg.get("id", "")),
                "type": "reply" if msg.get("type") == "REPLY" or msg.get("direction") == "inbound" else "sent",
                "subject": msg.get("subject"),
                "body": msg.get("text_content") or msg.get("html_content") or msg.get("email_body", ""),
                "from_email": msg.get("from_email", ""),
                "to_email": msg.get("to_email", ""),
                "timestamp": msg.get("time") or msg.get("sent_at") or msg.get("created_at"),
                "status": msg.get("status"),
            })

    # Cache for 5 minutes
    await cache.set(cache_key, json.dumps(messages, default=str), ttl=300)
    return messages


# ------------------------------------------------------------------
# Analytics / Stats
# ------------------------------------------------------------------

async def get_outreach_stats(db: AsyncSession) -> dict:
    """Calculate outreach statistics for the dashboard."""
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)

    # Total sent in last 30 days
    sent_q = await db.execute(
        select(func.count(OutreachEmail.id)).where(
            OutreachEmail.created_at >= thirty_days_ago,
            OutreachEmail.status != EmailStatus.FAILED,
            OutreachEmail.status != EmailStatus.PENDING,
        )
    )
    sent_30d = sent_q.scalar() or 0

    if sent_30d == 0:
        guard = SendGuard()
        daily_stats = await guard.get_daily_stats(db)
        warmup = await guard.get_warmup_status(db)
        return {
            "emails_sent_30d": 0,
            "open_rate": 0.0,
            "reply_rate": 0.0,
            "click_rate": 0.0,
            "bounce_rate": 0.0,
            "conversions_30d": 0,
            "daily_send_count": daily_stats["sent_today"],
            "daily_send_limit": daily_stats["limit"],
            "warmup_status": warmup["status"],
            "warmup_day": warmup["current_day"],
            "warmup_days_target": warmup["warmup_days_target"],
        }

    # Count by status
    opened_q = await db.execute(
        select(func.count(OutreachEmail.id)).where(
            OutreachEmail.created_at >= thirty_days_ago,
            OutreachEmail.status.in_([
                EmailStatus.OPENED, EmailStatus.CLICKED, EmailStatus.REPLIED,
            ]),
        )
    )
    opened_30d = opened_q.scalar() or 0

    replied_q = await db.execute(
        select(func.count(OutreachEmail.id)).where(
            OutreachEmail.created_at >= thirty_days_ago,
            OutreachEmail.status == EmailStatus.REPLIED,
        )
    )
    replied_30d = replied_q.scalar() or 0

    clicked_q = await db.execute(
        select(func.count(OutreachEmail.id)).where(
            OutreachEmail.created_at >= thirty_days_ago,
            OutreachEmail.status.in_([EmailStatus.CLICKED, EmailStatus.REPLIED]),
        )
    )
    clicked_30d = clicked_q.scalar() or 0

    bounced_q = await db.execute(
        select(func.count(OutreachEmail.id)).where(
            OutreachEmail.created_at >= thirty_days_ago,
            OutreachEmail.status == EmailStatus.BOUNCED,
        )
    )
    bounced_30d = bounced_q.scalar() or 0

    # Conversions in last 30 days
    converted_q = await db.execute(
        select(func.count(Lead.id)).where(
            Lead.status == LeadStatus.CONVERTED,
            Lead.updated_at >= thirty_days_ago,
        )
    )
    conversions_30d = converted_q.scalar() or 0

    guard = SendGuard()
    daily_stats = await guard.get_daily_stats(db)
    warmup = await guard.get_warmup_status(db)

    return {
        "emails_sent_30d": sent_30d,
        "open_rate": round(opened_30d / sent_30d * 100, 1) if sent_30d else 0.0,
        "reply_rate": round(replied_30d / sent_30d * 100, 1) if sent_30d else 0.0,
        "click_rate": round(clicked_30d / sent_30d * 100, 1) if sent_30d else 0.0,
        "bounce_rate": round(bounced_30d / sent_30d * 100, 1) if sent_30d else 0.0,
        "conversions_30d": conversions_30d,
        "daily_send_count": daily_stats["sent_today"],
        "daily_send_limit": daily_stats["limit"],
        "warmup_status": warmup["status"],
        "warmup_day": warmup["current_day"],
        "warmup_days_target": warmup["warmup_days_target"],
    }


# ------------------------------------------------------------------
# Conversion tracking
# ------------------------------------------------------------------

async def mark_lead_converted(lead_id: str) -> None:
    """
    Notify Smartlead that a lead has converted (claimed their site).

    Pauses the lead in the campaign so no more follow-up emails are sent.
    Called as a background task from the claim endpoint.
    """
    from app.database import get_db_session

    async with get_db_session() as db:
        result = await db.execute(
            select(OutreachEmail).where(
                OutreachEmail.lead_id == lead_id,
                OutreachEmail.sent_via == "smartlead",
                OutreachEmail.smartlead_campaign_id.isnot(None),
                OutreachEmail.smartlead_lead_id.isnot(None),
            ).limit(1)
        )
        outreach = result.scalar_one_or_none()
        if not outreach:
            return

        client = SmartleadClient()
        try:
            await client.pause_lead(
                outreach.smartlead_campaign_id,
                outreach.smartlead_lead_id,
            )
            logger.info(
                "Paused lead %s in Smartlead campaign %d (converted)",
                lead_id, outreach.smartlead_campaign_id,
            )
        except SmartleadError as e:
            logger.warning("Failed to pause converted lead in Smartlead: %s", e)
