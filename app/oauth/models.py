"""OAuth provider models for Qvicko.

Allows third-party apps (e.g. AutoBlogger) to request scoped access
to a user's Qvicko site via an OAuth 2.0 authorization-code flow.
"""
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

SCHEMA = "easyprocess"


class OAuthScope(str, enum.Enum):
    BLOG_READ = "blog:read"
    BLOG_WRITE = "blog:write"


VALID_SCOPES = {s.value for s in OAuthScope}

# Hard-coded internal clients.  A full client-registration system is not
# needed yet — AutoBlogger is the only consumer.
OAUTH_CLIENTS: dict[str, dict] = {
    "autoblogger": {
        "name": "AutoBlogger",
        "allowed_scopes": ["blog:read", "blog:write"],
        "allowed_redirect_uris": [
            "https://autoblogger.se/oauth/callback",
            "https://www.autoblogger.se/oauth/callback",
            "http://localhost:3002/oauth/callback",
        ],
    },
}


class OAuthAuthorizationCode(Base):
    """Short-lived authorization code issued during the consent step."""
    __tablename__ = "oauth_authorization_codes"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    client_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), nullable=False
    )
    site_id: Mapped[str] = mapped_column(
        String(36), ForeignKey(f"{SCHEMA}.generated_sites.id", ondelete="CASCADE"), nullable=False
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    scopes: Mapped[list] = mapped_column(JSON, nullable=False)
    redirect_uri: Mapped[str] = mapped_column(String(2000), nullable=False)
    state: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    __table_args__ = (
        Index("idx_oauth_code_expires", "expires_at"),
        {"schema": SCHEMA},
    )


class OAuthAccessToken(Base):
    """Long-lived access token granting scoped access to a site."""
    __tablename__ = "oauth_access_tokens"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    client_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), nullable=False
    )
    site_id: Mapped[str] = mapped_column(
        String(36), ForeignKey(f"{SCHEMA}.generated_sites.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    scopes: Mapped[list] = mapped_column(JSON, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    __table_args__ = (
        Index("idx_oauth_token_user", "user_id"),
        Index("idx_oauth_token_site", "site_id"),
        {"schema": SCHEMA},
    )
