from __future__ import annotations

from datetime import datetime

import enum

import strawberry
from strawberry.scalars import JSON

from app.graphql.pagination import PaginatedListType, PaginationInput


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

@strawberry.type(description="An industry category used for site generation templates.")
class IndustryType:
    id: str = strawberry.field(description="Unique industry identifier.")
    name: str = strawberry.field(description="Display name of the industry.")
    slug: str = strawberry.field(description="URL-friendly slug.")
    description: str | None = strawberry.field(default=None, description="Optional industry description.")
    prompt_hint: str | None = strawberry.field(default=None, description="AI prompt hint for generation.")
    default_sections: JSON | None = strawberry.field(default=None, description="Default page sections for this industry.")
    created_at: datetime = strawberry.field(description="Creation timestamp.")
    updated_at: datetime = strawberry.field(description="Last update timestamp.")


@strawberry.type(description="Data scraped from a lead's website.")
class ScrapedDataType:
    id: str = strawberry.field(description="Unique identifier.")
    logo_url: str | None = strawberry.field(default=None, description="Detected logo URL.")
    colors: JSON | None = strawberry.field(default=None, description="Extracted color palette.")
    texts: JSON | None = strawberry.field(default=None, description="Extracted text content.")
    images: JSON | None = strawberry.field(default=None, description="Extracted image URLs.")
    contact_info: JSON | None = strawberry.field(default=None, description="Extracted contact information.")
    meta_info: JSON | None = strawberry.field(default=None, description="Page meta tags and SEO info.")
    created_at: datetime = strawberry.field(description="When the scrape was performed.")


@strawberry.type(description="An AI-generated website.")
class GeneratedSiteType:
    id: str = strawberry.field(description="Unique site identifier.")
    site_data: JSON = strawberry.field(description="Full site content and configuration as JSON.")
    template: str = strawberry.field(description="Template used for generation.")
    status: str = strawberry.field(description="Current site status (DRAFT, PUBLISHED, etc.).")
    subdomain: str | None = strawberry.field(default=None, description="Assigned subdomain.")
    custom_domain: str | None = strawberry.field(default=None, description="Custom domain if configured.")
    views: int = strawberry.field(default=0, description="Total page view count.")
    tokens_used: int | None = strawberry.field(default=None, description="Total AI tokens consumed.")
    input_tokens: int | None = strawberry.field(default=None, description="AI input tokens used.")
    output_tokens: int | None = strawberry.field(default=None, description="AI output tokens used.")
    ai_model: str | None = strawberry.field(default=None, description="AI model used for generation.")
    generation_cost_usd: float | None = strawberry.field(default=None, description="Generation cost in USD.")
    video_url: str | None = strawberry.field(default=None, description="Preview video URL.")
    published_at: datetime | None = strawberry.field(default=None, description="When the site was published.")
    purchased_at: datetime | None = strawberry.field(default=None, description="When the site was purchased.")
    created_at: datetime = strawberry.field(description="Creation timestamp.")
    updated_at: datetime = strawberry.field(description="Last update timestamp.")
    lead_id: str | None = strawberry.field(default=None, description="Associated lead identifier.")
    business_name: str | None = strawberry.field(default=None, description="Business name from the lead.")
    website_url: str | None = strawberry.field(default=None, description="Original website URL.")


@strawberry.type(description="An outreach email sent to a lead.")
class OutreachEmailType:
    id: str = strawberry.field(description="Unique identifier for the outreach email.")
    to_email: str = strawberry.field(description="Recipient email address.")
    subject: str = strawberry.field(description="Email subject line.")
    status: str = strawberry.field(description="Current delivery status.")
    resend_id: str | None = strawberry.field(default=None, description="Resend service message ID.")
    smartlead_campaign_id: int | None = strawberry.field(default=None, description="Smartlead campaign identifier.")
    smartlead_lead_id: int | None = strawberry.field(default=None, description="Smartlead lead identifier.")
    sent_via: str = strawberry.field(default="resend", description="Delivery provider (e.g. resend, smartlead).")
    sent_at: datetime | None = strawberry.field(default=None, description="When the email was sent.")
    opened_at: datetime | None = strawberry.field(default=None, description="When the email was first opened.")
    clicked_at: datetime | None = strawberry.field(default=None, description="When a link was clicked.")
    replied_at: datetime | None = strawberry.field(default=None, description="When the recipient replied.")
    created_at: datetime = strawberry.field(description="Creation timestamp.")


@strawberry.type(description="A business lead for site generation and outreach.")
class LeadType:
    id: str = strawberry.field(description="Unique lead identifier.")
    business_name: str | None = strawberry.field(default=None, description="Name of the business.")
    website_url: str = strawberry.field(description="The business website URL.")
    email: str | None = strawberry.field(default=None, description="Contact email address.")
    phone: str | None = strawberry.field(default=None, description="Contact phone number.")
    address: str | None = strawberry.field(default=None, description="Business address.")
    industry: str | None = strawberry.field(default=None, description="Industry category string.")
    industry_id: str | None = strawberry.field(default=None, description="Industry identifier.")
    industry_name: str | None = strawberry.field(default=None, description="Resolved industry display name.")
    source: str = strawberry.field(description="How the lead was created (e.g. manual, import).")
    status: str = strawberry.field(description="Current pipeline status.")
    quality_score: float | None = strawberry.field(default=None, description="AI-assigned quality score (0-1).")
    error_message: str | None = strawberry.field(default=None, description="Error message if processing failed.")
    scraped_at: datetime | None = strawberry.field(default=None, description="When the website was scraped.")
    created_at: datetime = strawberry.field(description="Creation timestamp.")
    updated_at: datetime = strawberry.field(description="Last update timestamp.")

    scraped_data: ScrapedDataType | None = strawberry.field(default=None, description="Scraped website data.")
    generated_site: GeneratedSiteType | None = strawberry.field(default=None, description="Generated site if available.")
    outreach_emails: list[OutreachEmailType] = strawberry.field(default_factory=list, description="Outreach emails sent for this lead.")
    inbound_emails: list[InboundEmailType] = strawberry.field(default_factory=list, description="Inbound email replies.")
    inbound_emails_count: int = strawberry.field(default=0, description="Total count of inbound emails.")


@strawberry.type
class LeadListType(PaginatedListType):
    items: list[LeadType]


@strawberry.type(description="Aggregated dashboard statistics.")
class DashboardStatsType:
    total_leads: int = strawberry.field(default=0, description="Total number of leads.")
    leads_new: int = strawberry.field(default=0, description="Leads in NEW status.")
    leads_scraped: int = strawberry.field(default=0, description="Leads in SCRAPED status.")
    leads_generated: int = strawberry.field(default=0, description="Leads with generated sites.")
    leads_email_sent: int = strawberry.field(default=0, description="Leads with outreach emails sent.")
    leads_converted: int = strawberry.field(default=0, description="Leads that converted.")
    leads_failed: int = strawberry.field(default=0, description="Leads that failed processing.")
    total_sites: int = strawberry.field(default=0, description="Total generated sites.")
    total_emails_sent: int = strawberry.field(default=0, description="Total outreach emails sent.")
    total_views: int = strawberry.field(default=0, description="Aggregate page views across all sites.")
    total_ai_cost_usd: float = strawberry.field(default=0.0, description="Total AI generation cost in USD.")
    # Outreach stats
    outreach_sent_30d: int = strawberry.field(default=0, description="Outreach emails sent in the last 30 days.")
    outreach_open_rate: float = strawberry.field(default=0.0, description="Outreach email open rate (0-1).")
    outreach_reply_rate: float = strawberry.field(default=0.0, description="Outreach email reply rate (0-1).")
    outreach_conversions_30d: int = strawberry.field(default=0, description="Lead conversions in the last 30 days.")


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

_MAX_URL_LENGTH = 2048
_MAX_SHORT_STRING = 255
_MAX_SEARCH_STRING = 200
_MAX_DOMAIN_LENGTH = 253
_MAX_ID_LENGTH = 64


def _validate_max_length(value: str | None, max_len: int, field_name: str) -> None:
    """Raise ValueError if *value* exceeds *max_len*."""
    if value is not None and len(value) > max_len:
        raise ValueError(f"{field_name} must be at most {max_len} characters (got {len(value)})")


@strawberry.input(description="Input for creating a new lead.")
class CreateLeadInput:
    website_url: str = strawberry.field(description="Website URL of the business.")
    business_name: str | None = strawberry.field(default=None, description="Optional business name override.")
    industry: str | None = strawberry.field(default=None, description="Optional industry classification.")
    industry_id: str | None = strawberry.field(default=None, description="Optional industry record ID.")

    def __post_init__(self) -> None:
        from urllib.parse import urlparse

        _validate_max_length(self.website_url, _MAX_URL_LENGTH, "website_url")
        _validate_max_length(self.business_name, _MAX_SHORT_STRING, "business_name")
        _validate_max_length(self.industry, _MAX_SHORT_STRING, "industry")
        _validate_max_length(self.industry_id, _MAX_ID_LENGTH, "industry_id")

        url = self.website_url.strip()
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        parsed = urlparse(url)
        if not parsed.hostname or "." not in parsed.hostname:
            raise ValueError(f"Invalid website URL: {self.website_url}")
        self.website_url = url


@strawberry.input(description="Input for updating site content data.")
class UpdateSiteDataInput:
    site_id: str = strawberry.field(description="ID of the site to update.")
    site_data: JSON = strawberry.field(description="New site content and configuration (JSON).")

    def __post_init__(self) -> None:
        _validate_max_length(self.site_id, _MAX_ID_LENGTH, "site_id")


@strawberry.input(description="Input for saving a site draft.")
class SaveDraftInput:
    site_id: str = strawberry.field(description="ID of the site to save a draft for.")
    draft_data: JSON = strawberry.field(description="Draft content data (JSON).")

    def __post_init__(self) -> None:
        _validate_max_length(self.site_id, _MAX_ID_LENGTH, "site_id")


@strawberry.type(description="A saved site draft.")
class DraftType:
    site_id: str = strawberry.field(description="ID of the site this draft belongs to.")
    draft_data: JSON = strawberry.field(description="Saved draft content (JSON).")
    updated_at: datetime = strawberry.field(description="When the draft was last saved.")


@strawberry.type(description="Result of a site publish operation.")
class PublishResult:
    success: bool = strawberry.field(description="Whether the publish succeeded.")
    site: GeneratedSiteType = strawberry.field(description="The published site.")


@strawberry.input(description="Filter and pagination input for listing leads.")
class LeadFilterInput(PaginationInput):
    status: str | None = strawberry.field(default=None, description="Filter by lead status.")
    industry: str | None = strawberry.field(default=None, description="Filter by industry string.")
    industry_id: str | None = strawberry.field(default=None, description="Filter by industry record ID.")
    search: str | None = strawberry.field(default=None, description="Free-text search across business name and URL.")

    def __post_init__(self) -> None:
        _validate_max_length(self.status, _MAX_SHORT_STRING, "status")
        _validate_max_length(self.industry, _MAX_SHORT_STRING, "industry")
        _validate_max_length(self.industry_id, _MAX_ID_LENGTH, "industry_id")
        _validate_max_length(self.search, _MAX_SEARCH_STRING, "search")


# ---------------------------------------------------------------------------
# Inbound Email types
# ---------------------------------------------------------------------------

@strawberry.type(description="An inbound email received in reply to outreach.")
class InboundEmailType:
    id: str = strawberry.field(description="Unique identifier.")
    from_email: str = strawberry.field(description="Sender email address.")
    from_name: str | None = strawberry.field(description="Sender display name.")
    to_email: str = strawberry.field(description="Recipient email address.")
    subject: str | None = strawberry.field(description="Email subject line.")
    body_text: str | None = strawberry.field(description="Plain-text email body.")
    body_html: str | None = strawberry.field(description="HTML email body.")
    category: str = strawberry.field(description="Email category (e.g. interested, unsubscribe).")
    spam_score: float | None = strawberry.field(description="Spam score from the mail provider.")
    ai_summary: str | None = strawberry.field(description="AI-generated summary of the email.")
    matched_lead_id: str | None = strawberry.field(description="ID of the matched lead.")
    is_read: bool = strawberry.field(description="Whether the email has been read.")
    is_archived: bool = strawberry.field(description="Whether the email is archived.")
    created_at: str = strawberry.field(description="When the email was received.")


@strawberry.type
class InboundEmailListType(PaginatedListType):
    items: list[InboundEmailType]


# ---------------------------------------------------------------------------
# Analytics types
# ---------------------------------------------------------------------------

@strawberry.type(description="A single day's visitor and page-view counts.")
class DailyVisitorPoint:
    date: str = strawberry.field(description="Date string (YYYY-MM-DD).")
    visitors: int = strawberry.field(description="Unique visitors on this date.")
    page_views: int = strawberry.field(description="Total page views on this date.")


@strawberry.type
class SiteAnalyticsType:
    """Analytics data for a single site, used in user dashboard."""
    total_visitors: int = strawberry.field(default=0, description="Total unique visitors.")
    total_sessions: int = strawberry.field(default=0, description="Total sessions.")
    total_page_views: int = strawberry.field(default=0, description="Total page views.")
    pages_per_session: float = strawberry.field(default=0.0, description="Average pages per session.")
    avg_load_time_ms: int | None = strawberry.field(default=None, description="Average page load time in ms.")
    avg_fcp_ms: int | None = strawberry.field(default=None, description="Average First Contentful Paint in ms.")
    avg_lcp_ms: int | None = strawberry.field(default=None, description="Average Largest Contentful Paint in ms.")
    avg_cls: float | None = strawberry.field(default=None, description="Average Cumulative Layout Shift score.")
    performance_score: int = strawberry.field(default=0, description="Overall performance score (0-100).")
    visitors_change_pct: float = strawberry.field(default=0.0, description="Visitor change percentage vs. previous period.")
    pages_per_session_prev: float = strawberry.field(default=0.0, description="Pages per session in the previous period.")
    performance_score_prev: int = strawberry.field(default=0, description="Performance score in the previous period.")
    daily: list[DailyVisitorPoint] = strawberry.field(default_factory=list, description="Daily visitor data points.")


# ---------------------------------------------------------------------------
# Inbound Email types (cont.)
# ---------------------------------------------------------------------------

@strawberry.input(description="Filter and pagination input for listing inbound emails.")
class InboundEmailFilterInput(PaginationInput):
    category: str | None = strawberry.field(default=None, description="Filter by email category.")
    to_email: str | None = strawberry.field(default=None, description="Filter by recipient email.")
    is_read: bool | None = strawberry.field(default=None, description="Filter by read status.")
    is_archived: bool | None = strawberry.field(default=None, description="Filter by archived status.")
    search: str | None = strawberry.field(default=None, description="Free-text search across subject and body.")

    def __post_init__(self) -> None:
        _validate_max_length(self.category, _MAX_SHORT_STRING, "category")
        _validate_max_length(self.to_email, _MAX_SHORT_STRING, "to_email")
        _validate_max_length(self.search, _MAX_SEARCH_STRING, "search")


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------

@strawberry.enum
class DomainStatusGQL(enum.Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    FAILED = "FAILED"


@strawberry.type(description="A custom domain attached to a site.")
class CustomDomainType:
    id: str = strawberry.field(description="Unique identifier.")
    domain: str = strawberry.field(description="The custom domain name.")
    site_id: str | None = strawberry.field(default=None, description="ID of the assigned site.")
    status: str = strawberry.field(description="Verification status (PENDING, ACTIVE, FAILED).")
    site_subdomain: str | None = strawberry.field(default=None, description="Subdomain of the assigned site.")
    site_business_name: str | None = strawberry.field(default=None, description="Business name of the assigned site.")
    verified_at: datetime | None = strawberry.field(default=None, description="When the domain was verified.")
    created_at: datetime = strawberry.field(description="When the domain was added.")
    updated_at: datetime = strawberry.field(description="When the domain was last updated.")
    # Vercel verification info — tells the user what DNS records to set
    vercel_verification: JSON | None = strawberry.field(default=None, description="Vercel DNS verification records to configure.")


@strawberry.type
class SubdomainInfoType:
    """Info about the subdomain system."""
    subdomain: str | None = strawberry.field(default=None, description="The assigned subdomain.")
    full_url: str | None = strawberry.field(default=None, description="Full URL including the base domain.")
    base_domain: str = strawberry.field(default="", description="Base domain used for subdomains.")


@strawberry.input(description="Input for adding a custom domain.")
class AddDomainInput:
    domain: str = strawberry.field(description="The custom domain to add (e.g. example.com).")
    site_id: str | None = strawberry.field(default=None, description="Optional site ID to assign the domain to immediately.")

    def __post_init__(self) -> None:
        _validate_max_length(self.domain, _MAX_DOMAIN_LENGTH, "domain")
        _validate_max_length(self.site_id, _MAX_ID_LENGTH, "site_id")


@strawberry.input(description="Input for assigning a domain to a site.")
class AssignDomainInput:
    domain_id: str = strawberry.field(description="ID of the domain record.")
    site_id: str = strawberry.field(description="ID of the site to assign the domain to.")

    def __post_init__(self) -> None:
        _validate_max_length(self.domain_id, _MAX_ID_LENGTH, "domain_id")
        _validate_max_length(self.site_id, _MAX_ID_LENGTH, "site_id")


# ---------------------------------------------------------------------------
# Domain purchase types
# ---------------------------------------------------------------------------

@strawberry.type
class DomainSearchResult:
    """Result of a domain availability check."""
    available: bool = strawberry.field(description="Whether the domain is available for purchase.")
    domain: str = strawberry.field(description="The queried domain name.")
    price_sek: int = strawberry.field(default=0, description="Price in SEK ore (smallest unit).")
    price_sek_display: int = strawberry.field(default=0, description="Price in whole SEK for display.")
    price_usd: float = strawberry.field(default=0.0, description="Price in USD.")
    period: int = strawberry.field(default=1, description="Registration period in years.")


@strawberry.type
class DomainPurchaseType:
    """A domain purchased through the platform."""
    id: str = strawberry.field(description="Unique identifier for the purchase.")
    domain: str = strawberry.field(description="The purchased domain name.")
    price_sek: int = strawberry.field(description="Purchase price in SEK ore.")
    status: str = strawberry.field(description="Purchase status (pending, active, expired).")
    period_years: int = strawberry.field(description="Registration period in years.")
    auto_renew: bool = strawberry.field(default=True, description="Whether the domain auto-renews.")
    is_locked: bool = strawberry.field(default=True, description="Whether the transfer lock is enabled.")
    expires_at: datetime | None = strawberry.field(default=None, description="Domain expiration date.")
    purchased_at: datetime | None = strawberry.field(default=None, description="When the domain was purchased.")
    created_at: datetime = strawberry.field(description="When the purchase record was created.")


@strawberry.type
class DomainTransferInfoType:
    """Transfer info for moving a domain to another registrar."""
    domain: str = strawberry.field(description="The domain to transfer.")
    is_locked: bool = strawberry.field(description="Whether the transfer lock is enabled.")
    auth_code: str | None = strawberry.field(default=None, description="Authorization/EPP code for transfer.")
    instructions: str = strawberry.field(default="", description="Human-readable transfer instructions.")


@strawberry.type(description="A versioned snapshot of a site.")
class SiteVersionType:
    id: str = strawberry.field(description="Unique identifier for the version.")
    site_id: str = strawberry.field(description="ID of the site this version belongs to.")
    version_number: int = strawberry.field(description="Sequential version number.")
    site_data: JSON = strawberry.field(description="Full site data snapshot (JSON).")
    label: str | None = strawberry.field(default=None, description="Optional human-readable label.")
    created_at: datetime = strawberry.field(description="When the version was created.")


# ---------------------------------------------------------------------------
# Smartlead / Outreach types
# ---------------------------------------------------------------------------

@strawberry.type
class OutreachStatsType:
    """Outreach statistics for the admin dashboard."""
    emails_sent_30d: int = strawberry.field(default=0, description="Emails sent in the last 30 days.")
    open_rate: float = strawberry.field(default=0.0, description="Email open rate (0-1).")
    reply_rate: float = strawberry.field(default=0.0, description="Email reply rate (0-1).")
    click_rate: float = strawberry.field(default=0.0, description="Email click rate (0-1).")
    bounce_rate: float = strawberry.field(default=0.0, description="Email bounce rate (0-1).")
    conversions_30d: int = strawberry.field(default=0, description="Lead conversions in the last 30 days.")
    daily_send_count: int = strawberry.field(default=0, description="Emails sent today.")
    daily_send_limit: int = strawberry.field(default=0, description="Maximum emails allowed per day.")
    warmup_status: str = strawberry.field(default="not_configured", description="Email warmup status.")
    warmup_day: int = strawberry.field(default=0, description="Current warmup day number.")
    warmup_days_target: int = strawberry.field(default=14, description="Target number of warmup days.")


@strawberry.type
class AdminSiteType:
    """Site with owner info for admin views."""
    id: str = strawberry.field(description="Unique site identifier.")
    site_data: JSON = strawberry.field(description="Full site content (JSON).")
    template: str = strawberry.field(description="Template used for generation.")
    status: str = strawberry.field(description="Current site status.")
    subdomain: str | None = strawberry.field(default=None, description="Assigned subdomain.")
    custom_domain: str | None = strawberry.field(default=None, description="Custom domain if configured.")
    views: int = strawberry.field(default=0, description="Total page view count.")
    tokens_used: int | None = strawberry.field(default=None, description="Total AI tokens consumed.")
    input_tokens: int | None = strawberry.field(default=None, description="AI input tokens used.")
    output_tokens: int | None = strawberry.field(default=None, description="AI output tokens used.")
    ai_model: str | None = strawberry.field(default=None, description="AI model used.")
    generation_cost_usd: float | None = strawberry.field(default=None, description="Generation cost in USD.")
    published_at: datetime | None = strawberry.field(default=None, description="When the site was published.")
    created_at: datetime = strawberry.field(description="Creation timestamp.")
    updated_at: datetime = strawberry.field(description="Last update timestamp.")
    lead_id: str | None = strawberry.field(default=None, description="Associated lead ID.")
    business_name: str | None = strawberry.field(default=None, description="Business name from the lead.")
    website_url: str | None = strawberry.field(default=None, description="Original website URL.")
    # Owner info
    owner_id: str | None = strawberry.field(default=None, description="ID of the site owner.")
    owner_email: str | None = strawberry.field(default=None, description="Email of the site owner.")
    owner_name: str | None = strawberry.field(default=None, description="Display name of the site owner.")
    is_lead_site: bool = strawberry.field(default=False, description="Whether the site was created from a lead.")


@strawberry.type
class AdminSiteListType(PaginatedListType):
    items: list[AdminSiteType]


@strawberry.input(description="Filter and pagination input for admin site listing.")
class AdminSiteFilterInput(PaginationInput):
    search: str | None = strawberry.field(default=None, description="Free-text search across business name, subdomain, domain.")
    status: str | None = strawberry.field(default=None, description="Filter by site status.")
    is_lead_site: bool | None = strawberry.field(default=None, description="Filter lead-sites vs. user-created sites.")

    def __post_init__(self) -> None:
        _validate_max_length(self.search, _MAX_SEARCH_STRING, "search")
        _validate_max_length(self.status, _MAX_SHORT_STRING, "status")


@strawberry.input(description="Input for creating a new industry.")
class CreateIndustryInput:
    name: str = strawberry.field(description="Display name for the industry.")
    description: str | None = strawberry.field(default=None, description="Human-readable description.")
    prompt_hint: str | None = strawberry.field(default=None, description="AI prompt hint for site generation.")
    default_sections: list[str] | None = strawberry.field(default=None, description="Default section names.")

    def __post_init__(self) -> None:
        _validate_max_length(self.name, _MAX_SHORT_STRING, "name")
        _validate_max_length(self.description, 2000, "description")
        _validate_max_length(self.prompt_hint, 2000, "prompt_hint")


@strawberry.input(description="Input for updating an existing industry.")
class UpdateIndustryInput:
    id: str = strawberry.field(description="ID of the industry to update.")
    name: str | None = strawberry.field(default=None, description="New display name.")
    description: str | None = strawberry.field(default=None, description="New description.")
    prompt_hint: str | None = strawberry.field(default=None, description="New AI prompt hint.")
    default_sections: list[str] | None = strawberry.field(default=None, description="New default section names.")

    def __post_init__(self) -> None:
        _validate_max_length(self.id, _MAX_ID_LENGTH, "id")
        _validate_max_length(self.name, _MAX_SHORT_STRING, "name")
        _validate_max_length(self.description, 2000, "description")
        _validate_max_length(self.prompt_hint, 2000, "prompt_hint")


@strawberry.type
class SmartleadMessageType:
    """A message from Smartlead message history (sent or reply)."""
    id: str = strawberry.field(description="Unique message identifier.")
    type: str = strawberry.field(description="Message type: 'sent' or 'reply'.")
    subject: str | None = strawberry.field(default=None, description="Email subject line.")
    body: str | None = strawberry.field(default=None, description="Email body content.")
    from_email: str = strawberry.field(default="", description="Sender email address.")
    to_email: str = strawberry.field(default="", description="Recipient email address.")
    timestamp: datetime | None = strawberry.field(default=None, description="When the message was sent or received.")
    status: str | None = strawberry.field(default=None, description="Delivery status.")


# ---------------------------------------------------------------------------
# Google Search Console types
# ---------------------------------------------------------------------------

@strawberry.type(description="Google Search Console connection status.")
class GscConnectionType:
    connected: bool = strawberry.field(description="Whether GSC is connected.")
    google_email: str | None = strawberry.field(default=None, description="Google account email used.")
    indexed_domain: str | None = strawberry.field(default=None, description="Domain submitted for indexing.")
    indexed_at: datetime | None = strawberry.field(default=None, description="When the domain was submitted.")
    status: str | None = strawberry.field(default=None, description="Current indexing status.")
