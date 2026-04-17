"""Inbound email processing: classification and lead matching."""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.sites.models import InboundEmail, EmailCategory, Lead

logger = logging.getLogger(__name__)


def _extract_domain(email: str) -> str | None:
    """Extract domain from email address."""
    if "@" not in email:
        return None
    return email.split("@")[-1].strip().lower()


def _extract_domain_from_url(url: str) -> str | None:
    """Extract domain from URL."""
    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        host = parsed.hostname
        if host:
            # Remove www. prefix
            return host.lower().removeprefix("www.")
    except Exception:
        pass
    return None


async def classify_email(
    subject: str | None, body_text: str | None, from_email: str
) -> tuple[EmailCategory, float, str]:
    """
    Classify inbound email using Anthropic Haiku.
    Returns (category, spam_score, ai_summary).
    """
    if not settings.ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not set, skipping classification")
        return EmailCategory.OTHER, 0.0, ""

    # Truncate body for cost efficiency
    body_preview = (body_text or "")[:2000]

    prompt = f"""Classify this inbound email. Respond with ONLY a JSON object, no other text.

From: {from_email}
Subject: {subject or '(no subject)'}
Body:
{body_preview}

Respond with this exact JSON format:
{{"category": "spam|lead_reply|support|inquiry|other", "spam_score": 0.0-1.0, "summary": "one sentence summary in Swedish"}}

Rules:
- "spam": marketing, phishing, unsolicited ads, newsletters, automated notifications (spam_score > 0.7)
- "lead_reply": reply from a business we contacted about their website (spam_score < 0.2)
- "support": customer asking for help with their site or service (spam_score < 0.2)
- "inquiry": someone interested in our services (spam_score < 0.2)
- "other": anything else (spam_score 0.3-0.5)
"""

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 200,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["content"][0]["text"].strip()

            # Extract JSON from potential markdown code block
            if text.startswith("```"):
                # Remove ```json and ``` markers
                lines = text.split("\n")
                json_lines = [l for l in lines if not l.startswith("```")]
                text = "\n".join(json_lines).strip()

            # Parse JSON response
            result = json.loads(text)

            category_map = {
                "spam": EmailCategory.SPAM,
                "lead_reply": EmailCategory.LEAD_REPLY,
                "support": EmailCategory.SUPPORT,
                "inquiry": EmailCategory.INQUIRY,
                "other": EmailCategory.OTHER,
            }
            category = category_map.get(result.get("category", "other"), EmailCategory.OTHER)
            spam_score = float(result.get("spam_score", 0.5))
            summary = str(result.get("summary", ""))[:500]

            return category, spam_score, summary
    except Exception as e:
        logger.exception("AI classification failed: %s", e)
        return EmailCategory.OTHER, 0.0, ""


async def match_lead(db: AsyncSession, from_email: str) -> str | None:
    """
    Try to match an inbound email to an existing lead.
    Match by domain: if the sender's email domain matches a lead's website domain
    or contact email domain.
    Returns lead_id if matched, None otherwise.
    """
    sender_domain = _extract_domain(from_email)
    if not sender_domain:
        return None

    # First try exact email match on leads
    result = await db.execute(
        select(Lead).where(Lead.email == from_email)
    )
    lead = result.scalar_one_or_none()
    if lead:
        return lead.id

    # Then try domain matching against website_url
    result = await db.execute(select(Lead))
    leads = result.scalars().all()

    for lead in leads:
        # Match against website URL domain
        lead_domain = _extract_domain_from_url(lead.website_url)
        if lead_domain and lead_domain == sender_domain:
            return lead.id

        # Match against lead's email domain
        if lead.email:
            lead_email_domain = _extract_domain(lead.email)
            if lead_email_domain and lead_email_domain == sender_domain:
                return lead.id

    return None


async def process_inbound_email(
    db: AsyncSession, payload: dict
) -> InboundEmail | None:
    """
    Process an inbound email from Resend webhook.
    Classifies it, matches to lead, and stores it.

    Only processes emails to william@qvicko.com and help@qvicko.com.
    Ignores emails to noreply@qvicko.com.
    """
    # Extract email data from Resend inbound webhook payload
    from_email = payload.get("from", "")
    from_name = ""

    # Resend sends "from" as "Name <email>" or just "email"
    if "<" in from_email and ">" in from_email:
        match = re.match(r"^(.*?)\s*<(.+?)>$", from_email)
        if match:
            from_name = match.group(1).strip().strip('"')
            from_email = match.group(2).strip()

    to_email = payload.get("to", "")
    if isinstance(to_email, list):
        to_email = to_email[0] if to_email else ""

    # Extract just the email from "to" field too
    if "<" in to_email and ">" in to_email:
        match = re.match(r"^.*?<(.+?)>$", to_email)
        if match:
            to_email = match.group(1).strip()

    to_email_lower = to_email.lower().strip()

    # Only process emails to william@ and help@, ignore noreply@
    allowed_recipients = {
        settings.EMAIL_WILLIAM.lower(),
        settings.EMAIL_HELP.lower(),
    }
    if to_email_lower not in allowed_recipients:
        logger.info("Ignoring inbound email to %s (not routed)", to_email)
        return None

    subject = payload.get("subject", "")
    body_text = payload.get("text", "") or payload.get("stripped-text", "")
    body_html = payload.get("html", "") or payload.get("stripped-html", "")
    resend_email_id = payload.get("email_id", "") or payload.get("id", "")

    # AI classification
    category, spam_score, ai_summary = await classify_email(
        subject, body_text, from_email
    )

    # Lead matching
    matched_lead_id = await match_lead(db, from_email)

    # Store
    inbound = InboundEmail(
        from_email=from_email,
        from_name=from_name or None,
        to_email=to_email,
        subject=subject or None,
        body_text=body_text or None,
        body_html=body_html or None,
        category=category.value if isinstance(category, EmailCategory) else category,
        spam_score=spam_score,
        ai_summary=ai_summary or None,
        matched_lead_id=matched_lead_id,
        resend_email_id=resend_email_id or None,
    )
    db.add(inbound)
    await db.flush()

    logger.info(
        "Processed inbound email from=%s to=%s category=%s spam=%.2f lead=%s",
        from_email,
        to_email,
        category.value,
        spam_score,
        matched_lead_id or "none",
    )

    return inbound
