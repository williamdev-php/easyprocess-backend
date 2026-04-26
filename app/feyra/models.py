"""Feyra models — stored in a separate 'feyra' PostgreSQL schema.

AI-powered email warmup, lead generation & cold outreach platform.
Has its own standalone auth system (FeyraUser, FeyraSession, etc.).
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

FEYRA_SCHEMA = "feyra"

# Separate Base with its own schema so tables are created in 'feyra'
feyra_metadata = MetaData(schema=FEYRA_SCHEMA)


class FeyraBase(DeclarativeBase):
    metadata = feyra_metadata


# ─── Enums ───────────────────────────────────────────────────────────────────

class EmailProvider(str, enum.Enum):
    GMAIL = "GMAIL"
    OUTLOOK = "OUTLOOK"
    YAHOO = "YAHOO"
    CUSTOM = "CUSTOM"


class ConnectionStatus(str, enum.Enum):
    PENDING = "PENDING"
    CONNECTED = "CONNECTED"
    ERROR = "ERROR"
    DISCONNECTED = "DISCONNECTED"


class WarmupStatus(str, enum.Enum):
    IDLE = "IDLE"
    WARMING = "WARMING"
    READY = "READY"
    PAUSED = "PAUSED"


class WarmupEmailDirection(str, enum.Enum):
    SENT = "SENT"
    RECEIVED = "RECEIVED"


class WarmupEmailStatus(str, enum.Enum):
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    OPENED = "OPENED"
    REPLIED = "REPLIED"
    BOUNCED = "BOUNCED"
    SPAM = "SPAM"


class CompanySize(str, enum.Enum):
    SIZE_1_10 = "1-10"
    SIZE_11_50 = "11-50"
    SIZE_51_200 = "51-200"
    SIZE_201_500 = "201-500"
    SIZE_500_PLUS = "500+"


class EmailVerificationStatus(str, enum.Enum):
    PENDING = "PENDING"
    VALID = "VALID"
    INVALID = "INVALID"
    CATCH_ALL = "CATCH_ALL"


class LeadSource(str, enum.Enum):
    CRAWL = "CRAWL"
    CSV_IMPORT = "CSV_IMPORT"
    MANUAL = "MANUAL"
    API = "API"


class LeadStatus(str, enum.Enum):
    NEW = "NEW"
    CONTACTED = "CONTACTED"
    REPLIED = "REPLIED"
    INTERESTED = "INTERESTED"
    NOT_INTERESTED = "NOT_INTERESTED"
    BOUNCED = "BOUNCED"
    UNSUBSCRIBED = "UNSUBSCRIBED"


class CrawlType(str, enum.Enum):
    WEBSITE = "WEBSITE"
    GOOGLE_SEARCH = "GOOGLE_SEARCH"
    LINKEDIN_SEARCH = "LINKEDIN_SEARCH"


class CrawlJobStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class CrawlResultStatus(str, enum.Enum):
    PENDING = "PENDING"
    SCRAPED = "SCRAPED"
    PROCESSED = "PROCESSED"
    ERROR = "ERROR"


class CampaignStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"


class AITone(str, enum.Enum):
    PROFESSIONAL = "PROFESSIONAL"
    CASUAL = "CASUAL"
    FRIENDLY = "FRIENDLY"
    DIRECT = "DIRECT"


class CampaignLeadStatus(str, enum.Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    REPLIED = "REPLIED"
    BOUNCED = "BOUNCED"
    UNSUBSCRIBED = "UNSUBSCRIBED"
    COMPLETED = "COMPLETED"


class SentEmailStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    OPENED = "OPENED"
    REPLIED = "REPLIED"
    BOUNCED = "BOUNCED"
    SPAM_COMPLAINT = "SPAM_COMPLAINT"


class AIModelPreference(str, enum.Enum):
    QUALITY = "QUALITY"
    BALANCED = "BALANCED"
    FAST = "FAST"


class FeyraUserRole(str, enum.Enum):
    USER = "USER"
    ADMIN = "ADMIN"


class FeyraSocialProvider(str, enum.Enum):
    GOOGLE = "GOOGLE"
    APPLE = "APPLE"
    FACEBOOK = "FACEBOOK"
    GITHUB = "GITHUB"


class FeyraAuditEventType(str, enum.Enum):
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


class FeyraUser(FeyraBase):
    """Standalone Feyra user — not shared with Qvicko/easyprocess."""
    __tablename__ = "feyra_users"

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

    role: Mapped[FeyraUserRole] = mapped_column(
        Enum(FeyraUserRole, name="feyra_user_role", schema="feyra"), default=FeyraUserRole.USER, nullable=False
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
    sessions: Mapped[list["FeyraSession"]] = relationship(
        "FeyraSession", back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    social_accounts: Mapped[list["FeyraSocialAccount"]] = relationship(
        "FeyraSocialAccount", back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        {"schema": FEYRA_SCHEMA},
    )


class FeyraSession(FeyraBase):
    """DB-backed session for Feyra auth."""
    __tablename__ = "feyra_sessions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{FEYRA_SCHEMA}.feyra_users.id", ondelete="CASCADE"),
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

    user: Mapped[FeyraUser] = relationship("FeyraUser", back_populates="sessions", lazy="selectin")

    __table_args__ = (
        Index("idx_feyra_sessions_user_id", "user_id"),
        Index("idx_feyra_sessions_expires_at", "expires_at"),
        Index("idx_feyra_sessions_device_fp", "device_fingerprint"),
        {"schema": FEYRA_SCHEMA},
    )


class FeyraAuditLog(FeyraBase):
    """Audit trail for Feyra auth events."""
    __tablename__ = "feyra_audit_logs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(f"{FEYRA_SCHEMA}.feyra_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[FeyraAuditEventType] = mapped_column(
        Enum(FeyraAuditEventType, name="feyra_audit_event_type", schema="feyra"), nullable=False
    )
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    __table_args__ = (
        Index("idx_feyra_audit_logs_user_id", "user_id"),
        Index("idx_feyra_audit_logs_event_type", "event_type"),
        Index("idx_feyra_audit_logs_created_at", "created_at"),
        {"schema": FEYRA_SCHEMA},
    )


class FeyraSocialAccount(FeyraBase):
    """Social login accounts linked to a Feyra user."""
    __tablename__ = "feyra_social_accounts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{FEYRA_SCHEMA}.feyra_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[FeyraSocialProvider] = mapped_column(
        Enum(FeyraSocialProvider, name="feyra_social_provider", schema="feyra"), nullable=False
    )
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    user: Mapped[FeyraUser] = relationship("FeyraUser", back_populates="social_accounts", lazy="selectin")

    __table_args__ = (
        Index("idx_feyra_social_provider_uid", "provider", "provider_user_id", unique=True),
        Index("idx_feyra_social_user_id", "user_id"),
        {"schema": FEYRA_SCHEMA},
    )


class FeyraPasswordResetToken(FeyraBase):
    """Password reset tokens for Feyra users."""
    __tablename__ = "feyra_password_reset_tokens"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{FEYRA_SCHEMA}.feyra_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    user: Mapped[FeyraUser] = relationship("FeyraUser")

    __table_args__ = (
        {"schema": FEYRA_SCHEMA},
    )


class FeyraEmailVerificationToken(FeyraBase):
    """Email verification tokens for Feyra users."""
    __tablename__ = "feyra_email_verification_tokens"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{FEYRA_SCHEMA}.feyra_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    user: Mapped[FeyraUser] = relationship("FeyraUser")

    __table_args__ = (
        {"schema": FEYRA_SCHEMA},
    )


# ─── Models ──────────────────────────────────────────────────────────────────

class EmailAccount(FeyraBase):
    """Email accounts for sending warmup and outreach emails."""
    __tablename__ = "email_accounts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{FEYRA_SCHEMA}.feyra_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    email_address: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # IMAP settings
    imap_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    imap_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    imap_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    imap_password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    imap_use_ssl: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # SMTP settings
    smtp_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    smtp_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    smtp_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    smtp_password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    smtp_use_tls: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Provider & connection
    provider: Mapped[EmailProvider] = mapped_column(
        Enum(EmailProvider, schema="feyra"), default=EmailProvider.CUSTOM, nullable=False
    )
    connection_status: Mapped[ConnectionStatus] = mapped_column(
        Enum(ConnectionStatus, schema="feyra"), default=ConnectionStatus.PENDING, nullable=False
    )
    last_connection_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    connection_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Sending & warmup
    daily_send_limit: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    warmup_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    warmup_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    warmup_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sender_reputation_score: Mapped[int | None] = mapped_column(Integer, nullable=True)

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

    __table_args__ = (
        Index("idx_fea_user_id", "user_id"),
        Index("idx_fea_email_address", "email_address"),
        Index("idx_fea_connection_status", "connection_status"),
        Index("idx_fea_created_at", "created_at"),
        {"schema": FEYRA_SCHEMA},
    )


class WarmupSettings(FeyraBase):
    """Per email account warmup configuration."""
    __tablename__ = "warmup_settings"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    email_account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{FEYRA_SCHEMA}.email_accounts.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    daily_warmup_emails_min: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    daily_warmup_emails_max: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    ramp_up_increment_per_day: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    reply_rate_percent: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    warmup_duration_days: Mapped[int] = mapped_column(Integer, default=14, nullable=False)
    schedule_start_hour: Mapped[int] = mapped_column(Integer, default=8, nullable=False)
    schedule_end_hour: Mapped[int] = mapped_column(Integer, default=18, nullable=False)
    schedule_timezone: Mapped[str] = mapped_column(
        String(50), default="Europe/Stockholm", nullable=False
    )
    days_active: Mapped[list | None] = mapped_column(
        JSON, default=lambda: ["mon", "tue", "wed", "thu", "fri"], nullable=True
    )
    current_day: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[WarmupStatus] = mapped_column(
        Enum(WarmupStatus, schema="feyra"), default=WarmupStatus.IDLE, nullable=False
    )

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
        Index("idx_fws_email_account_id", "email_account_id"),
        Index("idx_fws_status", "status"),
        {"schema": FEYRA_SCHEMA},
    )


class WarmupEmail(FeyraBase):
    """Tracks warmup emails sent and received."""
    __tablename__ = "warmup_emails"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    from_account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{FEYRA_SCHEMA}.email_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    to_account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{FEYRA_SCHEMA}.email_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    message_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    in_reply_to: Mapped[str | None] = mapped_column(String(500), nullable=True)

    direction: Mapped[WarmupEmailDirection] = mapped_column(
        Enum(WarmupEmailDirection, schema="feyra"), nullable=False
    )
    status: Mapped[WarmupEmailStatus] = mapped_column(
        Enum(WarmupEmailStatus, schema="feyra"), default=WarmupEmailStatus.SENT, nullable=False
    )
    landed_in_spam: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rescued_from_spam: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    __table_args__ = (
        Index("idx_fwe_from_account_id", "from_account_id"),
        Index("idx_fwe_to_account_id", "to_account_id"),
        Index("idx_fwe_status", "status"),
        Index("idx_fwe_created_at", "created_at"),
        {"schema": FEYRA_SCHEMA},
    )


class Lead(FeyraBase):
    """Discovered or imported leads for outreach."""
    __tablename__ = "leads"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{FEYRA_SCHEMA}.feyra_users.id", ondelete="CASCADE"),
        nullable=False,
    )

    email: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company_size: Mapped[CompanySize | None] = mapped_column(
        Enum(CompanySize, schema="feyra"), nullable=True
    )
    industry: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)

    linkedin_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    website_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_verification_status: Mapped[EmailVerificationStatus] = mapped_column(
        Enum(EmailVerificationStatus, schema="feyra"), default=EmailVerificationStatus.PENDING, nullable=False
    )
    lead_score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    source: Mapped[LeadSource] = mapped_column(
        Enum(LeadSource, schema="feyra"), default=LeadSource.MANUAL, nullable=False
    )
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[LeadStatus] = mapped_column(
        Enum(LeadStatus, schema="feyra"), default=LeadStatus.NEW, nullable=False
    )
    last_contacted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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
        Index("idx_fl_user_id", "user_id"),
        Index("idx_fl_email", "email"),
        Index("idx_fl_status", "status"),
        Index("idx_fl_company_domain", "company_domain"),
        Index("idx_fl_created_at", "created_at"),
        {"schema": FEYRA_SCHEMA},
    )


class CrawlJob(FeyraBase):
    """Web crawling jobs for lead discovery."""
    __tablename__ = "crawl_jobs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{FEYRA_SCHEMA}.feyra_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    seed_urls: Mapped[list | None] = mapped_column(JSON, nullable=True)
    target_domains: Mapped[list | None] = mapped_column(JSON, nullable=True)
    max_pages: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    max_depth: Mapped[int] = mapped_column(Integer, default=3, nullable=False)

    crawl_type: Mapped[CrawlType] = mapped_column(
        Enum(CrawlType, schema="feyra"), default=CrawlType.WEBSITE, nullable=False
    )
    search_query: Mapped[str | None] = mapped_column(String(500), nullable=True)
    icp_description: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[CrawlJobStatus] = mapped_column(
        Enum(CrawlJobStatus, schema="feyra"), default=CrawlJobStatus.PENDING, nullable=False
    )
    pages_crawled: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    leads_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    emails_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

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
        Index("idx_fcj_user_id", "user_id"),
        Index("idx_fcj_status", "status"),
        Index("idx_fcj_created_at", "created_at"),
        {"schema": FEYRA_SCHEMA},
    )


class CrawlResult(FeyraBase):
    """Individual crawled pages from a crawl job."""
    __tablename__ = "crawl_results"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    crawl_job_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{FEYRA_SCHEMA}.crawl_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )

    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    page_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    emails_found: Mapped[list | None] = mapped_column(JSON, nullable=True)
    contacts_extracted: Mapped[list | None] = mapped_column(JSON, nullable=True)

    status: Mapped[CrawlResultStatus] = mapped_column(
        Enum(CrawlResultStatus, schema="feyra"), default=CrawlResultStatus.PENDING, nullable=False
    )
    http_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    crawled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_fcr_crawl_job_id", "crawl_job_id"),
        Index("idx_fcr_status", "status"),
        {"schema": FEYRA_SCHEMA},
    )


class Campaign(FeyraBase):
    """Outreach campaigns."""
    __tablename__ = "campaigns"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{FEYRA_SCHEMA}.feyra_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    email_account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{FEYRA_SCHEMA}.email_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )

    status: Mapped[CampaignStatus] = mapped_column(
        Enum(CampaignStatus, schema="feyra"), default=CampaignStatus.DRAFT, nullable=False
    )
    send_start_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    send_end_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    daily_send_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)

    schedule_start_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    schedule_end_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)
    schedule_timezone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    days_active: Mapped[list | None] = mapped_column(JSON, nullable=True)

    delay_between_emails_min_seconds: Mapped[int] = mapped_column(
        Integer, default=60, nullable=False
    )
    delay_between_emails_max_seconds: Mapped[int] = mapped_column(
        Integer, default=300, nullable=False
    )
    stop_on_reply: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    track_opens: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Stats
    total_leads: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    emails_sent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    emails_opened: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    replies_received: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bounces: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

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
        Index("idx_fc_user_id", "user_id"),
        Index("idx_fc_email_account_id", "email_account_id"),
        Index("idx_fc_status", "status"),
        Index("idx_fc_created_at", "created_at"),
        {"schema": FEYRA_SCHEMA},
    )


class CampaignStep(FeyraBase):
    """Email sequence steps within a campaign."""
    __tablename__ = "campaign_steps"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    campaign_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{FEYRA_SCHEMA}.campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    delay_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    subject_template: Mapped[str | None] = mapped_column(String(500), nullable=True)
    body_template: Mapped[str | None] = mapped_column(Text, nullable=True)

    ai_rewrite_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ai_tone: Mapped[AITone | None] = mapped_column(
        Enum(AITone, schema="feyra"), default=AITone.PROFESSIONAL, nullable=True
    )

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
        Index("idx_fcs_campaign_id", "campaign_id"),
        {"schema": FEYRA_SCHEMA},
    )


class CampaignLead(FeyraBase):
    """Junction table linking campaigns to leads."""
    __tablename__ = "campaign_leads"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    campaign_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{FEYRA_SCHEMA}.campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    lead_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{FEYRA_SCHEMA}.leads.id", ondelete="CASCADE"),
        nullable=False,
    )

    current_step: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[CampaignLeadStatus] = mapped_column(
        Enum(CampaignLeadStatus, schema="feyra"), default=CampaignLeadStatus.PENDING, nullable=False
    )

    next_send_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    __table_args__ = (
        Index("idx_fcl_campaign_id", "campaign_id"),
        Index("idx_fcl_lead_id", "lead_id"),
        Index("idx_fcl_status", "status"),
        {"schema": FEYRA_SCHEMA},
    )


class SentEmail(FeyraBase):
    """Every outreach email sent."""
    __tablename__ = "sent_emails"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    campaign_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{FEYRA_SCHEMA}.campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    campaign_lead_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{FEYRA_SCHEMA}.campaign_leads.id", ondelete="CASCADE"),
        nullable=False,
    )
    email_account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{FEYRA_SCHEMA}.email_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )

    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    to_email: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    message_id: Mapped[str | None] = mapped_column(String(500), nullable=True)

    status: Mapped[SentEmailStatus] = mapped_column(
        Enum(SentEmailStatus, schema="feyra"), default=SentEmailStatus.QUEUED, nullable=False
    )
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    bounced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    __table_args__ = (
        Index("idx_fse_campaign_id", "campaign_id"),
        Index("idx_fse_campaign_lead_id", "campaign_lead_id"),
        Index("idx_fse_email_account_id", "email_account_id"),
        Index("idx_fse_status", "status"),
        Index("idx_fse_to_email", "to_email"),
        Index("idx_fse_created_at", "created_at"),
        {"schema": FEYRA_SCHEMA},
    )


class GlobalSettings(FeyraBase):
    """Per-user Feyra settings."""
    __tablename__ = "global_settings"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{FEYRA_SCHEMA}.feyra_users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    default_timezone: Mapped[str] = mapped_column(
        String(50), default="Europe/Stockholm", nullable=False
    )
    default_sending_hours_start: Mapped[int] = mapped_column(Integer, default=8, nullable=False)
    default_sending_hours_end: Mapped[int] = mapped_column(Integer, default=18, nullable=False)

    unsubscribe_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_signature: Mapped[str | None] = mapped_column(Text, nullable=True)

    ai_model_preference: Mapped[AIModelPreference] = mapped_column(
        Enum(AIModelPreference, schema="feyra"), default=AIModelPreference.BALANCED, nullable=False
    )
    ai_default_tone: Mapped[AITone] = mapped_column(
        Enum(AITone, schema="feyra"), default=AITone.PROFESSIONAL, nullable=False
    )
    ai_default_language: Mapped[str] = mapped_column(String(10), default="en", nullable=False)

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
        Index("idx_fgs_user_id", "user_id"),
        {"schema": FEYRA_SCHEMA},
    )
