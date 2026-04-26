"""AutoBlogger models — stored in a separate 'autoblogger' PostgreSQL schema.

Has its own standalone auth system (AutoBloggerUser, AutoBloggerSession, etc.).
"""
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    MetaData,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

AUTOBLOGGER_SCHEMA = "autoblogger"

# Separate Base with its own schema so tables are created in 'autoblogger'
autoblogger_metadata = MetaData(schema=AUTOBLOGGER_SCHEMA)


class AutoBloggerBase(DeclarativeBase):
    metadata = autoblogger_metadata


# ─── Enums ───────────────────────────────────────────────────────────────────

class PostStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    GENERATING = "GENERATING"
    REVIEW = "REVIEW"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"


class PlatformType(str, enum.Enum):
    SHOPIFY = "SHOPIFY"
    QVICKO = "QVICKO"
    CUSTOM = "CUSTOM"  # Also used for WordPress / REST API integrations
    MANUAL = "MANUAL"


class TaskFrequency(str, enum.Enum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"
    MONTHLY = "MONTHLY"


class AutoBloggerUserRole(str, enum.Enum):
    USER = "USER"
    ADMIN = "ADMIN"


class AutoBloggerSocialProvider(str, enum.Enum):
    GOOGLE = "GOOGLE"
    APPLE = "APPLE"
    FACEBOOK = "FACEBOOK"
    GITHUB = "GITHUB"


class AutoBloggerAuditEventType(str, enum.Enum):
    LOGIN = "LOGIN"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGOUT = "LOGOUT"
    REGISTER = "REGISTER"
    PASSWORD_CHANGE = "PASSWORD_CHANGE"
    PASSWORD_RESET_REQUEST = "PASSWORD_RESET_REQUEST"
    PASSWORD_RESET_COMPLETE = "PASSWORD_RESET_COMPLETE"
    EMAIL_CHANGE = "EMAIL_CHANGE"
    TWO_FACTOR_ENABLE = "TWO_FACTOR_ENABLE"
    TWO_FACTOR_DISABLE = "TWO_FACTOR_DISABLE"
    TWO_FACTOR_VERIFY = "TWO_FACTOR_VERIFY"
    TWO_FACTOR_FAILED = "TWO_FACTOR_FAILED"
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    ACCOUNT_UNLOCKED = "ACCOUNT_UNLOCKED"
    ACCOUNT_DEACTIVATED = "ACCOUNT_DEACTIVATED"
    ACCOUNT_REACTIVATED = "ACCOUNT_REACTIVATED"
    SESSION_REVOKED = "SESSION_REVOKED"
    SOCIAL_ACCOUNT_LINKED = "SOCIAL_ACCOUNT_LINKED"
    SOCIAL_ACCOUNT_UNLINKED = "SOCIAL_ACCOUNT_UNLINKED"
    EMAIL_VERIFICATION_SENT = "EMAIL_VERIFICATION_SENT"
    EMAIL_VERIFIED = "EMAIL_VERIFIED"
    PROFILE_UPDATE = "PROFILE_UPDATE"


# ─── Auth Models ─────────────────────────────────────────────────────────────


class AutoBloggerUser(AutoBloggerBase):
    """Standalone AutoBlogger user — not shared with Qvicko/easyprocess."""
    __tablename__ = "ab_users"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    org_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    locale: Mapped[str] = mapped_column(String(10), nullable=False, default="sv")

    role: Mapped[AutoBloggerUserRole] = mapped_column(
        Enum(AutoBloggerUserRole, name="ab_user_role", schema=AUTOBLOGGER_SCHEMA),
        default=AutoBloggerUserRole.USER, nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # 2FA
    two_factor_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    two_factor_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Security
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Soft delete
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Stripe (for billing)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Timestamps
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
    sessions: Mapped[list["AutoBloggerSession"]] = relationship(
        "AutoBloggerSession", back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    social_accounts: Mapped[list["AutoBloggerSocialAccount"]] = relationship(
        "AutoBloggerSocialAccount", back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        {"schema": AUTOBLOGGER_SCHEMA},
    )


class AutoBloggerSession(AutoBloggerBase):
    """DB-backed session for AutoBlogger auth."""
    __tablename__ = "ab_sessions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{AUTOBLOGGER_SCHEMA}.ab_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    device_info: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Device trust & master session
    device_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    is_trusted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    master_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    user: Mapped[AutoBloggerUser] = relationship("AutoBloggerUser", back_populates="sessions", lazy="selectin")

    __table_args__ = (
        Index("idx_ab_sessions_user_id", "user_id"),
        Index("idx_ab_sessions_expires_at", "expires_at"),
        Index("idx_ab_sessions_device_fp", "device_fingerprint"),
        {"schema": AUTOBLOGGER_SCHEMA},
    )


class AutoBloggerAuditLog(AutoBloggerBase):
    """Audit trail for AutoBlogger auth events."""
    __tablename__ = "ab_audit_logs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(f"{AUTOBLOGGER_SCHEMA}.ab_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[AutoBloggerAuditEventType] = mapped_column(
        Enum(AutoBloggerAuditEventType, name="ab_audit_event_type", schema=AUTOBLOGGER_SCHEMA), nullable=False
    )
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    __table_args__ = (
        Index("idx_ab_audit_logs_user_id", "user_id"),
        Index("idx_ab_audit_logs_event_type", "event_type"),
        Index("idx_ab_audit_logs_created_at", "created_at"),
        {"schema": AUTOBLOGGER_SCHEMA},
    )


class AutoBloggerSocialAccount(AutoBloggerBase):
    """Social login accounts linked to an AutoBlogger user."""
    __tablename__ = "ab_social_accounts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{AUTOBLOGGER_SCHEMA}.ab_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[AutoBloggerSocialProvider] = mapped_column(
        Enum(AutoBloggerSocialProvider, name="ab_social_provider", schema=AUTOBLOGGER_SCHEMA), nullable=False
    )
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    user: Mapped[AutoBloggerUser] = relationship("AutoBloggerUser", back_populates="social_accounts", lazy="selectin")

    __table_args__ = (
        Index("idx_ab_social_provider_uid", "provider", "provider_user_id", unique=True),
        Index("idx_ab_social_user_id", "user_id"),
        {"schema": AUTOBLOGGER_SCHEMA},
    )


class AutoBloggerPasswordResetToken(AutoBloggerBase):
    """Password reset tokens for AutoBlogger users."""
    __tablename__ = "ab_password_reset_tokens"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{AUTOBLOGGER_SCHEMA}.ab_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    user: Mapped[AutoBloggerUser] = relationship("AutoBloggerUser")

    __table_args__ = (
        {"schema": AUTOBLOGGER_SCHEMA},
    )


class AutoBloggerEmailVerificationToken(AutoBloggerBase):
    """Email verification tokens for AutoBlogger users."""
    __tablename__ = "ab_email_verification_tokens"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{AUTOBLOGGER_SCHEMA}.ab_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    user: Mapped[AutoBloggerUser] = relationship("AutoBloggerUser")

    __table_args__ = (
        {"schema": AUTOBLOGGER_SCHEMA},
    )


# ─── Models ──────────────────────────────────────────────────────────────────

class Source(AutoBloggerBase):
    """A content source connects a user to a publishing platform."""
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    platform: Mapped[PlatformType] = mapped_column(Enum(PlatformType, name="platformtype", schema=AUTOBLOGGER_SCHEMA), nullable=False)
    platform_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    platform_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    brand_voice: Mapped[str | None] = mapped_column(Text, nullable=True)
    brand_images: Mapped[list | None] = mapped_column(JSON, nullable=True)
    default_language: Mapped[str] = mapped_column(String(10), default="en", nullable=False)
    target_keywords: Mapped[list | None] = mapped_column(JSON, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    posts: Mapped[list["BlogPostAB"]] = relationship(
        "BlogPostAB", back_populates="source", cascade="all, delete-orphan", lazy="selectin"
    )
    schedules: Mapped[list["ContentSchedule"]] = relationship(
        "ContentSchedule", back_populates="source", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        Index("idx_src_user_id", "user_id"),
        {"schema": AUTOBLOGGER_SCHEMA},
    )


class BlogPostAB(AutoBloggerBase):
    """An AI-generated blog post."""
    __tablename__ = "blog_posts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    source_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{AUTOBLOGGER_SCHEMA}.sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    slug: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    meta_description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    featured_image_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    language: Mapped[str] = mapped_column(String(10), default="en", nullable=False)

    status: Mapped[PostStatus] = mapped_column(
        Enum(PostStatus, name="poststatus", schema=AUTOBLOGGER_SCHEMA), default=PostStatus.DRAFT, nullable=False
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    platform_post_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # SEO data
    target_keyword: Mapped[str | None] = mapped_column(String(255), nullable=True)
    schema_markup: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    internal_links: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # AI generation metadata
    ai_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    generation_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # New fields
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reading_time_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    credits_used: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    source: Mapped["Source"] = relationship("Source", back_populates="posts")

    __table_args__ = (
        Index("idx_abp_source_id", "source_id"),
        Index("idx_abp_user_id", "user_id"),
        Index("idx_abp_status", "status"),
        Index("idx_abp_scheduled_at", "scheduled_at"),
        {"schema": AUTOBLOGGER_SCHEMA},
    )


class ContentSchedule(AutoBloggerBase):
    """A recurring content generation schedule."""
    __tablename__ = "content_schedules"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    source_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{AUTOBLOGGER_SCHEMA}.sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    frequency: Mapped[TaskFrequency] = mapped_column(Enum(TaskFrequency, name="taskfrequency", schema=AUTOBLOGGER_SCHEMA), nullable=False)
    days_of_week: Mapped[list | None] = mapped_column(JSON, nullable=True)
    posts_per_day: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    preferred_time: Mapped[str | None] = mapped_column(String(10), nullable=True)
    timezone: Mapped[str] = mapped_column(String(50), default="Europe/Stockholm", nullable=False)
    topics: Mapped[list | None] = mapped_column(JSON, nullable=True)
    keywords: Mapped[list | None] = mapped_column(JSON, nullable=True)
    language: Mapped[str] = mapped_column(String(10), default="en", nullable=False)
    auto_publish: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    posts_generated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    source: Mapped["Source"] = relationship("Source", back_populates="schedules")

    __table_args__ = (
        Index("idx_cs_source_id", "source_id"),
        Index("idx_cs_next_run", "next_run_at"),
        {"schema": AUTOBLOGGER_SCHEMA},
    )


class UserSettings(AutoBloggerBase):
    """Per-user AutoBlogger settings."""
    __tablename__ = "user_settings"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True)

    auto_publish: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ai_model: Mapped[str] = mapped_column(String(100), default="claude-sonnet-4-20250514", nullable=False)
    image_generation: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    default_language: Mapped[str] = mapped_column(String(10), default="en", nullable=False)
    brand_voice_global: Mapped[str | None] = mapped_column(Text, nullable=True)
    posts_per_month_limit: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    notification_email: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        {"schema": AUTOBLOGGER_SCHEMA},
    )


class AutoBloggerSubscription(AutoBloggerBase):
    """Tracks AutoBlogger Stripe subscriptions separately from Qvicko subs."""
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True)
    stripe_subscription_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    stripe_customer_id: Mapped[str] = mapped_column(String(255), nullable=False)
    plan: Mapped[str] = mapped_column(String(50), nullable=False)  # "pro" or "business"
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="trialing")
    # trialing, active, past_due, canceled, incomplete
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trial_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trial_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        Index("idx_absub_user_id", "user_id"),
        Index("idx_absub_stripe_id", "stripe_subscription_id"),
        {"schema": AUTOBLOGGER_SCHEMA},
    )


class AutoBloggerPayment(AutoBloggerBase):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    subscription_id: Mapped[str | None] = mapped_column(String(36), ForeignKey(f"{AUTOBLOGGER_SCHEMA}.subscriptions.id", ondelete="SET NULL"), nullable=True)
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    stripe_invoice_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # öre
    currency: Mapped[str] = mapped_column(String(10), default="sek", nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)  # succeeded, failed
    invoice_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        Index("idx_abpay_user_id", "user_id"),
        {"schema": AUTOBLOGGER_SCHEMA},
    )


class CreditBalance(AutoBloggerBase):
    """Tracks a user's credit balance for AI post generation."""
    __tablename__ = "credit_balances"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True)

    credits_remaining: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    credits_used_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    plan_credits_monthly: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    last_reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        {"schema": AUTOBLOGGER_SCHEMA},
    )


class Notification(AutoBloggerBase):
    """In-app notification for AutoBlogger events."""
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    # "post_generated", "post_failed", "post_review", "credits_low",
    # "credits_exhausted", "source_connected", "source_error"
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    __table_args__ = (
        Index("idx_notif_user_id", "user_id"),
        Index("idx_notif_user_unread", "user_id", "is_read"),
        Index("idx_notif_created_at", "created_at"),
        {"schema": AUTOBLOGGER_SCHEMA},
    )


class AnalyticsEventType(str, enum.Enum):
    POST_GENERATED = "POST_GENERATED"
    POST_PUBLISHED = "POST_PUBLISHED"
    CREDIT_USED = "CREDIT_USED"
    SCHEDULE_EXECUTED = "SCHEDULE_EXECUTED"
    GENERATION_FAILED = "GENERATION_FAILED"


class AnalyticsEvent(AutoBloggerBase):
    """Tracks analytics events for the AutoBlogger dashboard."""
    __tablename__ = "analytics_events"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    event_type: Mapped[AnalyticsEventType] = mapped_column(
        Enum(AnalyticsEventType, name="analyticseventtype", schema=AUTOBLOGGER_SCHEMA), nullable=False
    )
    event_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    __table_args__ = (
        Index("idx_ae_user_id", "user_id"),
        Index("idx_ae_event_type", "event_type"),
        Index("idx_ae_created_at", "created_at"),
        Index("idx_ae_user_type_created", "user_id", "event_type", "created_at"),
        {"schema": AUTOBLOGGER_SCHEMA},
    )


class CreditTransaction(AutoBloggerBase):
    """Individual credit transaction log entry."""
    __tablename__ = "credit_transactions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    post_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(f"{AUTOBLOGGER_SCHEMA}.blog_posts.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    post: Mapped["BlogPostAB | None"] = relationship("BlogPostAB", lazy="selectin")

    __table_args__ = (
        Index("idx_ct_user_id", "user_id"),
        Index("idx_ct_created_at", "created_at"),
        {"schema": AUTOBLOGGER_SCHEMA},
    )
