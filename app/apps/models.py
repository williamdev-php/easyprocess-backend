import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

SCHEMA = "easyprocess"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class BlogPostStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class ChatConversationStatus(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"


class ChatSenderType(str, enum.Enum):
    VISITOR = "visitor"
    AGENT = "agent"


class AppPricingType(str, enum.Enum):
    FREE = "FREE"
    ONE_TIME = "ONE_TIME"
    MONTHLY = "MONTHLY"
    USAGE = "USAGE"


# ---------------------------------------------------------------------------
# App catalog
# ---------------------------------------------------------------------------

class App(Base):
    """Registry of available apps (internal catalog)."""
    __tablename__ = "apps"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    slug: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    long_description: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    icon_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    scopes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    sidebar_links: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Showcase fields
    screenshots: Mapped[list | None] = mapped_column(JSON, nullable=True)
    features: Mapped[list | None] = mapped_column(JSON, nullable=True)
    developer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    developer_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Pricing
    pricing_type: Mapped[AppPricingType] = mapped_column(
        Enum(AppPricingType), default=AppPricingType.FREE, nullable=False
    )
    price: Mapped[float] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    price_description: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Stats
    install_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    installations: Mapped[list["AppInstallation"]] = relationship(
        "AppInstallation", back_populates="app", cascade="all, delete-orphan"
    )
    reviews: Mapped[list["AppReview"]] = relationship(
        "AppReview", back_populates="app", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_apps_slug", "slug"),
        {"schema": SCHEMA},
    )


# ---------------------------------------------------------------------------
# Per-site app installation
# ---------------------------------------------------------------------------

class AppInstallation(Base):
    """Tracks which apps are installed on which sites."""
    __tablename__ = "app_installations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    app_id: Mapped[str] = mapped_column(
        String(36), ForeignKey(f"{SCHEMA}.apps.id", ondelete="CASCADE"), nullable=False
    )
    site_id: Mapped[str] = mapped_column(
        String(36), ForeignKey(f"{SCHEMA}.generated_sites.id", ondelete="CASCADE"), nullable=False
    )
    installed_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey(f"{SCHEMA}.users.id", ondelete="SET NULL"), nullable=True
    )
    settings: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    app: Mapped[App] = relationship("App", back_populates="installations")

    __table_args__ = (
        UniqueConstraint("app_id", "site_id", name="uq_app_installations_app_site"),
        Index("idx_app_installations_app_id", "app_id"),
        Index("idx_app_installations_site_id", "site_id"),
        {"schema": SCHEMA},
    )


# ---------------------------------------------------------------------------
# App reviews
# ---------------------------------------------------------------------------

class AppReview(Base):
    """User review for an app. Requires the app to be installed."""
    __tablename__ = "app_reviews"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    app_id: Mapped[str] = mapped_column(
        String(36), ForeignKey(f"{SCHEMA}.apps.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), nullable=False
    )
    site_id: Mapped[str] = mapped_column(
        String(36), ForeignKey(f"{SCHEMA}.generated_sites.id", ondelete="CASCADE"), nullable=False
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    locale: Mapped[str | None] = mapped_column(String(10), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    app: Mapped[App] = relationship("App", back_populates="reviews")

    __table_args__ = (
        UniqueConstraint("app_id", "user_id", "site_id", name="uq_app_reviews_app_user_site"),
        Index("idx_app_reviews_app_id", "app_id"),
        Index("idx_app_reviews_user_id", "user_id"),
        {"schema": SCHEMA},
    )


# ---------------------------------------------------------------------------
# Blog categories
# ---------------------------------------------------------------------------

class BlogCategory(Base):
    """Blog category scoped to a site."""
    __tablename__ = "blog_categories"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    site_id: Mapped[str] = mapped_column(
        String(36), ForeignKey(f"{SCHEMA}.generated_sites.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    posts: Mapped[list["BlogPost"]] = relationship(
        "BlogPost", back_populates="category", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("site_id", "slug", name="uq_blog_categories_site_slug"),
        Index("idx_blog_categories_site_id", "site_id"),
        {"schema": SCHEMA},
    )


# ---------------------------------------------------------------------------
# Blog posts
# ---------------------------------------------------------------------------

class BlogPost(Base):
    """Blog post scoped to a site."""
    __tablename__ = "blog_posts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    site_id: Mapped[str] = mapped_column(
        String(36), ForeignKey(f"{SCHEMA}.generated_sites.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey(f"{SCHEMA}.blog_categories.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    slug: Mapped[str] = mapped_column(String(500), nullable=False)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    featured_image: Mapped[str | None] = mapped_column(String(500), nullable=True)
    author_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    author_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey(f"{SCHEMA}.users.id", ondelete="SET NULL"), nullable=True
    )

    status: Mapped[BlogPostStatus] = mapped_column(
        Enum(BlogPostStatus), default=BlogPostStatus.DRAFT, nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    category: Mapped[BlogCategory | None] = relationship("BlogCategory", back_populates="posts")

    __table_args__ = (
        UniqueConstraint("site_id", "slug", name="uq_blog_posts_site_slug"),
        Index("idx_blog_posts_site_id", "site_id"),
        Index("idx_blog_posts_status", "status"),
        Index("idx_blog_posts_published_at", "published_at"),
        Index("idx_blog_posts_category_id", "category_id"),
        Index("idx_blog_posts_site_status", "site_id", "status"),
        {"schema": SCHEMA},
    )


# ---------------------------------------------------------------------------
# Chat conversations
# ---------------------------------------------------------------------------

class ChatConversation(Base):
    """Chat conversation scoped to a site."""
    __tablename__ = "chat_conversations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    site_id: Mapped[str] = mapped_column(
        String(36), ForeignKey(f"{SCHEMA}.generated_sites.id", ondelete="CASCADE"), nullable=False
    )
    visitor_email: Mapped[str] = mapped_column(String(320), nullable=False)
    visitor_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    messages: Mapped[list["ChatMessage"]] = relationship(
        "ChatMessage", back_populates="conversation", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_chat_conversations_site_id", "site_id"),
        Index("idx_chat_conversations_status", "status"),
        Index("idx_chat_conversations_site_status", "site_id", "status"),
        Index("idx_chat_conversations_visitor_email", "visitor_email"),
        {"schema": SCHEMA},
    )


# ---------------------------------------------------------------------------
# Chat messages
# ---------------------------------------------------------------------------

class ChatMessage(Base):
    """Individual message within a chat conversation."""
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey(f"{SCHEMA}.chat_conversations.id", ondelete="CASCADE"), nullable=False
    )
    sender_type: Mapped[str] = mapped_column(String(20), nullable=False)
    sender_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    conversation: Mapped[ChatConversation] = relationship("ChatConversation", back_populates="messages")

    __table_args__ = (
        Index("idx_chat_messages_conversation_id", "conversation_id"),
        Index("idx_chat_messages_created_at", "created_at"),
        {"schema": SCHEMA},
    )
