"""OAuth service — code generation, token exchange, validation."""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.apps.models import App, AppInstallation
from app.oauth.models import (
    OAUTH_CLIENTS,
    VALID_SCOPES,
    OAuthAuthorizationCode,
    OAuthAccessToken,
)
from app.sites.models import GeneratedSite, Lead

logger = logging.getLogger(__name__)

AUTH_CODE_LIFETIME = timedelta(minutes=10)
BLOG_APP_SLUG = "blog"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


# ------------------------------------------------------------------
# Client helpers
# ------------------------------------------------------------------

def validate_client(client_id: str) -> dict | None:
    """Return client config if valid, else None."""
    return OAUTH_CLIENTS.get(client_id)


def validate_scopes(client_id: str, requested: list[str]) -> list[str] | None:
    """Return validated scopes or None if any are invalid."""
    client = validate_client(client_id)
    if not client:
        return None
    allowed = set(client["allowed_scopes"])
    for s in requested:
        if s not in VALID_SCOPES or s not in allowed:
            return None
    return requested


# ------------------------------------------------------------------
# Site listing (for the authorize page)
# ------------------------------------------------------------------

async def get_user_sites_for_oauth(db: AsyncSession, user_id: str) -> list[dict]:
    """Return sites the user can authorize, with blog-app install status."""
    result = await db.execute(
        select(GeneratedSite, Lead)
        .join(Lead, GeneratedSite.lead_id == Lead.id)
        .where(GeneratedSite.claimed_by == user_id)
    )
    rows = result.all()

    # Check blog app installation for each site
    site_ids = [str(site.id) for site, _ in rows]

    blog_app_installed: dict[str, bool] = {}
    if site_ids:
        # Find the blog app
        app_result = await db.execute(
            select(App).where(App.slug == BLOG_APP_SLUG, App.is_active.is_(True))
        )
        blog_app = app_result.scalar_one_or_none()

        if blog_app:
            install_result = await db.execute(
                select(AppInstallation.site_id).where(
                    AppInstallation.app_id == blog_app.id,
                    AppInstallation.site_id.in_(site_ids),
                    AppInstallation.is_active.is_(True),
                )
            )
            installed_site_ids = {row[0] for row in install_result.all()}
            blog_app_installed = {sid: sid in installed_site_ids for sid in site_ids}
        else:
            # Blog app doesn't exist in catalog yet — treat all as not installed
            blog_app_installed = {sid: False for sid in site_ids}

    sites = []
    for site, lead in rows:
        site_data = site.site_data or {}
        business_info = site_data.get("business_info", {})
        sid = str(site.id)
        sites.append({
            "id": sid,
            "subdomain": site.subdomain,
            "business_name": business_info.get("name", lead.business_name or ""),
            "status": site.status.value if hasattr(site.status, "value") else str(site.status),
            "domain": f"{site.subdomain}.qvickosite.com" if site.subdomain else None,
            "blog_app_installed": blog_app_installed.get(sid, False),
        })

    return sites


# ------------------------------------------------------------------
# Authorization code
# ------------------------------------------------------------------

async def create_authorization_code(
    db: AsyncSession,
    *,
    client_id: str,
    user_id: str,
    site_id: str,
    scopes: list[str],
    redirect_uri: str,
    state: str | None = None,
) -> str:
    """Create a short-lived authorization code.  Returns the raw code."""
    raw_code = secrets.token_urlsafe(48)

    code = OAuthAuthorizationCode(
        client_id=client_id,
        user_id=user_id,
        site_id=site_id,
        code_hash=_hash(raw_code),
        scopes=scopes,
        redirect_uri=redirect_uri,
        state=state,
        expires_at=datetime.now(timezone.utc) + AUTH_CODE_LIFETIME,
    )
    db.add(code)
    await db.flush()
    return raw_code


# ------------------------------------------------------------------
# Token exchange
# ------------------------------------------------------------------

async def exchange_code_for_token(
    db: AsyncSession,
    *,
    client_id: str,
    code: str,
    redirect_uri: str,
) -> tuple[str, OAuthAccessToken] | tuple[None, str]:
    """Exchange an authorization code for an access token.

    Returns (raw_token, token_obj) on success or (None, error_message) on failure.
    """
    code_hash = _hash(code)
    result = await db.execute(
        select(OAuthAuthorizationCode).where(
            OAuthAuthorizationCode.code_hash == code_hash,
            OAuthAuthorizationCode.client_id == client_id,
        )
    )
    auth_code = result.scalar_one_or_none()

    if not auth_code:
        return None, "Invalid authorization code"

    if auth_code.used_at is not None:
        return None, "Authorization code already used"

    if auth_code.expires_at < datetime.now(timezone.utc):
        return None, "Authorization code expired"

    if auth_code.redirect_uri != redirect_uri:
        return None, "Redirect URI mismatch"

    # Mark code as used
    auth_code.used_at = datetime.now(timezone.utc)

    # Create access token
    raw_token = secrets.token_urlsafe(48)
    token = OAuthAccessToken(
        client_id=client_id,
        user_id=auth_code.user_id,
        site_id=auth_code.site_id,
        token_hash=_hash(raw_token),
        scopes=auth_code.scopes,
    )
    db.add(token)
    await db.flush()
    await db.refresh(token)

    return raw_token, token


# ------------------------------------------------------------------
# Token validation
# ------------------------------------------------------------------

async def validate_access_token(
    db: AsyncSession, raw_token: str, required_scope: str | None = None,
) -> OAuthAccessToken | None:
    """Validate an access token and optionally check scope."""
    token_hash = _hash(raw_token)
    result = await db.execute(
        select(OAuthAccessToken).where(
            OAuthAccessToken.token_hash == token_hash,
            OAuthAccessToken.revoked_at.is_(None),
        )
    )
    token = result.scalar_one_or_none()
    if not token:
        return None

    if required_scope and required_scope not in (token.scopes or []):
        return None

    return token


# ------------------------------------------------------------------
# Revocation
# ------------------------------------------------------------------

async def revoke_access_token(db: AsyncSession, token_id: str) -> bool:
    """Revoke an access token by its ID."""
    result = await db.execute(
        select(OAuthAccessToken).where(OAuthAccessToken.id == token_id)
    )
    token = result.scalar_one_or_none()
    if not token or token.revoked_at:
        return False
    token.revoked_at = datetime.now(timezone.utc)
    await db.flush()
    return True


async def revoke_tokens_for_site(
    db: AsyncSession, site_id: str, client_id: str | None = None,
) -> int:
    """Revoke all active tokens for a site (optionally filtered by client)."""
    q = select(OAuthAccessToken).where(
        OAuthAccessToken.site_id == site_id,
        OAuthAccessToken.revoked_at.is_(None),
    )
    if client_id:
        q = q.where(OAuthAccessToken.client_id == client_id)
    result = await db.execute(q)
    tokens = result.scalars().all()
    now = datetime.now(timezone.utc)
    for t in tokens:
        t.revoked_at = now
    await db.flush()
    return len(tokens)
