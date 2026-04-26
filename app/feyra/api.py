"""Feyra main API router — email warmup, leads, crawls, campaigns, AI writer."""

import csv
import io
import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, update, delete, and_, or_, case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.feyra.auth_dependencies import get_current_feyra_user
from app.feyra.models import (
    FeyraUser,
    EmailProvider,
    ConnectionStatus,
    WarmupStatus,
    WarmupEmailDirection,
    WarmupEmailStatus,
    LeadSource,
    LeadStatus,
    CrawlType,
    CrawlJobStatus,
    CampaignStatus,
    AITone,
    SentEmailStatus,
    AIModelPreference,
)
from app.database import get_db
from app.rate_limit import limiter

from app.feyra.schemas import (
    # Email accounts
    EmailAccountCreate,
    EmailAccountUpdate,
    EmailAccountResponse,
    EmailAccountDetail,
    ConnectionTestResponse,
    WarmupStatsResponse,
    # Leads
    LeadCreate,
    LeadUpdate,
    LeadResponse,
    LeadListResponse,
    LeadImportRequest,
    BulkActionRequest,
    # Crawls
    CrawlJobCreate,
    CrawlJobResponse,
    CrawlJobDetail,
    # Campaigns
    CampaignCreate,
    CampaignUpdate,
    CampaignResponse,
    CampaignDetail,
    CampaignStepCreate,
    CampaignStepUpdate,
    CampaignStepResponse,
    CampaignAnalytics,
    CampaignEmailResponse,
    CampaignEmailListResponse,
    CampaignReplyResponse,
    CampaignReplyListResponse,
    # AI
    GenerateEmailRequest,
    GenerateEmailResponse,
    GenerateSubjectLinesRequest,
    RewriteEmailRequest,
    SpamCheckRequest,
    SpamCheckResponse,
    # Settings
    GlobalSettingsResponse,
    GlobalSettingsUpdate,
    # Dashboard
    DashboardStats,
    ActivityFeedItem,
    # Warmup
    WarmupDashboardResponse,
    WarmupEmailResponse,
    WarmupEmailListResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/feyra", tags=["Feyra"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


_MODEL_ALIASES = {
    "FeyraEmailAccount": "EmailAccount",
    "FeyraWarmupEmail": "WarmupEmail",
    "FeyraWarmupSettings": "WarmupSettings",
    "FeyraLead": "Lead",
    "FeyraCrawlJob": "CrawlJob",
    "FeyraCrawlResult": "CrawlResult",
    "FeyraCampaign": "Campaign",
    "FeyraCampaignStep": "CampaignStep",
    "FeyraCampaignLead": "CampaignLead",
    "FeyraCampaignEmail": "SentEmail",
    "FeyraCampaignReply": "SentEmail",
    "FeyraSentEmail": "SentEmail",
    "FeyraSettings": "GlobalSettings",
}


async def _get_model(name: str):
    """Dynamically import a Feyra model by name."""
    from app.feyra import models as m
    real_name = _MODEL_ALIASES.get(name, name)
    return getattr(m, real_name)


# ---------------------------------------------------------------------------
# Email Accounts
# ---------------------------------------------------------------------------


@router.post("/email-accounts", response_model=EmailAccountResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def create_email_account(
    body: EmailAccountCreate,
    request: Request,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a new email account with optional auto-detection of provider settings."""
    FeyraEmailAccount = await _get_model("FeyraEmailAccount")

    # Check for duplicate
    existing = await db.execute(
        select(FeyraEmailAccount).where(
            and_(
                FeyraEmailAccount.user_id == str(current_user.id),
                FeyraEmailAccount.email_address == body.email_address,
            )
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email account already connected")

    # Auto-detect provider from email domain
    domain = body.email_address.split("@")[-1].lower() if "@" in body.email_address else ""
    provider = EmailProvider.CUSTOM
    if "gmail" in domain or "google" in domain:
        provider = EmailProvider.GMAIL
    elif "outlook" in domain or "hotmail" in domain or "live" in domain:
        provider = EmailProvider.OUTLOOK
    elif "yahoo" in domain:
        provider = EmailProvider.YAHOO

    # Auto-fill IMAP/SMTP defaults if not provided
    imap_host = body.imap_host
    imap_port = body.imap_port
    smtp_host = body.smtp_host
    smtp_port = body.smtp_port
    if provider == EmailProvider.GMAIL and not imap_host:
        imap_host = "imap.gmail.com"
        imap_port = imap_port or 993
        smtp_host = smtp_host or "smtp.gmail.com"
        smtp_port = smtp_port or 587
    elif provider == EmailProvider.OUTLOOK and not imap_host:
        imap_host = "outlook.office365.com"
        imap_port = imap_port or 993
        smtp_host = smtp_host or "smtp.office365.com"
        smtp_port = smtp_port or 587
    elif provider == EmailProvider.YAHOO and not imap_host:
        imap_host = "imap.mail.yahoo.com"
        imap_port = imap_port or 993
        smtp_host = smtp_host or "smtp.mail.yahoo.com"
        smtp_port = smtp_port or 587

    account = FeyraEmailAccount(
        id=_uuid(),
        user_id=str(current_user.id),
        email_address=body.email_address,
        display_name=body.display_name,
        provider=provider,
        imap_host=imap_host,
        imap_port=imap_port or 993,
        imap_username=body.imap_username or body.email_address,
        imap_password_encrypted=body.imap_password or "",
        imap_use_ssl=body.imap_use_ssl,
        smtp_host=smtp_host,
        smtp_port=smtp_port or 587,
        smtp_username=body.smtp_username or body.email_address,
        smtp_password_encrypted=body.smtp_password or "",
        smtp_use_tls=body.smtp_use_tls,
        connection_status=ConnectionStatus.PENDING,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(account)
    await db.flush()
    await db.refresh(account)
    return EmailAccountResponse.model_validate(account)


@router.get("/email-accounts", response_model=list[EmailAccountResponse])
async def list_email_accounts(
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """List all email accounts belonging to the current user."""
    FeyraEmailAccount = await _get_model("FeyraEmailAccount")
    result = await db.execute(
        select(FeyraEmailAccount)
        .where(FeyraEmailAccount.user_id == str(current_user.id))
        .order_by(FeyraEmailAccount.created_at.desc())
    )
    accounts = result.scalars().all()
    return [EmailAccountResponse.model_validate(a) for a in accounts]


@router.get("/email-accounts/{account_id}", response_model=EmailAccountDetail)
async def get_email_account(
    account_id: str,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Get email account details including warmup stats."""
    FeyraEmailAccount = await _get_model("FeyraEmailAccount")
    result = await db.execute(
        select(FeyraEmailAccount).where(
            and_(
                FeyraEmailAccount.id == account_id,
                FeyraEmailAccount.user_id == str(current_user.id),
            )
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email account not found")

    # Build warmup stats
    warmup_stats = WarmupStatsResponse(
        sender_reputation_score=account.sender_reputation_score,
    )

    # Get warmup settings status
    try:
        FeyraWarmupSettings = await _get_model("FeyraWarmupSettings")
        ws_result = await db.execute(
            select(FeyraWarmupSettings).where(FeyraWarmupSettings.email_account_id == account_id)
        )
        ws = ws_result.scalar_one_or_none()
        if ws:
            warmup_stats.status = str(ws.status.value) if ws.status else None
            warmup_stats.current_day = ws.current_day
    except Exception:
        pass

    # Count today's warmup emails
    try:
        FeyraWarmupEmail = await _get_model("FeyraWarmupEmail")
        today_start = _now().replace(hour=0, minute=0, second=0, microsecond=0)
        sent_q = select(func.count()).select_from(FeyraWarmupEmail).where(
            and_(
                FeyraWarmupEmail.from_account_id == account_id,
                FeyraWarmupEmail.direction == WarmupEmailDirection.SENT,
                FeyraWarmupEmail.created_at >= today_start,
            )
        )
        warmup_stats.emails_sent_today = (await db.execute(sent_q)).scalar() or 0

        recv_q = select(func.count()).select_from(FeyraWarmupEmail).where(
            and_(
                FeyraWarmupEmail.to_account_id == account_id,
                FeyraWarmupEmail.direction == WarmupEmailDirection.RECEIVED,
                FeyraWarmupEmail.created_at >= today_start,
            )
        )
        warmup_stats.emails_received_today = (await db.execute(recv_q)).scalar() or 0
    except Exception:
        pass  # Models may not exist yet

    resp = EmailAccountDetail.model_validate(account)
    resp.warmup_stats = warmup_stats
    resp.emails_sent_today = warmup_stats.emails_sent_today
    resp.emails_received_today = warmup_stats.emails_received_today
    return resp


@router.patch("/email-accounts/{account_id}", response_model=EmailAccountResponse)
async def update_email_account(
    account_id: str,
    body: EmailAccountUpdate,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Update email account settings."""
    FeyraEmailAccount = await _get_model("FeyraEmailAccount")
    result = await db.execute(
        select(FeyraEmailAccount).where(
            and_(
                FeyraEmailAccount.id == account_id,
                FeyraEmailAccount.user_id == str(current_user.id),
            )
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email account not found")

    updates = body.model_dump(exclude_unset=True)
    # Map schema field names to model field names
    field_map = {"imap_password": "imap_password_encrypted", "smtp_password": "smtp_password_encrypted"}
    for field, value in updates.items():
        model_field = field_map.get(field, field)
        setattr(account, model_field, value)
    account.updated_at = _now()

    await db.flush()
    await db.refresh(account)
    return EmailAccountResponse.model_validate(account)


@router.delete("/email-accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_email_account(
    account_id: str,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Disconnect and delete an email account."""
    FeyraEmailAccount = await _get_model("FeyraEmailAccount")
    result = await db.execute(
        select(FeyraEmailAccount).where(
            and_(
                FeyraEmailAccount.id == account_id,
                FeyraEmailAccount.user_id == str(current_user.id),
            )
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email account not found")

    await db.delete(account)
    await db.flush()


@router.post("/email-accounts/{account_id}/test", response_model=ConnectionTestResponse)
@limiter.limit("5/minute")
async def test_email_account(
    account_id: str,
    request: Request,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Test IMAP and SMTP connectivity for an email account."""
    FeyraEmailAccount = await _get_model("FeyraEmailAccount")
    result = await db.execute(
        select(FeyraEmailAccount).where(
            and_(
                FeyraEmailAccount.id == account_id,
                FeyraEmailAccount.user_id == str(current_user.id),
            )
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email account not found")

    imap_ok = False
    smtp_ok = False
    imap_message = "Not tested"
    smtp_message = "Not tested"

    # Test IMAP
    try:
        import imaplib
        if account.imap_use_ssl:
            imap = imaplib.IMAP4_SSL(account.imap_host, account.imap_port)
        else:
            imap = imaplib.IMAP4(account.imap_host, account.imap_port)
        imap.login(account.imap_username, account.imap_password_encrypted)
        imap.logout()
        imap_ok = True
        imap_message = "Connection successful"
    except Exception as e:
        imap_message = f"IMAP connection failed: {str(e)}"

    # Test SMTP
    try:
        import smtplib
        if account.smtp_use_tls:
            smtp = smtplib.SMTP(account.smtp_host, account.smtp_port, timeout=10)
            smtp.starttls()
        else:
            smtp = smtplib.SMTP(account.smtp_host, account.smtp_port, timeout=10)
        smtp.login(account.smtp_username, account.smtp_password_encrypted)
        smtp.quit()
        smtp_ok = True
        smtp_message = "Connection successful"
    except Exception as e:
        smtp_message = f"SMTP connection failed: {str(e)}"

    # Update connection status
    if imap_ok and smtp_ok:
        account.connection_status = ConnectionStatus.CONNECTED
    else:
        account.connection_status = ConnectionStatus.ERROR
    account.updated_at = _now()
    await db.flush()

    return ConnectionTestResponse(
        imap_ok=imap_ok,
        smtp_ok=smtp_ok,
        imap_message=imap_message,
        smtp_message=smtp_message,
    )


@router.post("/email-accounts/{account_id}/warmup/start", response_model=EmailAccountResponse)
async def start_warmup(
    account_id: str,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Start email warmup for an account."""
    FeyraEmailAccount = await _get_model("FeyraEmailAccount")
    result = await db.execute(
        select(FeyraEmailAccount).where(
            and_(
                FeyraEmailAccount.id == account_id,
                FeyraEmailAccount.user_id == str(current_user.id),
            )
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email account not found")

    if account.warmup_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Warmup already active")

    account.warmup_enabled = True
    account.warmup_started_at = _now()
    account.updated_at = _now()

    # Ensure WarmupSettings exists and set to WARMING
    FeyraWarmupSettings = await _get_model("FeyraWarmupSettings")
    ws_result = await db.execute(
        select(FeyraWarmupSettings).where(FeyraWarmupSettings.email_account_id == account_id)
    )
    ws = ws_result.scalar_one_or_none()
    if not ws:
        ws = FeyraWarmupSettings(
            id=_uuid(),
            email_account_id=account_id,
            status=WarmupStatus.WARMING,
            created_at=_now(),
            updated_at=_now(),
        )
        db.add(ws)
    else:
        ws.status = WarmupStatus.WARMING
        ws.updated_at = _now()

    await db.flush()
    await db.refresh(account)
    return EmailAccountResponse.model_validate(account)


@router.post("/email-accounts/{account_id}/warmup/pause", response_model=EmailAccountResponse)
async def pause_warmup(
    account_id: str,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Pause email warmup for an account."""
    FeyraEmailAccount = await _get_model("FeyraEmailAccount")
    result = await db.execute(
        select(FeyraEmailAccount).where(
            and_(
                FeyraEmailAccount.id == account_id,
                FeyraEmailAccount.user_id == str(current_user.id),
            )
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email account not found")

    if not account.warmup_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Warmup is not active")

    # Set WarmupSettings status to PAUSED
    FeyraWarmupSettings = await _get_model("FeyraWarmupSettings")
    ws_result = await db.execute(
        select(FeyraWarmupSettings).where(FeyraWarmupSettings.email_account_id == account_id)
    )
    ws = ws_result.scalar_one_or_none()
    if ws:
        ws.status = WarmupStatus.PAUSED
        ws.updated_at = _now()

    account.updated_at = _now()
    await db.flush()
    await db.refresh(account)
    return EmailAccountResponse.model_validate(account)


@router.post("/email-accounts/{account_id}/warmup/stop", response_model=EmailAccountResponse)
async def stop_warmup(
    account_id: str,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Stop email warmup for an account."""
    FeyraEmailAccount = await _get_model("FeyraEmailAccount")
    result = await db.execute(
        select(FeyraEmailAccount).where(
            and_(
                FeyraEmailAccount.id == account_id,
                FeyraEmailAccount.user_id == str(current_user.id),
            )
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email account not found")

    account.warmup_enabled = False
    account.warmup_completed_at = _now()
    account.updated_at = _now()

    # Set WarmupSettings status to IDLE
    FeyraWarmupSettings = await _get_model("FeyraWarmupSettings")
    ws_result = await db.execute(
        select(FeyraWarmupSettings).where(FeyraWarmupSettings.email_account_id == account_id)
    )
    ws = ws_result.scalar_one_or_none()
    if ws:
        ws.status = WarmupStatus.IDLE
        ws.updated_at = _now()

    await db.flush()
    await db.refresh(account)
    return EmailAccountResponse.model_validate(account)


@router.get("/email-accounts/{account_id}/warmup/stats", response_model=WarmupStatsResponse)
async def get_warmup_stats(
    account_id: str,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Get warmup metrics for a specific email account."""
    FeyraEmailAccount = await _get_model("FeyraEmailAccount")
    result = await db.execute(
        select(FeyraEmailAccount).where(
            and_(
                FeyraEmailAccount.id == account_id,
                FeyraEmailAccount.user_id == str(current_user.id),
            )
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email account not found")

    stats = WarmupStatsResponse(
        sender_reputation_score=account.sender_reputation_score,
    )

    # Get warmup settings
    try:
        FeyraWarmupSettings = await _get_model("FeyraWarmupSettings")
        ws_result = await db.execute(
            select(FeyraWarmupSettings).where(FeyraWarmupSettings.email_account_id == account_id)
        )
        ws = ws_result.scalar_one_or_none()
        if ws:
            stats.status = str(ws.status.value) if ws.status else None
            stats.current_day = ws.current_day
    except Exception:
        pass

    try:
        FeyraWarmupEmail = await _get_model("FeyraWarmupEmail")
        today_start = _now().replace(hour=0, minute=0, second=0, microsecond=0)

        # Today's counts
        sent_today = (await db.execute(
            select(func.count()).select_from(FeyraWarmupEmail).where(
                and_(
                    FeyraWarmupEmail.from_account_id == account_id,
                    FeyraWarmupEmail.direction == WarmupEmailDirection.SENT,
                    FeyraWarmupEmail.created_at >= today_start,
                )
            )
        )).scalar() or 0

        recv_today = (await db.execute(
            select(func.count()).select_from(FeyraWarmupEmail).where(
                and_(
                    FeyraWarmupEmail.to_account_id == account_id,
                    FeyraWarmupEmail.direction == WarmupEmailDirection.RECEIVED,
                    FeyraWarmupEmail.created_at >= today_start,
                )
            )
        )).scalar() or 0

        # Totals
        total_sent = (await db.execute(
            select(func.count()).select_from(FeyraWarmupEmail).where(
                and_(
                    FeyraWarmupEmail.from_account_id == account_id,
                    FeyraWarmupEmail.direction == WarmupEmailDirection.SENT,
                )
            )
        )).scalar() or 0

        total_recv = (await db.execute(
            select(func.count()).select_from(FeyraWarmupEmail).where(
                and_(
                    FeyraWarmupEmail.to_account_id == account_id,
                    FeyraWarmupEmail.direction == WarmupEmailDirection.RECEIVED,
                )
            )
        )).scalar() or 0

        # Spam rate
        spam_count = (await db.execute(
            select(func.count()).select_from(FeyraWarmupEmail).where(
                and_(
                    FeyraWarmupEmail.from_account_id == account_id,
                    FeyraWarmupEmail.direction == WarmupEmailDirection.SENT,
                    FeyraWarmupEmail.status == WarmupEmailStatus.SPAM,
                )
            )
        )).scalar() or 0

        stats.emails_sent_today = sent_today
        stats.emails_received_today = recv_today
        stats.total_sent = total_sent
        stats.total_received = total_recv
        stats.spam_rate = round(spam_count / total_sent * 100, 2) if total_sent > 0 else 0.0
        stats.delivery_rate = round((total_sent - spam_count) / total_sent * 100, 2) if total_sent > 0 else 100.0

        # Current warmup day (days since warmup started)
        if account.warmup_started_at:
            delta = _now() - account.warmup_started_at
            stats.current_day = delta.days
    except Exception:
        pass  # Models may not exist yet

    return stats


# ---------------------------------------------------------------------------
# Warmup (global)
# ---------------------------------------------------------------------------


@router.get("/warmup/dashboard", response_model=WarmupDashboardResponse)
async def warmup_dashboard(
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Global warmup overview across all accounts."""
    FeyraEmailAccount = await _get_model("FeyraEmailAccount")
    result = await db.execute(
        select(FeyraEmailAccount).where(
            FeyraEmailAccount.user_id == str(current_user.id)
        ).order_by(FeyraEmailAccount.created_at.desc())
    )
    accounts = result.scalars().all()

    active = sum(1 for a in accounts if a.warmup_enabled)
    paused = 0  # Would need to check WarmupSettings for PAUSED status

    scores = [a.sender_reputation_score for a in accounts if a.sender_reputation_score is not None]
    avg_rep = round(sum(scores) / len(scores), 2) if scores else None

    return WarmupDashboardResponse(
        total_accounts=len(accounts),
        active_warmups=active,
        paused_warmups=paused,
        average_reputation=avg_rep,
        accounts=[EmailAccountResponse.model_validate(a) for a in accounts],
    )


@router.get("/warmup/emails", response_model=WarmupEmailListResponse)
async def list_warmup_emails(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    account_id: str | None = Query(None),
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """List warmup emails (paginated) for the current user."""
    FeyraWarmupEmail = await _get_model("FeyraWarmupEmail")
    FeyraEmailAccount = await _get_model("FeyraEmailAccount")

    # Get user's account IDs
    acct_result = await db.execute(
        select(FeyraEmailAccount.id).where(
            FeyraEmailAccount.user_id == str(current_user.id)
        )
    )
    user_account_ids = [r[0] for r in acct_result.all()]
    if not user_account_ids:
        return WarmupEmailListResponse(items=[], total=0, page=page, page_size=page_size)

    query = select(FeyraWarmupEmail).where(
        or_(
            FeyraWarmupEmail.from_account_id.in_(user_account_ids),
            FeyraWarmupEmail.to_account_id.in_(user_account_ids),
        )
    )
    if account_id:
        if account_id not in user_account_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        query = select(FeyraWarmupEmail).where(
            or_(
                FeyraWarmupEmail.from_account_id == account_id,
                FeyraWarmupEmail.to_account_id == account_id,
            )
        )

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    query = query.order_by(FeyraWarmupEmail.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = result.scalars().all()

    return WarmupEmailListResponse(
        items=[WarmupEmailResponse.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/warmup/stats", response_model=WarmupStatsResponse)
async def aggregate_warmup_stats(
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate warmup statistics across all user accounts."""
    FeyraEmailAccount = await _get_model("FeyraEmailAccount")

    result = await db.execute(
        select(FeyraEmailAccount).where(
            FeyraEmailAccount.user_id == str(current_user.id)
        )
    )
    accounts = result.scalars().all()

    total_sent = 0
    total_recv = 0
    scores = []

    try:
        FeyraWarmupEmail = await _get_model("FeyraWarmupEmail")
        account_ids = [a.id for a in accounts]
        if account_ids:
            sent = (await db.execute(
                select(func.count()).select_from(FeyraWarmupEmail).where(
                    and_(
                        FeyraWarmupEmail.from_account_id.in_(account_ids),
                        FeyraWarmupEmail.direction == WarmupEmailDirection.SENT,
                    )
                )
            )).scalar() or 0
            recv = (await db.execute(
                select(func.count()).select_from(FeyraWarmupEmail).where(
                    and_(
                        FeyraWarmupEmail.to_account_id.in_(account_ids),
                        FeyraWarmupEmail.direction == WarmupEmailDirection.RECEIVED,
                    )
                )
            )).scalar() or 0
            total_sent = sent
            total_recv = recv
    except Exception:
        pass

    for a in accounts:
        if a.sender_reputation_score is not None:
            scores.append(a.sender_reputation_score)

    return WarmupStatsResponse(
        total_sent=total_sent,
        total_received=total_recv,
        sender_reputation_score=round(sum(scores) / len(scores)) if scores else None,
    )


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------


@router.get("/leads", response_model=LeadListResponse)
async def list_leads(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status"),
    source: str | None = Query(None),
    tag: str | None = Query(None),
    search: str | None = Query(None),
    min_score: int | None = Query(None),
    max_score: int | None = Query(None),
    is_verified: bool | None = Query(None),
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """List leads with filtering and pagination."""
    FeyraLead = await _get_model("FeyraLead")

    query = select(FeyraLead).where(FeyraLead.user_id == str(current_user.id))

    if status_filter:
        query = query.where(FeyraLead.status == status_filter)
    if source:
        query = query.where(FeyraLead.source == source)
    if tag:
        query = query.where(FeyraLead.tags.contains([tag]))
    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(
                FeyraLead.email.ilike(pattern),
                FeyraLead.first_name.ilike(pattern),
                FeyraLead.last_name.ilike(pattern),
                FeyraLead.company_name.ilike(pattern),
            )
        )
    if min_score is not None:
        query = query.where(FeyraLead.lead_score >= min_score)
    if max_score is not None:
        query = query.where(FeyraLead.lead_score <= max_score)
    if is_verified is not None:
        query = query.where(FeyraLead.email_verified == is_verified)

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    query = query.order_by(FeyraLead.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = result.scalars().all()

    return LeadListResponse(
        items=[LeadResponse.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/leads", response_model=LeadResponse, status_code=status.HTTP_201_CREATED)
async def create_lead(
    body: LeadCreate,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a lead manually."""
    FeyraLead = await _get_model("FeyraLead")

    # Check for duplicate email
    existing = await db.execute(
        select(FeyraLead).where(
            and_(
                FeyraLead.user_id == str(current_user.id),
                FeyraLead.email == body.email,
            )
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Lead with this email already exists")

    lead = FeyraLead(
        id=_uuid(),
        user_id=str(current_user.id),
        email=body.email,
        first_name=body.first_name,
        last_name=body.last_name,
        full_name=body.full_name,
        company_name=body.company_name,
        job_title=body.job_title,
        company_domain=body.company_domain,
        industry=body.industry,
        phone=body.phone,
        website_url=body.website_url,
        linkedin_url=body.linkedin_url,
        location=body.location,
        country=body.country,
        tags=body.tags,
        notes=body.notes,
        source=LeadSource.MANUAL,
        status=LeadStatus.NEW,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(lead)
    await db.flush()
    await db.refresh(lead)
    return LeadResponse.model_validate(lead)


@router.get("/leads/{lead_id}", response_model=LeadResponse)
async def get_lead(
    lead_id: str,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Get lead details."""
    FeyraLead = await _get_model("FeyraLead")
    result = await db.execute(
        select(FeyraLead).where(
            and_(
                FeyraLead.id == lead_id,
                FeyraLead.user_id == str(current_user.id),
            )
        )
    )
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    return LeadResponse.model_validate(lead)


@router.patch("/leads/{lead_id}", response_model=LeadResponse)
async def update_lead(
    lead_id: str,
    body: LeadUpdate,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a lead."""
    FeyraLead = await _get_model("FeyraLead")
    result = await db.execute(
        select(FeyraLead).where(
            and_(
                FeyraLead.id == lead_id,
                FeyraLead.user_id == str(current_user.id),
            )
        )
    )
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")

    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(lead, field, value)
    lead.updated_at = _now()

    await db.flush()
    await db.refresh(lead)
    return LeadResponse.model_validate(lead)


@router.delete("/leads/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead(
    lead_id: str,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a lead."""
    FeyraLead = await _get_model("FeyraLead")
    result = await db.execute(
        select(FeyraLead).where(
            and_(
                FeyraLead.id == lead_id,
                FeyraLead.user_id == str(current_user.id),
            )
        )
    )
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")

    await db.delete(lead)
    await db.flush()


@router.post("/leads/import", status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def import_leads(
    request: Request,
    file: UploadFile = File(...),
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Import leads from a CSV file."""
    FeyraLead = await _get_model("FeyraLead")

    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only CSV files are supported")

    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CSV file is empty or has no headers")

    # Map common column names to lead fields
    field_aliases = {
        "email": "email",
        "email_address": "email",
        "e-mail": "email",
        "first_name": "first_name",
        "firstname": "first_name",
        "first name": "first_name",
        "last_name": "last_name",
        "lastname": "last_name",
        "last name": "last_name",
        "company": "company_name",
        "company_name": "company_name",
        "title": "job_title",
        "job_title": "job_title",
        "job title": "job_title",
        "phone": "phone",
        "phone_number": "phone",
        "website": "website_url",
        "website_url": "website_url",
        "url": "website_url",
        "linkedin": "linkedin_url",
        "linkedin_url": "linkedin_url",
        "location": "location",
        "city": "location",
        "industry": "industry",
        "country": "country",
    }

    created = 0
    skipped = 0
    errors_list: list[str] = []

    for row_num, row in enumerate(reader, start=2):
        mapped: dict[str, str] = {}
        for col, val in row.items():
            if col is None:
                continue
            key = field_aliases.get(col.lower().strip(), col.lower().strip())
            mapped[key] = (val or "").strip()

        email = mapped.get("email", "").strip()
        if not email or "@" not in email:
            skipped += 1
            continue

        # Check duplicate
        existing = await db.execute(
            select(FeyraLead.id).where(
                and_(
                    FeyraLead.user_id == str(current_user.id),
                    FeyraLead.email == email,
                )
            )
        )
        if existing.scalar_one_or_none():
            skipped += 1
            continue

        lead = FeyraLead(
            id=_uuid(),
            user_id=str(current_user.id),
            email=email,
            first_name=mapped.get("first_name") or None,
            last_name=mapped.get("last_name") or None,
            company_name=mapped.get("company_name") or None,
            job_title=mapped.get("job_title") or None,
            phone=mapped.get("phone") or None,
            website_url=mapped.get("website_url") or None,
            linkedin_url=mapped.get("linkedin_url") or None,
            location=mapped.get("location") or None,
            industry=mapped.get("industry") or None,
            country=mapped.get("country") or None,
            source=LeadSource.CSV_IMPORT,
            status=LeadStatus.NEW,
            tags=[],
            created_at=_now(),
            updated_at=_now(),
        )
        db.add(lead)
        created += 1

    await db.flush()
    return {"created": created, "skipped": skipped, "errors": errors_list}


@router.post("/leads/export")
async def export_leads(
    status_filter: str | None = Query(None, alias="status"),
    tag: str | None = Query(None),
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Export leads to CSV."""
    FeyraLead = await _get_model("FeyraLead")

    query = select(FeyraLead).where(FeyraLead.user_id == str(current_user.id))
    if status_filter:
        query = query.where(FeyraLead.status == status_filter)
    if tag:
        query = query.where(FeyraLead.tags.contains([tag]))

    result = await db.execute(query.order_by(FeyraLead.created_at.desc()))
    leads = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["email", "first_name", "last_name", "company_name", "job_title", "phone", "website_url", "linkedin_url", "location", "status", "source", "lead_score", "tags"])
    for lead in leads:
        writer.writerow([
            lead.email,
            lead.first_name or "",
            lead.last_name or "",
            lead.company_name or "",
            lead.job_title or "",
            lead.phone or "",
            lead.website_url or "",
            lead.linkedin_url or "",
            lead.location or "",
            lead.status or "",
            lead.source or "",
            lead.lead_score or "",
            ",".join(lead.tags) if lead.tags else "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads_export.csv"},
    )


@router.post("/leads/bulk-action")
async def bulk_action_leads(
    body: BulkActionRequest,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Perform bulk operations on leads."""
    FeyraLead = await _get_model("FeyraLead")

    # Verify ownership of all leads
    result = await db.execute(
        select(FeyraLead).where(
            and_(
                FeyraLead.id.in_(body.lead_ids),
                FeyraLead.user_id == str(current_user.id),
            )
        )
    )
    leads = result.scalars().all()
    if len(leads) != len(body.lead_ids):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Some leads not found or access denied")

    affected = 0

    if body.action == "delete":
        for lead in leads:
            await db.delete(lead)
            affected += 1

    elif body.action == "tag":
        new_tags = body.params.get("tags", [])
        for lead in leads:
            existing_tags = lead.tags or []
            lead.tags = list(set(existing_tags + new_tags))
            lead.updated_at = _now()
            affected += 1

    elif body.action == "untag":
        remove_tags = set(body.params.get("tags", []))
        for lead in leads:
            existing_tags = lead.tags or []
            lead.tags = [t for t in existing_tags if t not in remove_tags]
            lead.updated_at = _now()
            affected += 1

    elif body.action == "update_status":
        new_status = body.params.get("status")
        if not new_status:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing 'status' in params")
        for lead in leads:
            lead.status = new_status
            lead.updated_at = _now()
            affected += 1

    elif body.action == "verify":
        from app.feyra.models import EmailVerificationStatus
        for lead in leads:
            lead.email_verified = True
            lead.email_verification_status = EmailVerificationStatus.VALID
            lead.updated_at = _now()
            affected += 1

    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown action: {body.action}")

    await db.flush()
    return {"affected": affected, "action": body.action}


@router.post("/leads/{lead_id}/verify", response_model=LeadResponse)
@limiter.limit("30/minute")
async def verify_lead_email(
    lead_id: str,
    request: Request,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Verify a lead's email address."""
    FeyraLead = await _get_model("FeyraLead")
    result = await db.execute(
        select(FeyraLead).where(
            and_(
                FeyraLead.id == lead_id,
                FeyraLead.user_id == str(current_user.id),
            )
        )
    )
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")

    # Basic email verification (DNS MX check would go here in production)
    # For now, mark as verified
    from app.feyra.models import EmailVerificationStatus
    lead.email_verified = True
    lead.email_verification_status = EmailVerificationStatus.VALID
    lead.updated_at = _now()
    await db.flush()
    await db.refresh(lead)
    return LeadResponse.model_validate(lead)


# ---------------------------------------------------------------------------
# Crawl Jobs
# ---------------------------------------------------------------------------


@router.post("/crawls", response_model=CrawlJobResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def create_crawl_job(
    body: CrawlJobCreate,
    request: Request,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new crawl/scrape job."""
    FeyraCrawlJob = await _get_model("FeyraCrawlJob")

    job = FeyraCrawlJob(
        id=_uuid(),
        user_id=str(current_user.id),
        name=body.name,
        crawl_type=body.crawl_type,
        seed_urls=body.seed_urls,
        target_domains=body.target_domains,
        max_pages=body.max_pages,
        max_depth=body.max_depth,
        search_query=body.search_query,
        icp_description=body.icp_description,
        status=CrawlJobStatus.PENDING,
        pages_crawled=0,
        leads_found=0,
        emails_found=0,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(job)
    await db.flush()
    await db.refresh(job)
    return CrawlJobResponse.model_validate(job)


@router.get("/crawls", response_model=list[CrawlJobResponse])
async def list_crawl_jobs(
    status_filter: str | None = Query(None, alias="status"),
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """List crawl jobs for the current user."""
    FeyraCrawlJob = await _get_model("FeyraCrawlJob")

    query = select(FeyraCrawlJob).where(FeyraCrawlJob.user_id == str(current_user.id))
    if status_filter:
        query = query.where(FeyraCrawlJob.status == status_filter)

    result = await db.execute(query.order_by(FeyraCrawlJob.created_at.desc()))
    jobs = result.scalars().all()
    return [CrawlJobResponse.model_validate(j) for j in jobs]


@router.get("/crawls/{job_id}", response_model=CrawlJobDetail)
async def get_crawl_job(
    job_id: str,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Get crawl job status and details."""
    FeyraCrawlJob = await _get_model("FeyraCrawlJob")
    result = await db.execute(
        select(FeyraCrawlJob).where(
            and_(
                FeyraCrawlJob.id == job_id,
                FeyraCrawlJob.user_id == str(current_user.id),
            )
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crawl job not found")

    detail = CrawlJobDetail.model_validate(job)
    if job.max_pages and job.pages_crawled:
        detail.progress_percent = round(min(job.pages_crawled / job.max_pages * 100, 100), 1)
    return detail


@router.post("/crawls/{job_id}/pause", response_model=CrawlJobResponse)
async def pause_crawl_job(
    job_id: str,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Pause a running crawl job."""
    FeyraCrawlJob = await _get_model("FeyraCrawlJob")
    result = await db.execute(
        select(FeyraCrawlJob).where(
            and_(
                FeyraCrawlJob.id == job_id,
                FeyraCrawlJob.user_id == str(current_user.id),
            )
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crawl job not found")

    if job.status not in (CrawlJobStatus.RUNNING, CrawlJobStatus.PENDING):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Job cannot be paused in current state")

    job.status = CrawlJobStatus.PAUSED
    job.updated_at = _now()
    await db.flush()
    await db.refresh(job)
    return CrawlJobResponse.model_validate(job)


@router.post("/crawls/{job_id}/resume", response_model=CrawlJobResponse)
async def resume_crawl_job(
    job_id: str,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Resume a paused crawl job."""
    FeyraCrawlJob = await _get_model("FeyraCrawlJob")
    result = await db.execute(
        select(FeyraCrawlJob).where(
            and_(
                FeyraCrawlJob.id == job_id,
                FeyraCrawlJob.user_id == str(current_user.id),
            )
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crawl job not found")

    if job.status != CrawlJobStatus.PAUSED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Job is not paused")

    job.status = CrawlJobStatus.RUNNING
    job.updated_at = _now()
    await db.flush()
    await db.refresh(job)
    return CrawlJobResponse.model_validate(job)


@router.delete("/crawls/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_crawl_job(
    job_id: str,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel and delete a crawl job."""
    FeyraCrawlJob = await _get_model("FeyraCrawlJob")
    result = await db.execute(
        select(FeyraCrawlJob).where(
            and_(
                FeyraCrawlJob.id == job_id,
                FeyraCrawlJob.user_id == str(current_user.id),
            )
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crawl job not found")

    await db.delete(job)
    await db.flush()


@router.get("/crawls/{job_id}/leads", response_model=LeadListResponse)
async def get_crawl_job_leads(
    job_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Get leads found by a crawl job."""
    FeyraCrawlJob = await _get_model("FeyraCrawlJob")
    FeyraLead = await _get_model("FeyraLead")

    # Verify ownership
    job_result = await db.execute(
        select(FeyraCrawlJob).where(
            and_(
                FeyraCrawlJob.id == job_id,
                FeyraCrawlJob.user_id == str(current_user.id),
            )
        )
    )
    if not job_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crawl job not found")

    query = select(FeyraLead).where(
        and_(
            FeyraLead.user_id == str(current_user.id),
            FeyraLead.source == LeadSource.CRAWL,
            FeyraLead.source_url == job_id,
        )
    )

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    query = query.order_by(FeyraLead.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = result.scalars().all()

    return LeadListResponse(
        items=[LeadResponse.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------


@router.post("/campaigns", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    body: CampaignCreate,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new outreach campaign."""
    FeyraCampaign = await _get_model("FeyraCampaign")

    campaign = FeyraCampaign(
        id=_uuid(),
        user_id=str(current_user.id),
        name=body.name,
        description=body.description,
        status=CampaignStatus.DRAFT,
        email_account_id=body.email_account_id,
        daily_send_limit=body.daily_send_limit,
        schedule_start_hour=body.schedule_start_hour,
        schedule_end_hour=body.schedule_end_hour,
        schedule_timezone=body.schedule_timezone,
        days_active=body.days_active,
        delay_between_emails_min_seconds=body.delay_between_emails_min_seconds,
        delay_between_emails_max_seconds=body.delay_between_emails_max_seconds,
        stop_on_reply=body.stop_on_reply,
        track_opens=body.track_opens,
        total_leads=0,
        emails_sent=0,
        emails_opened=0,
        replies_received=0,
        bounces=0,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(campaign)
    await db.flush()

    # Create initial steps
    if body.steps:
        FeyraCampaignStep = await _get_model("FeyraCampaignStep")
        for i, step_data in enumerate(body.steps):
            step = FeyraCampaignStep(
                id=_uuid(),
                campaign_id=campaign.id,
                step_number=step_data.step_number,
                delay_days=step_data.delay_days,
                subject_template=step_data.subject_template,
                body_template=step_data.body_template,
                ai_rewrite_enabled=step_data.ai_rewrite_enabled,
                ai_tone=step_data.ai_tone,
                created_at=_now(),
                updated_at=_now(),
            )
            db.add(step)
        await db.flush()

    await db.refresh(campaign)
    return CampaignResponse.model_validate(campaign)


@router.get("/campaigns", response_model=list[CampaignResponse])
async def list_campaigns(
    status_filter: str | None = Query(None, alias="status"),
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """List campaigns for the current user."""
    FeyraCampaign = await _get_model("FeyraCampaign")

    query = select(FeyraCampaign).where(FeyraCampaign.user_id == str(current_user.id))
    if status_filter:
        query = query.where(FeyraCampaign.status == status_filter)

    result = await db.execute(query.order_by(FeyraCampaign.created_at.desc()))
    campaigns = result.scalars().all()
    return [CampaignResponse.model_validate(c) for c in campaigns]


@router.get("/campaigns/{campaign_id}", response_model=CampaignDetail)
async def get_campaign(
    campaign_id: str,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Get campaign details including steps."""
    FeyraCampaign = await _get_model("FeyraCampaign")
    FeyraCampaignStep = await _get_model("FeyraCampaignStep")

    result = await db.execute(
        select(FeyraCampaign).where(
            and_(
                FeyraCampaign.id == campaign_id,
                FeyraCampaign.user_id == str(current_user.id),
            )
        )
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    steps_result = await db.execute(
        select(FeyraCampaignStep)
        .where(FeyraCampaignStep.campaign_id == campaign_id)
        .order_by(FeyraCampaignStep.step_number)
    )
    steps = steps_result.scalars().all()

    detail = CampaignDetail.model_validate(campaign)
    detail.steps = [CampaignStepResponse.model_validate(s) for s in steps]
    return detail


@router.patch("/campaigns/{campaign_id}", response_model=CampaignResponse)
async def update_campaign(
    campaign_id: str,
    body: CampaignUpdate,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a campaign (only if draft or paused)."""
    FeyraCampaign = await _get_model("FeyraCampaign")
    result = await db.execute(
        select(FeyraCampaign).where(
            and_(
                FeyraCampaign.id == campaign_id,
                FeyraCampaign.user_id == str(current_user.id),
            )
        )
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    if campaign.status not in (CampaignStatus.DRAFT, CampaignStatus.PAUSED):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Campaign can only be edited when in draft or paused state",
        )

    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(campaign, field, value)
    campaign.updated_at = _now()

    await db.flush()
    await db.refresh(campaign)
    return CampaignResponse.model_validate(campaign)


@router.delete("/campaigns/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_campaign(
    campaign_id: str,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a campaign and its steps."""
    FeyraCampaign = await _get_model("FeyraCampaign")
    result = await db.execute(
        select(FeyraCampaign).where(
            and_(
                FeyraCampaign.id == campaign_id,
                FeyraCampaign.user_id == str(current_user.id),
            )
        )
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    # Delete steps first
    try:
        FeyraCampaignStep = await _get_model("FeyraCampaignStep")
        await db.execute(
            delete(FeyraCampaignStep).where(FeyraCampaignStep.campaign_id == campaign_id)
        )
    except Exception:
        pass

    await db.delete(campaign)
    await db.flush()


@router.post("/campaigns/{campaign_id}/launch", response_model=CampaignResponse)
async def launch_campaign(
    campaign_id: str,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Launch a campaign (start sending)."""
    FeyraCampaign = await _get_model("FeyraCampaign")
    result = await db.execute(
        select(FeyraCampaign).where(
            and_(
                FeyraCampaign.id == campaign_id,
                FeyraCampaign.user_id == str(current_user.id),
            )
        )
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    if campaign.status not in (CampaignStatus.DRAFT, CampaignStatus.PAUSED):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Campaign cannot be launched from current state")

    # Validate that campaign has at least one step and one email account
    try:
        FeyraCampaignStep = await _get_model("FeyraCampaignStep")
        step_count = (await db.execute(
            select(func.count()).select_from(FeyraCampaignStep).where(
                FeyraCampaignStep.campaign_id == campaign_id
            )
        )).scalar() or 0
        if step_count == 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Campaign must have at least one step")
    except HTTPException:
        raise
    except Exception:
        pass

    if not campaign.email_account_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Campaign must have an email account")

    campaign.status = CampaignStatus.ACTIVE
    campaign.send_start_date = _now()
    campaign.updated_at = _now()
    await db.flush()
    await db.refresh(campaign)
    return CampaignResponse.model_validate(campaign)


@router.post("/campaigns/{campaign_id}/pause", response_model=CampaignResponse)
async def pause_campaign(
    campaign_id: str,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Pause an active campaign."""
    FeyraCampaign = await _get_model("FeyraCampaign")
    result = await db.execute(
        select(FeyraCampaign).where(
            and_(
                FeyraCampaign.id == campaign_id,
                FeyraCampaign.user_id == str(current_user.id),
            )
        )
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    if campaign.status != CampaignStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Campaign is not active")

    campaign.status = CampaignStatus.PAUSED
    campaign.updated_at = _now()
    await db.flush()
    await db.refresh(campaign)
    return CampaignResponse.model_validate(campaign)


@router.post("/campaigns/{campaign_id}/resume", response_model=CampaignResponse)
async def resume_campaign(
    campaign_id: str,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Resume a paused campaign."""
    FeyraCampaign = await _get_model("FeyraCampaign")
    result = await db.execute(
        select(FeyraCampaign).where(
            and_(
                FeyraCampaign.id == campaign_id,
                FeyraCampaign.user_id == str(current_user.id),
            )
        )
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    if campaign.status != CampaignStatus.PAUSED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Campaign is not paused")

    campaign.status = CampaignStatus.ACTIVE
    campaign.updated_at = _now()
    await db.flush()
    await db.refresh(campaign)
    return CampaignResponse.model_validate(campaign)


@router.get("/campaigns/{campaign_id}/analytics", response_model=CampaignAnalytics)
async def get_campaign_analytics(
    campaign_id: str,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Get detailed analytics for a campaign."""
    FeyraCampaign = await _get_model("FeyraCampaign")
    result = await db.execute(
        select(FeyraCampaign).where(
            and_(
                FeyraCampaign.id == campaign_id,
                FeyraCampaign.user_id == str(current_user.id),
            )
        )
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    sent = campaign.emails_sent or 0
    opened = campaign.emails_opened or 0
    replied = campaign.replies_received or 0
    bounced = campaign.bounces or 0

    analytics = CampaignAnalytics(
        campaign_id=campaign_id,
        total_leads=campaign.total_leads or 0,
        emails_sent=sent,
        emails_delivered=max(sent - bounced, 0),
        emails_opened=opened,
        unique_opens=opened,  # Placeholder — would come from distinct tracking
        replies_received=replied,
        bounces=bounced,
        open_rate=round(opened / sent * 100, 2) if sent > 0 else 0.0,
        reply_rate=round(replied / sent * 100, 2) if sent > 0 else 0.0,
        bounce_rate=round(bounced / sent * 100, 2) if sent > 0 else 0.0,
    )

    # Step-level stats
    try:
        FeyraCampaignStep = await _get_model("FeyraCampaignStep")
        steps_result = await db.execute(
            select(FeyraCampaignStep)
            .where(FeyraCampaignStep.campaign_id == campaign_id)
            .order_by(FeyraCampaignStep.step_number)
        )
        steps = steps_result.scalars().all()
        analytics.step_stats = [
            {
                "step_id": s.id,
                "step_number": s.step_number,
                "delay_days": s.delay_days,
                "subject_template": s.subject_template,
            }
            for s in steps
        ]
    except Exception:
        pass

    return analytics


@router.get("/campaigns/{campaign_id}/emails", response_model=CampaignEmailListResponse)
async def list_campaign_emails(
    campaign_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """List sent emails for a campaign (paginated)."""
    FeyraCampaign = await _get_model("FeyraCampaign")

    # Verify ownership
    campaign_result = await db.execute(
        select(FeyraCampaign).where(
            and_(
                FeyraCampaign.id == campaign_id,
                FeyraCampaign.user_id == str(current_user.id),
            )
        )
    )
    if not campaign_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    try:
        FeyraCampaignEmail = await _get_model("FeyraCampaignEmail")
        query = select(FeyraCampaignEmail).where(FeyraCampaignEmail.campaign_id == campaign_id)

        count_q = select(func.count()).select_from(query.subquery())
        total = (await db.execute(count_q)).scalar() or 0

        query = query.order_by(FeyraCampaignEmail.sent_at.desc()).offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query)
        items = result.scalars().all()

        return CampaignEmailListResponse(
            items=[CampaignEmailResponse.model_validate(i) for i in items],
            total=total,
            page=page,
            page_size=page_size,
        )
    except Exception:
        return CampaignEmailListResponse(items=[], total=0, page=page, page_size=page_size)


@router.get("/campaigns/{campaign_id}/replies", response_model=CampaignReplyListResponse)
async def list_campaign_replies(
    campaign_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """List replies received for a campaign."""
    FeyraCampaign = await _get_model("FeyraCampaign")

    # Verify ownership
    campaign_result = await db.execute(
        select(FeyraCampaign).where(
            and_(
                FeyraCampaign.id == campaign_id,
                FeyraCampaign.user_id == str(current_user.id),
            )
        )
    )
    if not campaign_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    try:
        FeyraSentEmail = await _get_model("FeyraSentEmail")
        query = select(FeyraSentEmail).where(
            and_(
                FeyraSentEmail.campaign_id == campaign_id,
                FeyraSentEmail.status == SentEmailStatus.REPLIED,
            )
        )

        count_q = select(func.count()).select_from(query.subquery())
        total = (await db.execute(count_q)).scalar() or 0

        query = query.order_by(FeyraSentEmail.replied_at.desc()).offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query)
        items = result.scalars().all()

        return CampaignReplyListResponse(
            items=[CampaignReplyResponse.model_validate(i) for i in items],
            total=total,
            page=page,
            page_size=page_size,
        )
    except Exception:
        return CampaignReplyListResponse(items=[], total=0, page=page, page_size=page_size)


# ---------------------------------------------------------------------------
# Campaign Steps
# ---------------------------------------------------------------------------


@router.post("/campaigns/{campaign_id}/steps", response_model=CampaignStepResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign_step(
    campaign_id: str,
    body: CampaignStepCreate,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a step to a campaign."""
    FeyraCampaign = await _get_model("FeyraCampaign")
    FeyraCampaignStep = await _get_model("FeyraCampaignStep")

    # Verify ownership and state
    campaign_result = await db.execute(
        select(FeyraCampaign).where(
            and_(
                FeyraCampaign.id == campaign_id,
                FeyraCampaign.user_id == str(current_user.id),
            )
        )
    )
    campaign = campaign_result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    if campaign.status not in (CampaignStatus.DRAFT, CampaignStatus.PAUSED):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Steps can only be added to draft or paused campaigns")

    # Determine step_number
    step_number = body.step_number
    max_num = (await db.execute(
        select(func.max(FeyraCampaignStep.step_number)).where(
            FeyraCampaignStep.campaign_id == campaign_id
        )
    )).scalar()
    if step_number <= (max_num or 0):
        step_number = (max_num or 0) + 1

    step = FeyraCampaignStep(
        id=_uuid(),
        campaign_id=campaign_id,
        step_number=step_number,
        delay_days=body.delay_days,
        subject_template=body.subject_template,
        body_template=body.body_template,
        ai_rewrite_enabled=body.ai_rewrite_enabled,
        ai_tone=body.ai_tone,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(step)
    await db.flush()
    await db.refresh(step)
    return CampaignStepResponse.model_validate(step)


@router.patch("/campaigns/{campaign_id}/steps/{step_id}", response_model=CampaignStepResponse)
async def update_campaign_step(
    campaign_id: str,
    step_id: str,
    body: CampaignStepUpdate,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a campaign step."""
    FeyraCampaign = await _get_model("FeyraCampaign")
    FeyraCampaignStep = await _get_model("FeyraCampaignStep")

    # Verify ownership
    campaign_result = await db.execute(
        select(FeyraCampaign).where(
            and_(
                FeyraCampaign.id == campaign_id,
                FeyraCampaign.user_id == str(current_user.id),
            )
        )
    )
    campaign = campaign_result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    if campaign.status not in (CampaignStatus.DRAFT, CampaignStatus.PAUSED):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Steps can only be edited in draft or paused campaigns")

    step_result = await db.execute(
        select(FeyraCampaignStep).where(
            and_(
                FeyraCampaignStep.id == step_id,
                FeyraCampaignStep.campaign_id == campaign_id,
            )
        )
    )
    step = step_result.scalar_one_or_none()
    if not step:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Step not found")

    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(step, field, value)

    await db.flush()
    await db.refresh(step)
    return CampaignStepResponse.model_validate(step)


@router.delete("/campaigns/{campaign_id}/steps/{step_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_campaign_step(
    campaign_id: str,
    step_id: str,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a step from a campaign."""
    FeyraCampaign = await _get_model("FeyraCampaign")
    FeyraCampaignStep = await _get_model("FeyraCampaignStep")

    # Verify ownership
    campaign_result = await db.execute(
        select(FeyraCampaign).where(
            and_(
                FeyraCampaign.id == campaign_id,
                FeyraCampaign.user_id == str(current_user.id),
            )
        )
    )
    campaign = campaign_result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    if campaign.status not in (CampaignStatus.DRAFT, CampaignStatus.PAUSED):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Steps can only be removed from draft or paused campaigns")

    step_result = await db.execute(
        select(FeyraCampaignStep).where(
            and_(
                FeyraCampaignStep.id == step_id,
                FeyraCampaignStep.campaign_id == campaign_id,
            )
        )
    )
    step = step_result.scalar_one_or_none()
    if not step:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Step not found")

    await db.delete(step)
    await db.flush()


@router.post("/campaigns/{campaign_id}/steps/{step_id}/preview")
async def preview_campaign_step(
    campaign_id: str,
    step_id: str,
    lead_id: str | None = Query(None),
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Preview a step with a sample lead's data merged in."""
    FeyraCampaign = await _get_model("FeyraCampaign")
    FeyraCampaignStep = await _get_model("FeyraCampaignStep")

    # Verify ownership
    campaign_result = await db.execute(
        select(FeyraCampaign).where(
            and_(
                FeyraCampaign.id == campaign_id,
                FeyraCampaign.user_id == str(current_user.id),
            )
        )
    )
    if not campaign_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    step_result = await db.execute(
        select(FeyraCampaignStep).where(
            and_(
                FeyraCampaignStep.id == step_id,
                FeyraCampaignStep.campaign_id == campaign_id,
            )
        )
    )
    step = step_result.scalar_one_or_none()
    if not step:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Step not found")

    # Get lead data for merge
    lead_data: dict[str, str] = {
        "first_name": "John",
        "last_name": "Doe",
        "company_name": "Acme Inc",
        "job_title": "CEO",
        "email": "john@example.com",
    }

    if lead_id:
        FeyraLead = await _get_model("FeyraLead")
        lead_result = await db.execute(
            select(FeyraLead).where(
                and_(
                    FeyraLead.id == lead_id,
                    FeyraLead.user_id == str(current_user.id),
                )
            )
        )
        lead = lead_result.scalar_one_or_none()
        if lead:
            lead_data = {
                "first_name": lead.first_name or "",
                "last_name": lead.last_name or "",
                "company_name": lead.company_name or "",
                "job_title": lead.job_title or "",
                "email": lead.email or "",
            }

    # Simple template merge using {{variable}} syntax
    subject = step.subject_template or ""
    body = step.body_template or ""
    for key, val in lead_data.items():
        placeholder = "{{" + key + "}}"
        subject = subject.replace(placeholder, val)
        body = body.replace(placeholder, val)

    return {
        "subject": subject,
        "body": body,
        "lead_data": lead_data,
    }


# ---------------------------------------------------------------------------
# AI Writer
# ---------------------------------------------------------------------------


@router.post("/ai/generate-email", response_model=GenerateEmailResponse)
@limiter.limit("20/minute")
async def generate_email(
    body: GenerateEmailRequest,
    request: Request,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate an email from a prompt and lead data using AI."""
    # Placeholder AI generation — in production, this calls the AI service
    lead_name = body.lead_data.get("first_name", "there")
    company = body.lead_data.get("company", "your company")

    subject = f"Quick question about {company}"
    email_body = (
        f"Hi {lead_name},\n\n"
        f"I hope this message finds you well. {body.prompt}\n\n"
        f"I'd love to discuss how we could help {company} achieve its goals.\n\n"
        f"Would you be open to a brief chat this week?\n\n"
        f"Best regards"
    )

    return GenerateEmailResponse(
        subject=subject,
        body=email_body,
        tokens_used=0,
    )


@router.post("/ai/generate-subject-lines")
@limiter.limit("20/minute")
async def generate_subject_lines(
    body: GenerateSubjectLinesRequest,
    request: Request,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate subject line options for an email."""
    # Placeholder — in production, calls AI service
    lines = [
        f"Subject option {i+1} for your email"
        for i in range(body.count)
    ]
    return {"subject_lines": lines, "tokens_used": 0}


@router.post("/ai/rewrite")
@limiter.limit("20/minute")
async def rewrite_email(
    body: RewriteEmailRequest,
    request: Request,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Rewrite an email with a different tone."""
    # Placeholder — in production, calls AI service
    return {
        "original_text": body.original_text,
        "rewritten_text": body.original_text,  # Placeholder
        "tone": body.tone,
        "tokens_used": 0,
    }


@router.post("/ai/spam-check", response_model=SpamCheckResponse)
@limiter.limit("30/minute")
async def spam_check(
    body: SpamCheckRequest,
    request: Request,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Check email content for spam triggers."""
    issues: list[dict[str, str]] = []
    suggestions: list[str] = []
    score = 0.0

    text = (body.subject + " " + body.body).lower()

    # Simple heuristic spam checks
    spam_words = [
        "free", "winner", "click here", "buy now", "limited time",
        "act now", "urgent", "guaranteed", "no obligation", "risk free",
        "discount", "lowest price", "order now", "special promotion",
    ]
    for word in spam_words:
        if word in text:
            score += 8
            issues.append({"type": "spam_word", "word": word, "severity": "medium"})

    # Check for ALL CAPS
    words = body.subject.split()
    caps_count = sum(1 for w in words if w.isupper() and len(w) > 2)
    if caps_count > 1:
        score += 10
        issues.append({"type": "excessive_caps", "severity": "medium"})
        suggestions.append("Reduce the use of ALL CAPS in subject line")

    # Check for excessive punctuation
    if body.subject.count("!") > 1 or body.subject.count("?") > 2:
        score += 5
        issues.append({"type": "excessive_punctuation", "severity": "low"})
        suggestions.append("Reduce excessive punctuation in subject line")

    # Check body length
    if len(body.body) < 50:
        score += 5
        suggestions.append("Email body is very short; consider adding more content")
    elif len(body.body) > 5000:
        score += 5
        suggestions.append("Email body is very long; consider being more concise")

    if not issues:
        suggestions.append("Email content looks good!")

    score = min(score, 100)

    return SpamCheckResponse(
        score=round(score, 1),
        is_likely_spam=score > 50,
        issues=issues,
        suggestions=suggestions,
    )


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@router.get("/settings", response_model=GlobalSettingsResponse)
async def get_settings(
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the user's global Feyra settings."""
    try:
        FeyraSettings = await _get_model("FeyraSettings")
        result = await db.execute(
            select(FeyraSettings).where(
                FeyraSettings.user_id == str(current_user.id)
            )
        )
        settings_obj = result.scalar_one_or_none()
        if settings_obj:
            return GlobalSettingsResponse.model_validate(settings_obj)
    except Exception:
        pass

    # Return defaults if no settings exist yet
    return GlobalSettingsResponse(
        user_id=str(current_user.id),
    )


@router.patch("/settings", response_model=GlobalSettingsResponse)
async def update_settings(
    body: GlobalSettingsUpdate,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the user's global Feyra settings."""
    FeyraSettings = await _get_model("FeyraSettings")

    result = await db.execute(
        select(FeyraSettings).where(
            FeyraSettings.user_id == str(current_user.id)
        )
    )
    settings_obj = result.scalar_one_or_none()

    if not settings_obj:
        # Create settings record
        settings_obj = FeyraSettings(
            id=_uuid(),
            user_id=str(current_user.id),
            created_at=_now(),
            updated_at=_now(),
        )
        db.add(settings_obj)
        await db.flush()

    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(settings_obj, field, value)
    settings_obj.updated_at = _now()

    await db.flush()
    await db.refresh(settings_obj)
    return GlobalSettingsResponse.model_validate(settings_obj)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@router.get("/dashboard/stats", response_model=DashboardStats)
async def dashboard_stats(
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Get overview statistics for the dashboard."""
    user_id = str(current_user.id)
    stats = DashboardStats()

    # Email accounts
    try:
        FeyraEmailAccount = await _get_model("FeyraEmailAccount")
        acct_result = await db.execute(
            select(FeyraEmailAccount).where(FeyraEmailAccount.user_id == user_id)
        )
        accounts = acct_result.scalars().all()
        stats.total_email_accounts = len(accounts)
        stats.active_warmups = sum(1 for a in accounts if a.warmup_enabled)

        scores = [a.sender_reputation_score for a in accounts if a.sender_reputation_score is not None]
        stats.reputation_score = round(sum(scores) / len(scores), 2) if scores else None
    except Exception:
        pass

    # Leads
    try:
        FeyraLead = await _get_model("FeyraLead")
        total_leads = (await db.execute(
            select(func.count()).select_from(FeyraLead).where(FeyraLead.user_id == user_id)
        )).scalar() or 0
        verified_leads = (await db.execute(
            select(func.count()).select_from(FeyraLead).where(
                and_(FeyraLead.user_id == user_id, FeyraLead.email_verified.is_(True))
            )
        )).scalar() or 0
        stats.total_leads = total_leads
        stats.verified_leads = verified_leads
    except Exception:
        pass

    # Campaigns
    try:
        FeyraCampaign = await _get_model("FeyraCampaign")
        active_campaigns = (await db.execute(
            select(func.count()).select_from(FeyraCampaign).where(
                and_(FeyraCampaign.user_id == user_id, FeyraCampaign.status == CampaignStatus.ACTIVE)
            )
        )).scalar() or 0
        stats.active_campaigns = active_campaigns

        # Email stats from campaigns
        campaign_result = await db.execute(
            select(
                func.coalesce(func.sum(FeyraCampaign.emails_sent), 0),
                func.coalesce(func.sum(FeyraCampaign.emails_opened), 0),
                func.coalesce(func.sum(FeyraCampaign.replies_received), 0),
            ).where(FeyraCampaign.user_id == user_id)
        )
        row = campaign_result.one()
        total_sent = row[0] or 0
        total_opened = row[1] or 0
        total_replied = row[2] or 0
        stats.emails_sent_month = total_sent
        stats.average_open_rate = round(total_opened / total_sent * 100, 2) if total_sent > 0 else 0.0
        stats.average_reply_rate = round(total_replied / total_sent * 100, 2) if total_sent > 0 else 0.0
    except Exception:
        pass

    # Crawl jobs
    try:
        FeyraCrawlJob = await _get_model("FeyraCrawlJob")
        active_crawls = (await db.execute(
            select(func.count()).select_from(FeyraCrawlJob).where(
                and_(
                    FeyraCrawlJob.user_id == user_id,
                    FeyraCrawlJob.status.in_([CrawlJobStatus.PENDING, CrawlJobStatus.RUNNING]),
                )
            )
        )).scalar() or 0
        stats.active_crawl_jobs = active_crawls
    except Exception:
        pass

    return stats


@router.get("/dashboard/activity", response_model=list[ActivityFeedItem])
async def dashboard_activity(
    limit: int = Query(20, ge=1, le=50),
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
):
    """Get recent activity feed for the dashboard."""
    user_id = str(current_user.id)
    items: list[ActivityFeedItem] = []

    # Gather recent activity from various sources
    try:
        FeyraLead = await _get_model("FeyraLead")
        result = await db.execute(
            select(FeyraLead)
            .where(FeyraLead.user_id == user_id)
            .order_by(FeyraLead.created_at.desc())
            .limit(5)
        )
        for lead in result.scalars().all():
            items.append(ActivityFeedItem(
                id=lead.id,
                event_type="lead_created",
                description=f"New lead added: {lead.email}",
                metadata={"lead_id": lead.id, "source": lead.source or "manual"},
                created_at=lead.created_at or _now(),
            ))
    except Exception:
        pass

    try:
        FeyraCampaign = await _get_model("FeyraCampaign")
        result = await db.execute(
            select(FeyraCampaign)
            .where(FeyraCampaign.user_id == user_id)
            .order_by(FeyraCampaign.updated_at.desc())
            .limit(5)
        )
        for campaign in result.scalars().all():
            items.append(ActivityFeedItem(
                id=campaign.id,
                event_type="campaign_updated",
                description=f"Campaign '{campaign.name}' — {campaign.status}",
                metadata={"campaign_id": campaign.id, "status": campaign.status or ""},
                created_at=campaign.updated_at or _now(),
            ))
    except Exception:
        pass

    try:
        FeyraCrawlJob = await _get_model("FeyraCrawlJob")
        result = await db.execute(
            select(FeyraCrawlJob)
            .where(FeyraCrawlJob.user_id == user_id)
            .order_by(FeyraCrawlJob.updated_at.desc())
            .limit(5)
        )
        for job in result.scalars().all():
            items.append(ActivityFeedItem(
                id=job.id,
                event_type="crawl_updated",
                description=f"Crawl '{job.name}' — {job.status} ({job.leads_found or 0} found)",
                metadata={"crawl_id": job.id, "status": job.status or ""},
                created_at=job.updated_at or _now(),
            ))
    except Exception:
        pass

    # Sort by created_at and limit
    items.sort(key=lambda x: x.created_at, reverse=True)
    return items[:limit]
