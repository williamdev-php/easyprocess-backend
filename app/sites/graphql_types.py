from __future__ import annotations

from datetime import datetime

import enum

import strawberry
from strawberry.scalars import JSON


# ---------------------------------------------------------------------------
# Enums (mirrored from models for GraphQL)
# ---------------------------------------------------------------------------

@strawberry.enum
class LeadStatusGQL(enum.Enum):
    NEW = "NEW"
    SCRAPING = "SCRAPING"
    SCRAPED = "SCRAPED"
    GENERATING = "GENERATING"
    GENERATED = "GENERATED"
    EMAIL_SENT = "EMAIL_SENT"
    OPENED = "OPENED"
    REPLIED = "REPLIED"
    CONVERTED = "CONVERTED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


@strawberry.enum
class SiteStatusGQL(enum.Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    PURCHASED = "PURCHASED"
    ARCHIVED = "ARCHIVED"
    PAUSED = "PAUSED"


@strawberry.enum
class EmailStatusGQL(enum.Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    OPENED = "OPENED"
    CLICKED = "CLICKED"
    REPLIED = "REPLIED"
    BOUNCED = "BOUNCED"
    FAILED = "FAILED"


# ---------------------------------------------------------------------------
# Output types
# ---------------------------------------------------------------------------

@strawberry.type
class IndustryType:
    id: str
    name: str
    slug: str
    description: str | None = None
    created_at: datetime
    updated_at: datetime


@strawberry.type
class ScrapedDataType:
    id: str
    logo_url: str | None = None
    colors: JSON | None = None
    texts: JSON | None = None
    images: JSON | None = None
    contact_info: JSON | None = None
    meta_info: JSON | None = None
    created_at: datetime


@strawberry.type
class GeneratedSiteType:
    id: str
    site_data: JSON
    template: str
    status: str
    subdomain: str | None = None
    custom_domain: str | None = None
    views: int = 0
    tokens_used: int | None = None
    ai_model: str | None = None
    generation_cost_usd: float | None = None
    video_url: str | None = None
    published_at: datetime | None = None
    purchased_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    lead_id: str | None = None
    business_name: str | None = None
    website_url: str | None = None


@strawberry.type
class OutreachEmailType:
    id: str
    to_email: str
    subject: str
    status: str
    resend_id: str | None = None
    smartlead_campaign_id: int | None = None
    smartlead_lead_id: int | None = None
    sent_via: str = "resend"
    sent_at: datetime | None = None
    opened_at: datetime | None = None
    clicked_at: datetime | None = None
    replied_at: datetime | None = None
    created_at: datetime


@strawberry.type
class LeadType:
    id: str
    business_name: str | None = None
    website_url: str
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    industry: str | None = None
    industry_id: str | None = None
    industry_name: str | None = None
    source: str
    status: str
    quality_score: float | None = None
    error_message: str | None = None
    scraped_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    scraped_data: ScrapedDataType | None = None
    generated_site: GeneratedSiteType | None = None
    outreach_emails: list[OutreachEmailType] = strawberry.field(default_factory=list)
    inbound_emails: list[InboundEmailType] = strawberry.field(default_factory=list)
    inbound_emails_count: int = 0


@strawberry.type
class LeadListType:
    items: list[LeadType]
    total: int
    page: int
    page_size: int


@strawberry.type
class DashboardStatsType:
    total_leads: int = 0
    leads_new: int = 0
    leads_scraped: int = 0
    leads_generated: int = 0
    leads_email_sent: int = 0
    leads_converted: int = 0
    leads_failed: int = 0
    total_sites: int = 0
    total_emails_sent: int = 0
    total_views: int = 0
    total_ai_cost_usd: float = 0.0
    # Outreach stats
    outreach_sent_30d: int = 0
    outreach_open_rate: float = 0.0
    outreach_reply_rate: float = 0.0
    outreach_conversions_30d: int = 0


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

@strawberry.input
class CreateLeadInput:
    website_url: str
    business_name: str | None = None
    industry: str | None = None
    industry_id: str | None = None

    def __post_init__(self) -> None:
        from urllib.parse import urlparse

        url = self.website_url.strip()
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        parsed = urlparse(url)
        if not parsed.hostname or "." not in parsed.hostname:
            raise ValueError(f"Invalid website URL: {self.website_url}")
        self.website_url = url


@strawberry.input
class UpdateSiteDataInput:
    site_id: str
    site_data: JSON


@strawberry.input
class SaveDraftInput:
    site_id: str
    draft_data: JSON


@strawberry.type
class DraftType:
    site_id: str
    draft_data: JSON
    updated_at: datetime


@strawberry.type
class PublishResult:
    success: bool
    site: GeneratedSiteType


@strawberry.input
class LeadFilterInput:
    status: str | None = None
    industry: str | None = None
    industry_id: str | None = None
    search: str | None = None
    page: int = 1
    page_size: int = 20


# ---------------------------------------------------------------------------
# Inbound Email types
# ---------------------------------------------------------------------------

@strawberry.type
class InboundEmailType:
    id: str
    from_email: str
    from_name: str | None
    to_email: str
    subject: str | None
    body_text: str | None
    body_html: str | None
    category: str
    spam_score: float | None
    ai_summary: str | None
    matched_lead_id: str | None
    is_read: bool
    is_archived: bool
    created_at: str


@strawberry.type
class InboundEmailListType:
    items: list[InboundEmailType]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Analytics types
# ---------------------------------------------------------------------------

@strawberry.type
class DailyVisitorPoint:
    date: str
    visitors: int
    page_views: int


@strawberry.type
class SiteAnalyticsType:
    """Analytics data for a single site, used in user dashboard."""
    total_visitors: int = 0
    total_sessions: int = 0
    total_page_views: int = 0
    pages_per_session: float = 0.0
    avg_load_time_ms: int | None = None
    avg_fcp_ms: int | None = None
    avg_lcp_ms: int | None = None
    avg_cls: float | None = None
    performance_score: int = 0
    visitors_change_pct: float = 0.0
    pages_per_session_prev: float = 0.0
    performance_score_prev: int = 0
    daily: list[DailyVisitorPoint] = strawberry.field(default_factory=list)


# ---------------------------------------------------------------------------
# Inbound Email types (cont.)
# ---------------------------------------------------------------------------

@strawberry.input
class InboundEmailFilterInput:
    category: str | None = None
    to_email: str | None = None
    is_read: bool | None = None
    is_archived: bool | None = None
    search: str | None = None
    page: int = 1
    page_size: int = 20


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------

@strawberry.enum
class DomainStatusGQL(enum.Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    FAILED = "FAILED"


@strawberry.type
class CustomDomainType:
    id: str
    domain: str
    site_id: str | None = None
    status: str
    site_subdomain: str | None = None
    site_business_name: str | None = None
    verified_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    # Vercel verification info — tells the user what DNS records to set
    vercel_verification: JSON | None = None


@strawberry.type
class SubdomainInfoType:
    """Info about the subdomain system."""
    subdomain: str | None = None
    full_url: str | None = None
    base_domain: str = ""


@strawberry.input
class AddDomainInput:
    domain: str
    site_id: str | None = None


@strawberry.input
class AssignDomainInput:
    domain_id: str
    site_id: str


# ---------------------------------------------------------------------------
# Domain purchase types
# ---------------------------------------------------------------------------

@strawberry.type
class DomainSearchResult:
    """Result of a domain availability check."""
    available: bool
    domain: str
    price_sek: int = 0  # öre
    price_sek_display: int = 0  # whole SEK for display
    price_usd: float = 0.0
    period: int = 1  # years


@strawberry.type
class DomainPurchaseType:
    """A domain purchased through the platform."""
    id: str
    domain: str
    price_sek: int  # öre
    status: str
    period_years: int
    auto_renew: bool = True
    is_locked: bool = True
    expires_at: datetime | None = None
    purchased_at: datetime | None = None
    created_at: datetime


@strawberry.type
class DomainTransferInfoType:
    """Transfer info for moving a domain to another registrar."""
    domain: str
    is_locked: bool
    auth_code: str | None = None
    instructions: str = ""


@strawberry.type
class SiteVersionType:
    id: str
    site_id: str
    version_number: int
    site_data: JSON
    label: str | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Smartlead / Outreach types
# ---------------------------------------------------------------------------

@strawberry.type
class OutreachStatsType:
    """Outreach statistics for the admin dashboard."""
    emails_sent_30d: int = 0
    open_rate: float = 0.0
    reply_rate: float = 0.0
    click_rate: float = 0.0
    bounce_rate: float = 0.0
    conversions_30d: int = 0
    daily_send_count: int = 0
    daily_send_limit: int = 0
    warmup_status: str = "not_configured"
    warmup_day: int = 0
    warmup_days_target: int = 14


@strawberry.type
class AdminSiteType:
    """Site with owner info for admin views."""
    id: str
    site_data: JSON
    template: str
    status: str
    subdomain: str | None = None
    custom_domain: str | None = None
    views: int = 0
    tokens_used: int | None = None
    ai_model: str | None = None
    generation_cost_usd: float | None = None
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    lead_id: str | None = None
    business_name: str | None = None
    website_url: str | None = None
    # Owner info
    owner_id: str | None = None
    owner_email: str | None = None
    owner_name: str | None = None
    is_lead_site: bool = False


@strawberry.type
class AdminSiteListType:
    items: list[AdminSiteType]
    total: int
    page: int
    page_size: int


@strawberry.input
class AdminSiteFilterInput:
    search: str | None = None
    status: str | None = None
    is_lead_site: bool | None = None
    page: int = 1
    page_size: int = 20


@strawberry.input
class CreateIndustryInput:
    name: str
    description: str | None = None


@strawberry.input
class UpdateIndustryInput:
    id: str
    name: str | None = None
    description: str | None = None


@strawberry.type
class SmartleadMessageType:
    """A message from Smartlead message history (sent or reply)."""
    id: str
    type: str  # "sent" | "reply"
    subject: str | None = None
    body: str | None = None
    from_email: str = ""
    to_email: str = ""
    timestamp: datetime | None = None
    status: str | None = None
