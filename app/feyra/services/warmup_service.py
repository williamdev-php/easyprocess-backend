"""Warmup service — pairing accounts, generating emails, reputation scoring."""

import logging
import random
from datetime import datetime, timedelta, timezone

import anthropic
from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.feyra.models import (
    EmailAccount,
    WarmupEmail,
    WarmupEmailDirection,
    WarmupEmailStatus,
    WarmupSettings,
    WarmupStatus,
)

logger = logging.getLogger(__name__)

_ai_client = anthropic.AsyncAnthropic()

# ---------------------------------------------------------------------------
# Pairing
# ---------------------------------------------------------------------------


async def get_warmup_pairs(db: AsyncSession) -> list[tuple[str, str]]:
    """Pair warmup-enabled accounts across different users for sending.

    Returns a list of (sender_account_id, receiver_account_id) tuples.
    Each account appears at most once as sender and once as receiver.
    """
    result = await db.execute(
        select(EmailAccount).where(
            and_(
                EmailAccount.warmup_status.in_([WarmupStatus.WARMING, WarmupStatus.READY]),
                EmailAccount.connection_status == "connected",
            )
        )
    )
    accounts = list(result.scalars().all())

    if len(accounts) < 2:
        return []

    # Group accounts by user_id to avoid pairing accounts owned by the same user
    by_user: dict[str, list] = {}
    for acc in accounts:
        by_user.setdefault(acc.user_id, []).append(acc)

    if len(by_user) < 2:
        logger.info("Not enough distinct users for warmup pairing")
        return []

    # Shuffle and pair across users
    random.shuffle(accounts)
    pairs: list[tuple[str, str]] = []
    used_senders: set[str] = set()
    used_receivers: set[str] = set()

    for sender in accounts:
        if sender.id in used_senders:
            continue
        for receiver in accounts:
            if receiver.id in used_receivers:
                continue
            if receiver.user_id == sender.user_id:
                continue
            if receiver.id == sender.id:
                continue
            pairs.append((sender.id, receiver.id))
            used_senders.add(sender.id)
            used_receivers.add(receiver.id)
            break

    return pairs


# ---------------------------------------------------------------------------
# Volume calculation
# ---------------------------------------------------------------------------


async def calculate_daily_volume(settings: WarmupSettings) -> int:
    """Calculate how many warmup emails to send today based on the ramp-up schedule.

    Linearly ramps from 1 email/day to max_daily_volume over ramp_up_days.
    """
    if not settings.enabled:
        return 0

    max_volume = settings.max_daily_volume or 20
    ramp_days = settings.ramp_up_days or 30

    # Calculate days since warmup started
    start_date = settings.created_at
    if hasattr(settings, "started_at") and settings.started_at:
        start_date = settings.started_at

    days_active = (datetime.now(timezone.utc) - start_date).days
    if days_active < 0:
        return 0

    if days_active >= ramp_days:
        return max_volume

    # Linear ramp: start at 1, end at max_volume
    volume = max(1, int(1 + (max_volume - 1) * (days_active / ramp_days)))
    return min(volume, max_volume)


# ---------------------------------------------------------------------------
# AI email generation
# ---------------------------------------------------------------------------


async def generate_warmup_email(from_email: str, to_email: str) -> tuple[str, str]:
    """Use Claude to generate a short conversational warmup email.

    Returns (subject, body_html). Keeps under 100 words, no links or images.
    """
    prompt = (
        "Generate a short, natural-sounding email between two professionals. "
        "The email should look like a genuine casual conversation — asking a question, "
        "sharing a quick thought, or following up on something. "
        "Do NOT include any links, images, or marketing language. "
        "Keep the body under 100 words. "
        "Return ONLY the subject line on the first line, then a blank line, then the body in plain text. "
        "No HTML, no formatting markers."
    )

    response = await _ai_client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()
    lines = text.split("\n", 1)
    subject = lines[0].strip()
    body = lines[1].strip() if len(lines) > 1 else ""

    # Remove common prefixes the model might add
    for prefix in ("Subject:", "Subject Line:", "Re:"):
        if subject.lower().startswith(prefix.lower()):
            subject = subject[len(prefix):].strip()

    # Wrap body in minimal HTML
    body_html = f"<p>{body.replace(chr(10), '</p><p>')}</p>"

    return subject, body_html


async def generate_warmup_reply(
    original_subject: str, original_body: str
) -> tuple[str, str]:
    """Generate a contextual 1-3 sentence reply to a warmup email.

    Returns (subject, body_html).
    """
    prompt = (
        f"You received this email:\n"
        f"Subject: {original_subject}\n"
        f"Body: {original_body}\n\n"
        "Write a brief, natural reply (1-3 sentences). "
        "Do NOT include any links, images, or marketing language. "
        "Return ONLY the reply body in plain text. No subject line, no formatting markers."
    )

    response = await _ai_client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )

    body = response.content[0].text.strip()
    subject = f"Re: {original_subject}" if not original_subject.lower().startswith("re:") else original_subject
    body_html = f"<p>{body.replace(chr(10), '</p><p>')}</p>"

    return subject, body_html


# ---------------------------------------------------------------------------
# Reputation scoring
# ---------------------------------------------------------------------------


async def calculate_reputation_score(db: AsyncSession, account_id: str) -> int:
    """Calculate email reputation score 0-100 based on warmup email metrics.

    Weights: delivery rate 40%, spam rate 25%, reply rate 20%, bounce rate 15%.
    """
    # Get counts of sent warmup emails for this account (last 30 days)
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    base_filter = and_(
        WarmupEmail.sender_account_id == account_id,
        WarmupEmail.direction == WarmupEmailDirection.SENT,
        WarmupEmail.created_at >= cutoff,
    )

    total_result = await db.execute(
        select(func.count()).select_from(WarmupEmail).where(base_filter)
    )
    total_sent = total_result.scalar() or 0

    if total_sent == 0:
        return 50  # Neutral score for new accounts

    # Delivered count
    delivered_result = await db.execute(
        select(func.count()).select_from(WarmupEmail).where(
            and_(
                base_filter,
                WarmupEmail.status.in_([
                    WarmupEmailStatus.DELIVERED,
                    WarmupEmailStatus.OPENED,
                    WarmupEmailStatus.REPLIED,
                ]),
            )
        )
    )
    delivered = delivered_result.scalar() or 0

    # Spam count
    spam_result = await db.execute(
        select(func.count()).select_from(WarmupEmail).where(
            and_(base_filter, WarmupEmail.status == WarmupEmailStatus.SPAM)
        )
    )
    spam_count = spam_result.scalar() or 0

    # Reply count
    reply_result = await db.execute(
        select(func.count()).select_from(WarmupEmail).where(
            and_(base_filter, WarmupEmail.status == WarmupEmailStatus.REPLIED)
        )
    )
    reply_count = reply_result.scalar() or 0

    # Bounce count
    bounce_result = await db.execute(
        select(func.count()).select_from(WarmupEmail).where(
            and_(base_filter, WarmupEmail.status == WarmupEmailStatus.BOUNCED)
        )
    )
    bounce_count = bounce_result.scalar() or 0

    delivery_rate = delivered / total_sent
    spam_rate = spam_count / total_sent
    reply_rate = reply_count / total_sent
    bounce_rate = bounce_count / total_sent

    # Score components (higher is better)
    delivery_score = delivery_rate * 100  # 0-100
    spam_score = (1 - spam_rate) * 100  # lower spam = higher score
    reply_score = min(reply_rate * 200, 100)  # 50% reply rate = perfect score
    bounce_score = (1 - bounce_rate) * 100  # lower bounce = higher score

    # Weighted total
    score = (
        delivery_score * 0.40
        + spam_score * 0.25
        + reply_score * 0.20
        + bounce_score * 0.15
    )

    return max(0, min(100, int(round(score))))


# ---------------------------------------------------------------------------
# Readiness check
# ---------------------------------------------------------------------------


async def check_warmup_readiness(
    db: AsyncSession, account_id: str
) -> tuple[bool, str]:
    """Check if an account is ready for production campaigns.

    Criteria: spam rate < 5%, delivery rate > 90%, reputation > 70.
    Returns (is_ready, reason_message).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)
    base_filter = and_(
        WarmupEmail.sender_account_id == account_id,
        WarmupEmail.direction == WarmupEmailDirection.SENT,
        WarmupEmail.created_at >= cutoff,
    )

    total_result = await db.execute(
        select(func.count()).select_from(WarmupEmail).where(base_filter)
    )
    total_sent = total_result.scalar() or 0

    if total_sent < 20:
        return False, f"Insufficient warmup volume: {total_sent} emails sent in last 14 days (need at least 20)"

    # Delivered
    delivered_result = await db.execute(
        select(func.count()).select_from(WarmupEmail).where(
            and_(
                base_filter,
                WarmupEmail.status.in_([
                    WarmupEmailStatus.DELIVERED,
                    WarmupEmailStatus.OPENED,
                    WarmupEmailStatus.REPLIED,
                ]),
            )
        )
    )
    delivered = delivered_result.scalar() or 0
    delivery_rate = delivered / total_sent

    # Spam
    spam_result = await db.execute(
        select(func.count()).select_from(WarmupEmail).where(
            and_(base_filter, WarmupEmail.status == WarmupEmailStatus.SPAM)
        )
    )
    spam_count = spam_result.scalar() or 0
    spam_rate = spam_count / total_sent

    reputation = await calculate_reputation_score(db, account_id)

    issues = []
    if spam_rate >= 0.05:
        issues.append(f"Spam rate too high: {spam_rate:.1%} (must be < 5%)")
    if delivery_rate <= 0.90:
        issues.append(f"Delivery rate too low: {delivery_rate:.1%} (must be > 90%)")
    if reputation <= 70:
        issues.append(f"Reputation score too low: {reputation} (must be > 70)")

    if issues:
        return False, "; ".join(issues)

    return True, f"Account is ready — delivery: {delivery_rate:.1%}, spam: {spam_rate:.1%}, reputation: {reputation}"


# ---------------------------------------------------------------------------
# Main warmup processing
# ---------------------------------------------------------------------------


async def process_warmup_cycle(db: AsyncSession) -> None:
    """Main warmup processing cycle.

    Pairs accounts, calculates volumes, generates warmup emails, and creates
    WarmupEmail records for sending.
    """
    from app.feyra.services.email_account_service import send_email_smtp

    pairs = await get_warmup_pairs(db)
    if not pairs:
        logger.info("No warmup pairs available")
        return

    for sender_id, receiver_id in pairs:
        try:
            # Load accounts
            sender_result = await db.execute(
                select(EmailAccount).where(EmailAccount.id == sender_id)
            )
            sender = sender_result.scalar_one_or_none()

            receiver_result = await db.execute(
                select(EmailAccount).where(EmailAccount.id == receiver_id)
            )
            receiver = receiver_result.scalar_one_or_none()

            if not sender or not receiver:
                continue

            # Get warmup settings for sender
            settings_result = await db.execute(
                select(WarmupSettings).where(WarmupSettings.email_account_id == sender_id)
            )
            ws = settings_result.scalar_one_or_none()
            if not ws:
                continue

            volume = await calculate_daily_volume(ws)

            # Check how many already sent today
            today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            sent_today_result = await db.execute(
                select(func.count()).select_from(WarmupEmail).where(
                    and_(
                        WarmupEmail.sender_account_id == sender_id,
                        WarmupEmail.direction == WarmupEmailDirection.SENT,
                        WarmupEmail.created_at >= today_start,
                    )
                )
            )
            sent_today = sent_today_result.scalar() or 0

            remaining = volume - sent_today
            if remaining <= 0:
                continue

            for _ in range(remaining):
                try:
                    subject, body_html = await generate_warmup_email(sender.email, receiver.email)
                    body_text = subject  # Fallback plain text

                    msg_id = await send_email_smtp(
                        sender, receiver.email, subject, body_html, body_text
                    )

                    # Record the sent warmup email
                    warmup_email = WarmupEmail(
                        sender_account_id=sender_id,
                        receiver_account_id=receiver_id,
                        direction=WarmupEmailDirection.SENT,
                        status=WarmupEmailStatus.SENT,
                        subject=subject,
                        message_id=msg_id,
                    )
                    db.add(warmup_email)
                    await db.flush()

                    # Random delay between sends (2-8 seconds)
                    import asyncio
                    await asyncio.sleep(random.uniform(2, 8))

                except Exception:
                    logger.exception(
                        "Failed to send warmup email from %s to %s",
                        sender.email, receiver.email,
                    )

        except Exception:
            logger.exception("Error processing warmup pair %s -> %s", sender_id, receiver_id)


# ---------------------------------------------------------------------------
# Spam rescue
# ---------------------------------------------------------------------------


async def process_spam_rescue(db: AsyncSession) -> None:
    """Check spam folders for warmup emails and move them back to inbox.

    This improves sender reputation by signaling to the mail provider that
    the emails are not spam.
    """
    from app.feyra.services.email_account_service import (
        check_spam_folder,
        move_email_from_spam,
    )

    # Get all active warmup accounts
    result = await db.execute(
        select(EmailAccount).where(
            EmailAccount.warmup_status.in_([WarmupStatus.WARMING, WarmupStatus.READY])
        )
    )
    accounts = result.scalars().all()

    # Collect all warmup message IDs for quick lookup
    warmup_msg_result = await db.execute(
        select(WarmupEmail.message_id).where(
            WarmupEmail.message_id.isnot(None)
        )
    )
    warmup_message_ids: set[str] = {row[0] for row in warmup_msg_result.all()}

    for account in accounts:
        try:
            spam_emails = await check_spam_folder(account)
            for email_data in spam_emails:
                msg_id = email_data.get("message_id", "")
                if msg_id in warmup_message_ids:
                    moved = await move_email_from_spam(account, msg_id)
                    if moved:
                        # Update the warmup email status
                        await db.execute(
                            update(WarmupEmail)
                            .where(WarmupEmail.message_id == msg_id)
                            .values(status=WarmupEmailStatus.DELIVERED)
                        )
                        await db.flush()
                        logger.info(
                            "Rescued warmup email %s from spam for %s",
                            msg_id, account.email,
                        )
        except Exception:
            logger.exception("Error during spam rescue for %s", account.email)
