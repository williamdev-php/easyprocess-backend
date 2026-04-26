"""Campaign service — creation, scheduling, sending, reply detection, analytics."""

import logging
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.feyra.models import (
    Campaign,
    CampaignLead,
    CampaignLeadStatus,
    CampaignStatus,
    CampaignStep,
    ConnectionStatus,
    EmailAccount,
    Lead,
    LeadStatus,
    SentEmail,
    SentEmailStatus,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Campaign CRUD
# ---------------------------------------------------------------------------


async def create_campaign(
    db: AsyncSession, user_id: str, data: dict
) -> Campaign:
    """Create a new campaign with steps and assign leads.

    data keys:
      - name: str
      - email_account_id: str
      - subject: str (optional, can be per-step)
      - tone: str (AiTone value)
      - daily_send_limit: int
      - timezone: str
      - steps: list[dict] — each with {delay_days, subject, body_html, body_text}
      - lead_ids: list[str] — IDs of leads to include
    """
    campaign = Campaign(
        user_id=user_id,
        name=data["name"],
        email_account_id=data["email_account_id"],
        status=CampaignStatus.DRAFT,
        daily_send_limit=data.get("daily_send_limit", 50),
        schedule_timezone=data.get("timezone", "UTC"),
    )
    db.add(campaign)
    await db.flush()

    # Create steps
    for idx, step_data in enumerate(data.get("steps", []), start=1):
        step = CampaignStep(
            campaign_id=campaign.id,
            step_number=idx,
            delay_days=step_data.get("delay_days", 0 if idx == 1 else 3),
            subject_template=step_data.get("subject"),
            body_template=step_data.get("body_html", ""),
        )
        db.add(step)

    # Assign leads
    for lead_id in data.get("lead_ids", []):
        campaign_lead = CampaignLead(
            campaign_id=campaign.id,
            lead_id=lead_id,
            status=CampaignLeadStatus.PENDING,
            current_step=1,
        )
        db.add(campaign_lead)

    await db.flush()
    logger.info("Created campaign %s with %d steps and %d leads",
                campaign.id, len(data.get("steps", [])), len(data.get("lead_ids", [])))
    return campaign


# ---------------------------------------------------------------------------
# Campaign lifecycle
# ---------------------------------------------------------------------------


async def launch_campaign(db: AsyncSession, campaign_id: str) -> None:
    """Validate and activate a campaign for sending."""
    result = await db.execute(
        select(Campaign).where(Campaign.id == campaign_id)
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise ValueError(f"Campaign {campaign_id} not found")

    if campaign.status != CampaignStatus.DRAFT:
        raise ValueError(f"Campaign must be in DRAFT status to launch (current: {campaign.status.value})")

    # Validate: has steps
    steps_result = await db.execute(
        select(func.count()).select_from(CampaignStep).where(
            CampaignStep.campaign_id == campaign_id
        )
    )
    step_count = steps_result.scalar() or 0
    if step_count == 0:
        raise ValueError("Campaign must have at least one step")

    # Validate: has leads
    leads_result = await db.execute(
        select(func.count()).select_from(CampaignLead).where(
            CampaignLead.campaign_id == campaign_id
        )
    )
    lead_count = leads_result.scalar() or 0
    if lead_count == 0:
        raise ValueError("Campaign must have at least one lead")

    # Validate: email account is connected
    account_result = await db.execute(
        select(EmailAccount).where(EmailAccount.id == campaign.email_account_id)
    )
    account = account_result.scalar_one_or_none()
    if not account or account.connection_status != ConnectionStatus.CONNECTED:
        raise ValueError("Email account is not connected")

    # Activate
    await db.execute(
        update(Campaign)
        .where(Campaign.id == campaign_id)
        .values(
            status=CampaignStatus.ACTIVE,
            send_start_date=datetime.now(timezone.utc),
        )
    )

    # Schedule first batch
    await schedule_campaign_emails(db, campaign_id)

    await db.flush()
    logger.info("Campaign %s launched", campaign_id)


async def pause_campaign(db: AsyncSession, campaign_id: str) -> None:
    """Pause an active campaign."""
    result = await db.execute(
        select(Campaign).where(Campaign.id == campaign_id)
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise ValueError(f"Campaign {campaign_id} not found")

    if campaign.status != CampaignStatus.ACTIVE:
        raise ValueError(f"Can only pause ACTIVE campaigns (current: {campaign.status.value})")

    await db.execute(
        update(Campaign)
        .where(Campaign.id == campaign_id)
        .values(status=CampaignStatus.PAUSED)
    )
    await db.flush()
    logger.info("Campaign %s paused", campaign_id)


async def resume_campaign(db: AsyncSession, campaign_id: str) -> None:
    """Resume a paused campaign."""
    result = await db.execute(
        select(Campaign).where(Campaign.id == campaign_id)
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise ValueError(f"Campaign {campaign_id} not found")

    if campaign.status != CampaignStatus.PAUSED:
        raise ValueError(f"Can only resume PAUSED campaigns (current: {campaign.status.value})")

    await db.execute(
        update(Campaign)
        .where(Campaign.id == campaign_id)
        .values(status=CampaignStatus.ACTIVE)
    )

    # Re-schedule pending emails
    await schedule_campaign_emails(db, campaign_id)

    await db.flush()
    logger.info("Campaign %s resumed", campaign_id)


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------


async def schedule_campaign_emails(
    db: AsyncSession, campaign_id: str
) -> None:
    """Calculate send times and set next_send_at for each pending CampaignLead."""
    result = await db.execute(
        select(Campaign).where(Campaign.id == campaign_id)
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        return

    # Get campaign steps ordered by step number
    steps_result = await db.execute(
        select(CampaignStep)
        .where(CampaignStep.campaign_id == campaign_id)
        .order_by(CampaignStep.step_number)
    )
    steps = {s.step_number: s for s in steps_result.scalars().all()}

    if not steps:
        return

    # Get pending/active leads
    leads_result = await db.execute(
        select(CampaignLead).where(
            and_(
                CampaignLead.campaign_id == campaign_id,
                CampaignLead.status.in_([
                    CampaignLeadStatus.PENDING,
                    CampaignLeadStatus.ACTIVE,
                ]),
            )
        )
    )
    campaign_leads = leads_result.scalars().all()

    daily_limit = campaign.daily_send_limit or 50
    now = datetime.now(timezone.utc)
    scheduled_count = 0
    day_offset = 0

    for cl in campaign_leads:
        current_step = steps.get(cl.current_step)
        if not current_step:
            continue

        # Calculate base send time from step delay
        delay_days = current_step.delay_days or 0
        base_time = now + timedelta(days=delay_days + day_offset)

        # Add random jitter (0-30 minutes) to appear more human
        jitter_minutes = random.randint(0, 30)
        send_at = base_time + timedelta(minutes=jitter_minutes)

        cl.next_send_at = send_at
        if cl.status == CampaignLeadStatus.PENDING:
            cl.status = CampaignLeadStatus.ACTIVE

        scheduled_count += 1

        # Respect daily send limit
        if scheduled_count >= daily_limit:
            scheduled_count = 0
            day_offset += 1

    await db.flush()
    logger.info("Scheduled emails for campaign %s", campaign_id)


# ---------------------------------------------------------------------------
# Queue processing
# ---------------------------------------------------------------------------


async def process_campaign_queue(db: AsyncSession) -> None:
    """Send queued campaign emails where next_send_at <= now."""
    from app.feyra.services.ai_writer_service import personalize_template
    from app.feyra.services.email_account_service import send_email_smtp

    now = datetime.now(timezone.utc)

    # Get campaign leads ready to send
    result = await db.execute(
        select(CampaignLead)
        .where(
            and_(
                CampaignLead.status == CampaignLeadStatus.ACTIVE,
                CampaignLead.next_send_at <= now,
                CampaignLead.next_send_at.isnot(None),
            )
        )
        .limit(100)
    )
    campaign_leads = result.scalars().all()

    for cl in campaign_leads:
        try:
            # Load campaign, step, lead, and account
            campaign_result = await db.execute(
                select(Campaign).where(Campaign.id == cl.campaign_id)
            )
            campaign = campaign_result.scalar_one_or_none()
            if not campaign or campaign.status != CampaignStatus.ACTIVE:
                continue

            step_result = await db.execute(
                select(CampaignStep).where(
                    and_(
                        CampaignStep.campaign_id == cl.campaign_id,
                        CampaignStep.step_number == cl.current_step,
                    )
                )
            )
            step = step_result.scalar_one_or_none()
            if not step:
                continue

            lead_result = await db.execute(
                select(Lead).where(Lead.id == cl.lead_id)
            )
            lead = lead_result.scalar_one_or_none()
            if not lead:
                continue

            account_result = await db.execute(
                select(EmailAccount).where(EmailAccount.id == campaign.email_account_id)
            )
            account = account_result.scalar_one_or_none()
            if not account:
                continue

            # Build lead data for personalization
            lead_data = {
                "first_name": lead.first_name or "",
                "last_name": lead.last_name or "",
                "company": lead.company_name or "",
                "job_title": lead.job_title or "",
                "email": lead.email,
                "phone": lead.phone or "",
                "city": lead.location or "",
                "country": lead.country or "",
                "website": lead.website_url or "",
                "industry": lead.industry or "",
            }

            # Personalize subject and body
            subject = personalize_template(step.subject_template or "", lead_data)
            body_html = personalize_template(step.body_template or "", lead_data)
            body_text = personalize_template(step.body_template or "", lead_data)

            # Determine reply-to and in-reply-to for follow-ups
            in_reply_to = None
            if cl.current_step > 1:
                # Look up the last sent email's message_id for threading
                last_sent_result = await db.execute(
                    select(SentEmail.message_id)
                    .where(
                        and_(
                            SentEmail.campaign_lead_id == cl.id,
                            SentEmail.status == SentEmailStatus.SENT,
                        )
                    )
                    .order_by(SentEmail.sent_at.desc())
                    .limit(1)
                )
                last_msg_id = last_sent_result.scalar_one_or_none()
                if last_msg_id:
                    in_reply_to = last_msg_id

            # Send the email
            message_id = await send_email_smtp(
                account, lead.email, subject, body_html, body_text,
                in_reply_to=in_reply_to,
            )

            # Record sent email
            sent_email = SentEmail(
                campaign_id=cl.campaign_id,
                campaign_lead_id=cl.id,
                email_account_id=account.id,
                step_number=step.step_number,
                to_email=lead.email,
                subject=subject,
                body_html=body_html,
                body_text=body_text,
                message_id=message_id,
                status=SentEmailStatus.SENT,
                sent_at=datetime.now(timezone.utc),
            )
            db.add(sent_email)

            # Update campaign lead
            cl.last_sent_at = datetime.now(timezone.utc)

            # Check if there is a next step
            next_step_result = await db.execute(
                select(CampaignStep).where(
                    and_(
                        CampaignStep.campaign_id == cl.campaign_id,
                        CampaignStep.step_number == cl.current_step + 1,
                    )
                )
            )
            next_step = next_step_result.scalar_one_or_none()

            if next_step:
                # Schedule next step
                cl.current_step += 1
                delay = next_step.delay_days or 3
                jitter = random.randint(0, 30)
                cl.next_send_at = datetime.now(timezone.utc) + timedelta(days=delay, minutes=jitter)
            else:
                # Campaign sequence complete for this lead
                cl.status = CampaignLeadStatus.COMPLETED
                cl.next_send_at = None

            # Update lead status if this is the first email
            if lead.status == LeadStatus.NEW:
                lead.status = LeadStatus.CONTACTED

            await db.flush()
            logger.info(
                "Sent campaign email to %s (campaign=%s, step=%d)",
                lead.email, cl.campaign_id, step.step_number,
            )

        except Exception:
            logger.exception("Failed to send campaign email for CampaignLead %s", cl.id)
            # Don't block other sends — continue with next lead


# ---------------------------------------------------------------------------
# Reply detection
# ---------------------------------------------------------------------------


async def detect_replies(db: AsyncSession, account_id: str) -> None:
    """Check the inbox of an email account for campaign replies.

    Matches incoming emails to sent campaign emails by In-Reply-To or References headers.
    """
    from app.feyra.services.email_account_service import read_inbox_imap

    account_result = await db.execute(
        select(EmailAccount).where(EmailAccount.id == account_id)
    )
    account = account_result.scalar_one_or_none()
    if not account:
        return

    # Read recent inbox messages
    since = datetime.now(timezone.utc) - timedelta(days=7)
    emails = await read_inbox_imap(account, folder="INBOX", since_date=since, limit=100)

    # Get sent message IDs for this account's campaigns
    # Join with CampaignLead to get lead_id, since SentEmail doesn't store it directly
    sent_result = await db.execute(
        select(SentEmail.message_id, SentEmail.campaign_lead_id, CampaignLead.lead_id)
        .join(CampaignLead, SentEmail.campaign_lead_id == CampaignLead.id)
        .where(SentEmail.email_account_id == account_id)
    )
    sent_map: dict[str, tuple[str, str]] = {}
    for row in sent_result.all():
        if row[0]:
            sent_map[row[0]] = (row[1], row[2])

    for email_data in emails:
        in_reply_to = email_data.get("in_reply_to", "").strip()
        references = email_data.get("references", "").strip()

        # Check if this is a reply to one of our sent emails
        matched_msg_id = None
        if in_reply_to in sent_map:
            matched_msg_id = in_reply_to
        else:
            for ref in references.split():
                ref = ref.strip()
                if ref in sent_map:
                    matched_msg_id = ref
                    break

        if not matched_msg_id:
            continue

        campaign_lead_id, lead_id = sent_map[matched_msg_id]

        # Check if we already processed this reply
        from_email = email_data.get("from", "")
        reply_msg_id = email_data.get("message_id", "")

        existing = await db.execute(
            select(func.count()).select_from(SentEmail).where(
                and_(
                    SentEmail.message_id == reply_msg_id,
                    SentEmail.status == SentEmailStatus.REPLIED,
                )
            )
        )
        if existing.scalar() > 0:
            continue

        # Update the sent email status
        await db.execute(
            update(SentEmail)
            .where(SentEmail.message_id == matched_msg_id)
            .values(status=SentEmailStatus.REPLIED)
        )

        # Update campaign lead
        await db.execute(
            update(CampaignLead)
            .where(CampaignLead.id == campaign_lead_id)
            .values(
                status=CampaignLeadStatus.REPLIED,
                next_send_at=None,  # Stop sending follow-ups
            )
        )

        # Update lead status
        await db.execute(
            update(Lead)
            .where(Lead.id == lead_id)
            .values(status=LeadStatus.REPLIED)
        )

        await db.flush()
        logger.info("Detected reply from %s to campaign email %s", from_email, matched_msg_id)


# ---------------------------------------------------------------------------
# Bounce handling
# ---------------------------------------------------------------------------


async def handle_bounce(
    db: AsyncSession, campaign_lead_id: str, is_hard: bool
) -> None:
    """Process an email bounce for a campaign lead.

    Hard bounces permanently stop sending to the lead.
    Soft bounces increment a counter and stop after 3 consecutive soft bounces.
    """
    result = await db.execute(
        select(CampaignLead).where(CampaignLead.id == campaign_lead_id)
    )
    cl = result.scalar_one_or_none()
    if not cl:
        logger.warning("CampaignLead %s not found for bounce handling", campaign_lead_id)
        return

    if is_hard:
        # Hard bounce: stop sending, mark as bounced
        cl.status = CampaignLeadStatus.BOUNCED
        cl.next_send_at = None

        # Also mark the lead as bounced
        await db.execute(
            update(Lead)
            .where(Lead.id == cl.lead_id)
            .values(status=LeadStatus.BOUNCED)
        )

        # Update the most recent sent email
        await db.execute(
            update(SentEmail)
            .where(
                and_(
                    SentEmail.campaign_lead_id == campaign_lead_id,
                    SentEmail.status == SentEmailStatus.SENT,
                )
            )
            .values(status=SentEmailStatus.BOUNCED)
        )

        logger.info("Hard bounce for CampaignLead %s — stopped sending", campaign_lead_id)
    else:
        # Soft bounce: count previous bounces from SentEmail records
        bounce_count_result = await db.execute(
            select(func.count()).select_from(SentEmail).where(
                and_(
                    SentEmail.campaign_lead_id == campaign_lead_id,
                    SentEmail.status == SentEmailStatus.BOUNCED,
                )
            )
        )
        bounce_count = (bounce_count_result.scalar() or 0) + 1

        if bounce_count >= 3:
            cl.status = CampaignLeadStatus.BOUNCED
            cl.next_send_at = None
            logger.info(
                "CampaignLead %s bounced after %d soft bounces",
                campaign_lead_id, bounce_count,
            )
        else:
            # Retry after a delay
            cl.next_send_at = datetime.now(timezone.utc) + timedelta(hours=24)
            logger.info(
                "Soft bounce %d/3 for CampaignLead %s — retrying in 24h",
                bounce_count, campaign_lead_id,
            )

    await db.flush()


# ---------------------------------------------------------------------------
# Campaign analytics
# ---------------------------------------------------------------------------


async def get_campaign_analytics(db: AsyncSession, campaign_id: str) -> dict:
    """Aggregate campaign statistics.

    Returns a dict with counts and rates for key metrics.
    """
    # Total leads
    total_result = await db.execute(
        select(func.count()).select_from(CampaignLead).where(
            CampaignLead.campaign_id == campaign_id
        )
    )
    total_leads = total_result.scalar() or 0

    # Lead status breakdown
    status_result = await db.execute(
        select(CampaignLead.status, func.count())
        .where(CampaignLead.campaign_id == campaign_id)
        .group_by(CampaignLead.status)
    )
    status_counts = {row[0].value if hasattr(row[0], "value") else str(row[0]): row[1] for row in status_result.all()}

    # Sent email stats
    sent_total_result = await db.execute(
        select(func.count()).select_from(SentEmail).where(
            SentEmail.campaign_id == campaign_id
        )
    )
    total_sent = sent_total_result.scalar() or 0

    # Email status breakdown
    email_status_result = await db.execute(
        select(SentEmail.status, func.count())
        .where(SentEmail.campaign_id == campaign_id)
        .group_by(SentEmail.status)
    )
    email_status_counts = {
        row[0].value if hasattr(row[0], "value") else str(row[0]): row[1]
        for row in email_status_result.all()
    }

    delivered = email_status_counts.get("delivered", 0) + email_status_counts.get("opened", 0) + email_status_counts.get("replied", 0)
    opened = email_status_counts.get("opened", 0) + email_status_counts.get("replied", 0)
    replied = email_status_counts.get("replied", 0)
    bounced = email_status_counts.get("bounced", 0)
    spam = email_status_counts.get("spam_complaint", 0)

    # Calculate rates
    delivery_rate = (delivered / total_sent * 100) if total_sent > 0 else 0
    open_rate = (opened / delivered * 100) if delivered > 0 else 0
    reply_rate = (replied / delivered * 100) if delivered > 0 else 0
    bounce_rate = (bounced / total_sent * 100) if total_sent > 0 else 0
    spam_rate = (spam / total_sent * 100) if total_sent > 0 else 0

    # Emails sent per step
    step_result = await db.execute(
        select(CampaignStep.step_number, func.count(SentEmail.id))
        .outerjoin(
            SentEmail,
            and_(
                SentEmail.campaign_id == CampaignStep.campaign_id,
                SentEmail.step_number == CampaignStep.step_number,
            ),
        )
        .where(CampaignStep.campaign_id == campaign_id)
        .group_by(CampaignStep.step_number)
        .order_by(CampaignStep.step_number)
    )
    per_step = [{"step": row[0], "sent": row[1]} for row in step_result.all()]

    return {
        "total_leads": total_leads,
        "lead_status": status_counts,
        "total_sent": total_sent,
        "delivered": delivered,
        "opened": opened,
        "replied": replied,
        "bounced": bounced,
        "spam_complaints": spam,
        "delivery_rate": round(delivery_rate, 1),
        "open_rate": round(open_rate, 1),
        "reply_rate": round(reply_rate, 1),
        "bounce_rate": round(bounce_rate, 1),
        "spam_rate": round(spam_rate, 1),
        "per_step": per_step,
    }
