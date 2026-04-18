import enum
import uuid
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

SCHEMA = "easyprocess"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class LeadStatus(str, enum.Enum):
    NEW = "NEW"
    SCRAPING = "SCRAPING"
    SCRAPED = "SCRAPED"
    GENERATING = "GENERATING"
    GENERATED = "GENERATED"
    EMAIL_SENT = "EMAIL_SENT"
    OPENED = "OPENED"
    CONVERTED = "CONVERTED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class SiteStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    PURCHASED = "PURCHASED"
    ARCHIVED = "ARCHIVED"


class DomainStatus(str, enum.Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    FAILED = "FAILED"


# Subdomains that cannot be used by users
BLACKLISTED_SUBDOMAINS = frozenset({
    "www", "mail", "email", "ftp", "ssh", "api", "app", "admin", "dashboard",
    "panel", "login", "register", "auth", "oauth", "signup", "signin",
    "support", "help", "docs", "blog", "news", "status", "cdn", "assets",
    "static", "media", "images", "img", "files", "download", "uploads",
    "staging", "dev", "test", "demo", "preview", "sandbox",
    "ns1", "ns2", "ns3", "ns4", "mx", "smtp", "pop", "imap",
    "proxy", "vpn", "gateway", "relay",
    "billing", "payment", "checkout", "store", "shop",
    "qvicko", "viewer", "editor", "builder",
    "abuse", "postmaster", "webmaster", "hostmaster", "root", "info",
    "noreply", "no-reply", "mailer-daemon",
})


class EmailStatus(str, enum.Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    OPENED = "OPENED"
    CLICKED = "CLICKED"
    BOUNCED = "BOUNCED"
    FAILED = "FAILED"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    business_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    website_url: Mapped[str] = mapped_column(String(500), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False, default="manual")

    status: Mapped[LeadStatus] = mapped_column(
        Enum(LeadStatus), default=LeadStatus.NEW, nullable=False
    )
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Created by (superadmin user)
    created_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey(f"{SCHEMA}.users.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    scraped_data: Mapped["ScrapedData | None"] = relationship(
        "ScrapedData", back_populates="lead", uselist=False, cascade="all, delete-orphan"
    )
    generated_site: Mapped["GeneratedSite | None"] = relationship(
        "GeneratedSite", back_populates="lead", uselist=False, cascade="all, delete-orphan"
    )
    outreach_emails: Mapped[list["OutreachEmail"]] = relationship(
        "OutreachEmail", back_populates="lead", cascade="all, delete-orphan"
    )
    inbound_emails: Mapped[list["InboundEmail"]] = relationship(
        "InboundEmail", back_populates="matched_lead", foreign_keys="InboundEmail.matched_lead_id"
    )

    __table_args__ = (
        Index("idx_leads_status", "status"),
        Index("idx_leads_email", "email"),
        Index("idx_leads_website_url", "website_url"),
        Index("idx_leads_created_by", "created_by"),
        {"schema": SCHEMA},
    )


class ScrapedData(Base):
    __tablename__ = "scraped_data"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    lead_id: Mapped[str] = mapped_column(
        String(36), ForeignKey(f"{SCHEMA}.leads.id", ondelete="CASCADE"),
        nullable=False, unique=True
    )

    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    colors: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    texts: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    images: Mapped[list | None] = mapped_column(JSON, nullable=True)
    contact_info: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    meta_info: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    raw_html_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    lead: Mapped[Lead] = relationship("Lead", back_populates="scraped_data")

    __table_args__ = (
        Index("idx_scraped_data_lead_id", "lead_id"),
        {"schema": SCHEMA},
    )


class GeneratedSite(Base):
    __tablename__ = "generated_sites"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    lead_id: Mapped[str] = mapped_column(
        String(36), ForeignKey(f"{SCHEMA}.leads.id", ondelete="CASCADE"),
        nullable=False, unique=True
    )

    # The full site JSON (SiteSchema)
    site_data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    template: Mapped[str] = mapped_column(String(50), nullable=False, default="default")

    status: Mapped[SiteStatus] = mapped_column(
        Enum(SiteStatus), default=SiteStatus.DRAFT, nullable=False
    )
    subdomain: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    custom_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    views: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # AI generation cost tracking
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(50), nullable=True)
    generation_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    purchased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    lead: Mapped[Lead] = relationship("Lead", back_populates="generated_site")
    outreach_emails: Mapped[list["OutreachEmail"]] = relationship(
        "OutreachEmail", back_populates="site"
    )

    __table_args__ = (
        Index("idx_generated_sites_lead_id", "lead_id"),
        Index("idx_generated_sites_subdomain", "subdomain"),
        Index("idx_generated_sites_status", "status"),
        {"schema": SCHEMA},
    )


class OutreachEmail(Base):
    __tablename__ = "outreach_emails"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    lead_id: Mapped[str] = mapped_column(
        String(36), ForeignKey(f"{SCHEMA}.leads.id", ondelete="CASCADE"), nullable=False
    )
    site_id: Mapped[str] = mapped_column(
        String(36), ForeignKey(f"{SCHEMA}.generated_sites.id", ondelete="CASCADE"), nullable=False
    )

    to_email: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    body_html: Mapped[str] = mapped_column(Text, nullable=False)

    resend_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[EmailStatus] = mapped_column(
        Enum(EmailStatus), default=EmailStatus.PENDING, nullable=False
    )

    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    clicked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    lead: Mapped[Lead] = relationship("Lead", back_populates="outreach_emails")
    site: Mapped[GeneratedSite] = relationship("GeneratedSite", back_populates="outreach_emails")

    __table_args__ = (
        Index("idx_outreach_emails_lead_id", "lead_id"),
        Index("idx_outreach_emails_site_id", "site_id"),
        Index("idx_outreach_emails_resend_id", "resend_id"),
        Index("idx_outreach_emails_status", "status"),
        {"schema": SCHEMA},
    )


class EmailCategory(str, enum.Enum):
    SPAM = "spam"
    LEAD_REPLY = "lead_reply"
    SUPPORT = "support"
    INQUIRY = "inquiry"
    OTHER = "other"


class PageView(Base):
    """Individual page view event with performance metrics."""
    __tablename__ = "page_views"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    site_id: Mapped[str] = mapped_column(
        String(36), ForeignKey(f"{SCHEMA}.generated_sites.id", ondelete="CASCADE"),
        nullable=False,
    )
    visitor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    path: Mapped[str] = mapped_column(String(500), nullable=False, default="/")
    referrer: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    screen_width: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Web Vitals
    load_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ttfb_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fcp_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lcp_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cls: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    __table_args__ = (
        Index("idx_page_views_site_id", "site_id"),
        Index("idx_page_views_created_at", "created_at"),
        Index("idx_page_views_site_created", "site_id", "created_at"),
        Index("idx_page_views_visitor_id", "visitor_id"),
        Index("idx_page_views_session_id", "session_id"),
        {"schema": SCHEMA},
    )


class InboundEmail(Base):
    __tablename__ = "inbound_emails"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))

    # Envelope
    from_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    from_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    to_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    subject: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Content
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Classification (stored as varchar, validated by Python enum)
    category: Mapped[str] = mapped_column(
        String(20), default=EmailCategory.OTHER.value
    )
    spam_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Lead matching
    matched_lead_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey(f"{SCHEMA}.leads.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Status
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)

    # Resend metadata
    resend_email_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    matched_lead: Mapped["Lead | None"] = relationship("Lead", foreign_keys=[matched_lead_id])


class CustomDomain(Base):
    """User-owned custom domain that can be assigned to a generated site."""
    __tablename__ = "custom_domains"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), nullable=False
    )
    domain: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    site_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey(f"{SCHEMA}.generated_sites.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[DomainStatus] = mapped_column(
        Enum(DomainStatus), default=DomainStatus.PENDING, nullable=False
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    site: Mapped["GeneratedSite | None"] = relationship("GeneratedSite", foreign_keys=[site_id])

    __table_args__ = (
        Index("idx_custom_domains_user_id", "user_id"),
        Index("idx_custom_domains_domain", "domain"),
        Index("idx_custom_domains_site_id", "site_id"),
        {"schema": SCHEMA},
    )


class DomainPurchaseStatus(str, enum.Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    PURCHASED = "PURCHASED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class DomainPurchase(Base):
    """Domain purchased via Vercel Domains on behalf of a user."""
    __tablename__ = "domain_purchases"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), nullable=False
    )
    domain: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    price_sek: Mapped[int] = mapped_column(Integer, nullable=False)  # öre
    price_usd: Mapped[float] = mapped_column(Float, nullable=False)  # Vercel cost
    period_years: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[DomainPurchaseStatus] = mapped_column(
        Enum(DomainPurchaseStatus), default=DomainPurchaseStatus.PENDING_PAYMENT, nullable=False
    )
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vercel_domain_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    purchased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    __table_args__ = (
        Index("idx_domain_purchases_user_id", "user_id"),
        Index("idx_domain_purchases_domain", "domain"),
        {"schema": SCHEMA},
    )


class ContactMessage(Base):
    """Contact form message submitted by a site visitor."""
    __tablename__ = "contact_messages"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    site_id: Mapped[str] = mapped_column(
        String(36), ForeignKey(f"{SCHEMA}.generated_sites.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # Relationships
    site: Mapped["GeneratedSite"] = relationship("GeneratedSite", foreign_keys=[site_id])

    __table_args__ = (
        Index("idx_contact_messages_site_id", "site_id"),
        {"schema": SCHEMA},
    )
