"""Feyra schemas — auth re-exports + all API request/response models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---- Auth re-exports (Pydantic-only schemas shared with Qvicko) ----------
from app.auth.schemas import (
    ChangePasswordRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    SessionResponse,
    TokenResponse,
    UpdateProfileRequest,
    UserLogin,
    UserRegister,
)


class FeyraUserResponse(BaseModel):
    """User response tailored to FeyraUser fields (no Qvicko billing/stripe)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    full_name: str
    company_name: str | None = None
    org_number: str | None = None
    phone: str | None = None
    avatar_url: str | None = None
    locale: str = "sv"
    is_active: bool = True
    is_verified: bool = False
    last_login_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


__all__ = [
    "ChangePasswordRequest",
    "FeyraUserResponse",
    "PasswordResetConfirm",
    "PasswordResetRequest",
    "SessionResponse",
    "TokenResponse",
    "UpdateProfileRequest",
    "UserLogin",
    "UserRegister",
]

# ---------------------------------------------------------------------------
# Email Accounts
# ---------------------------------------------------------------------------


class EmailAccountCreate(BaseModel):
    email_address: str
    display_name: str | None = None
    imap_host: str | None = None
    imap_port: int | None = None
    imap_username: str | None = None
    imap_password: str | None = None
    imap_use_ssl: bool = True
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True


class EmailAccountUpdate(BaseModel):
    display_name: str | None = None
    imap_host: str | None = None
    imap_port: int | None = None
    imap_username: str | None = None
    imap_password: str | None = None
    imap_use_ssl: bool | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool | None = None
    daily_send_limit: int | None = None


class EmailAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    email_address: str
    display_name: str | None = None
    provider: str | None = None
    imap_host: str | None = None
    imap_port: int | None = None
    imap_use_ssl: bool = True
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_use_tls: bool = True
    connection_status: str | None = None
    warmup_enabled: bool = False
    daily_send_limit: int | None = None
    sender_reputation_score: int | None = None
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class WarmupStatsResponse(BaseModel):
    current_day: int = 0
    status: str | None = None
    emails_sent_today: int = 0
    emails_received_today: int = 0
    sender_reputation_score: int | None = None
    spam_rate: float | None = None
    delivery_rate: float | None = None
    total_sent: int = 0
    total_received: int = 0


class EmailAccountDetail(EmailAccountResponse):
    warmup_stats: WarmupStatsResponse | None = None
    emails_sent_today: int = 0
    emails_received_today: int = 0


class ConnectionTestResponse(BaseModel):
    imap_ok: bool = False
    smtp_ok: bool = False
    imap_message: str = ""
    smtp_message: str = ""


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------


class LeadCreate(BaseModel):
    email: str
    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    company_name: str | None = None
    job_title: str | None = None
    company_domain: str | None = None
    company_size: str | None = None
    industry: str | None = None
    phone: str | None = None
    website_url: str | None = None
    linkedin_url: str | None = None
    location: str | None = None
    country: str | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None


class LeadUpdate(BaseModel):
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    company_name: str | None = None
    job_title: str | None = None
    company_domain: str | None = None
    company_size: str | None = None
    industry: str | None = None
    phone: str | None = None
    website_url: str | None = None
    linkedin_url: str | None = None
    location: str | None = None
    country: str | None = None
    status: str | None = None
    tags: list[str] | None = None
    lead_score: int | None = None
    notes: str | None = None


class LeadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    email: str
    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    job_title: str | None = None
    company_name: str | None = None
    company_domain: str | None = None
    company_size: str | None = None
    industry: str | None = None
    phone: str | None = None
    website_url: str | None = None
    linkedin_url: str | None = None
    location: str | None = None
    country: str | None = None
    status: str | None = None
    source: str | None = None
    source_url: str | None = None
    tags: list[str] = Field(default_factory=list)
    lead_score: int | None = None
    email_verified: bool = False
    email_verification_status: str | None = None
    notes: str | None = None
    last_contacted_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class LeadListResponse(BaseModel):
    items: list[LeadResponse]
    total: int
    page: int
    page_size: int


class LeadImportRequest(BaseModel):
    column_mapping: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of CSV column names to lead fields",
    )
    tags: list[str] = Field(default_factory=list)


class BulkActionRequest(BaseModel):
    lead_ids: list[str]
    action: str = Field(description="Action: delete, tag, untag, update_status, verify")
    params: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Crawl Jobs
# ---------------------------------------------------------------------------


class CrawlJobCreate(BaseModel):
    name: str
    crawl_type: str = Field(default="WEBSITE", description="WEBSITE, GOOGLE_SEARCH, LINKEDIN_SEARCH")
    seed_urls: list[str] = Field(default_factory=list)
    target_domains: list[str] = Field(default_factory=list)
    max_pages: int = Field(default=100, ge=1, le=10000)
    max_depth: int = Field(default=3, ge=1, le=10)
    search_query: str | None = None
    icp_description: str | None = None


class CrawlJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    name: str
    crawl_type: str | None = None
    status: str | None = None
    seed_urls: list[str] = Field(default_factory=list)
    target_domains: list[str] = Field(default_factory=list)
    max_pages: int = 100
    max_depth: int = 3
    search_query: str | None = None
    icp_description: str | None = None
    pages_crawled: int = 0
    leads_found: int = 0
    emails_found: int = 0
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CrawlJobDetail(CrawlJobResponse):
    progress_percent: float = 0.0


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------


class CampaignStepCreate(BaseModel):
    step_number: int
    delay_days: int = 0
    subject_template: str | None = None
    body_template: str | None = None
    ai_rewrite_enabled: bool = False
    ai_tone: str | None = None


class CampaignStepUpdate(BaseModel):
    step_number: int | None = None
    delay_days: int | None = None
    subject_template: str | None = None
    body_template: str | None = None
    ai_rewrite_enabled: bool | None = None
    ai_tone: str | None = None


class CampaignStepResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    campaign_id: str
    step_number: int = 0
    delay_days: int = 0
    subject_template: str | None = None
    body_template: str | None = None
    ai_rewrite_enabled: bool = False
    ai_tone: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CampaignCreate(BaseModel):
    name: str
    description: str | None = None
    email_account_id: str
    daily_send_limit: int | None = Field(default=None, ge=1, le=500)
    schedule_start_hour: int | None = None
    schedule_end_hour: int | None = None
    schedule_timezone: str | None = None
    days_active: list[str] | None = None
    delay_between_emails_min_seconds: int = 60
    delay_between_emails_max_seconds: int = 300
    stop_on_reply: bool = True
    track_opens: bool = True
    steps: list[CampaignStepCreate] = Field(default_factory=list)


class CampaignUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    email_account_id: str | None = None
    daily_send_limit: int | None = None
    schedule_start_hour: int | None = None
    schedule_end_hour: int | None = None
    schedule_timezone: str | None = None
    days_active: list[str] | None = None
    delay_between_emails_min_seconds: int | None = None
    delay_between_emails_max_seconds: int | None = None
    stop_on_reply: bool | None = None
    track_opens: bool | None = None


class CampaignResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    name: str
    description: str | None = None
    status: str | None = None
    email_account_id: str
    daily_send_limit: int | None = None
    schedule_start_hour: int | None = None
    schedule_end_hour: int | None = None
    schedule_timezone: str | None = None
    days_active: list[str] | None = None
    delay_between_emails_min_seconds: int = 60
    delay_between_emails_max_seconds: int = 300
    stop_on_reply: bool = True
    track_opens: bool = True
    total_leads: int = 0
    emails_sent: int = 0
    emails_opened: int = 0
    replies_received: int = 0
    bounces: int = 0
    send_start_date: datetime | None = None
    send_end_date: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CampaignDetail(CampaignResponse):
    steps: list[CampaignStepResponse] = Field(default_factory=list)


class CampaignAnalytics(BaseModel):
    campaign_id: str
    total_leads: int = 0
    emails_sent: int = 0
    emails_delivered: int = 0
    emails_opened: int = 0
    unique_opens: int = 0
    replies_received: int = 0
    bounces: int = 0
    open_rate: float = 0.0
    reply_rate: float = 0.0
    bounce_rate: float = 0.0
    daily_stats: list[dict[str, Any]] = Field(default_factory=list)
    step_stats: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# AI Writer
# ---------------------------------------------------------------------------


class GenerateEmailRequest(BaseModel):
    prompt: str
    lead_data: dict[str, Any] = Field(default_factory=dict)
    tone: str = Field(default="professional", description="professional, casual, friendly, formal, humorous")
    language: str = "en"
    max_length: int | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class GenerateEmailResponse(BaseModel):
    subject: str
    body: str
    tokens_used: int = 0


class GenerateSubjectLinesRequest(BaseModel):
    email_body: str
    count: int = Field(default=5, ge=1, le=20)
    tone: str = "professional"
    language: str = "en"


class RewriteEmailRequest(BaseModel):
    original_text: str
    tone: str = Field(description="Target tone: professional, casual, friendly, formal, humorous")
    instructions: str | None = None
    language: str = "en"


class SpamCheckRequest(BaseModel):
    subject: str
    body: str
    from_name: str | None = None


class SpamCheckResponse(BaseModel):
    score: float = Field(description="Spam score 0-100 (lower is better)")
    is_likely_spam: bool = False
    issues: list[dict[str, Any]] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class GlobalSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str | None = None
    user_id: str | None = None
    default_timezone: str = "Europe/Stockholm"
    default_sending_hours_start: int = 8
    default_sending_hours_end: int = 18
    unsubscribe_text: str | None = None
    company_signature: str | None = None
    ai_model_preference: str | None = None
    ai_default_tone: str | None = None
    ai_default_language: str = "en"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class GlobalSettingsUpdate(BaseModel):
    default_timezone: str | None = None
    default_sending_hours_start: int | None = None
    default_sending_hours_end: int | None = None
    unsubscribe_text: str | None = None
    company_signature: str | None = None
    ai_model_preference: str | None = None
    ai_default_tone: str | None = None
    ai_default_language: str | None = None


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


class DashboardStats(BaseModel):
    total_email_accounts: int = 0
    active_warmups: int = 0
    total_leads: int = 0
    verified_leads: int = 0
    active_campaigns: int = 0
    emails_sent_today: int = 0
    emails_sent_week: int = 0
    emails_sent_month: int = 0
    average_open_rate: float = 0.0
    average_reply_rate: float = 0.0
    reputation_score: float | None = None
    active_crawl_jobs: int = 0


class ActivityFeedItem(BaseModel):
    id: str
    event_type: str
    description: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


# ---------------------------------------------------------------------------
# Warmup dashboard
# ---------------------------------------------------------------------------


class WarmupDashboardResponse(BaseModel):
    total_accounts: int = 0
    active_warmups: int = 0
    paused_warmups: int = 0
    average_reputation: float | None = None
    total_sent_today: int = 0
    total_received_today: int = 0
    accounts: list[EmailAccountResponse] = Field(default_factory=list)


class WarmupEmailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    from_account_id: str
    to_account_id: str
    direction: str | None = None
    subject: str | None = None
    body_text: str | None = None
    message_id: str | None = None
    in_reply_to: str | None = None
    status: str | None = None
    landed_in_spam: bool = False
    rescued_from_spam: bool = False
    sent_at: datetime | None = None
    opened_at: datetime | None = None
    replied_at: datetime | None = None
    created_at: datetime | None = None


class WarmupEmailListResponse(BaseModel):
    items: list[WarmupEmailResponse]
    total: int
    page: int
    page_size: int


class CampaignEmailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    campaign_id: str
    campaign_lead_id: str
    email_account_id: str
    step_number: int
    to_email: str
    subject: str
    body_html: str | None = None
    body_text: str | None = None
    message_id: str | None = None
    status: str | None = None
    opened_at: datetime | None = None
    replied_at: datetime | None = None
    bounced_at: datetime | None = None
    sent_at: datetime | None = None
    created_at: datetime | None = None


class CampaignEmailListResponse(BaseModel):
    items: list[CampaignEmailResponse]
    total: int
    page: int
    page_size: int


class CampaignReplyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    campaign_id: str
    campaign_lead_id: str
    email_account_id: str
    to_email: str
    subject: str
    status: str | None = None
    replied_at: datetime | None = None
    sent_at: datetime | None = None
    created_at: datetime | None = None


class CampaignReplyListResponse(BaseModel):
    items: list[CampaignReplyResponse]
    total: int
    page: int
    page_size: int
