"""Google Search Console integration service.

Handles OAuth token exchange, token refresh, site property management,
sitemap submission, and indexing notifications.
"""

import logging
from datetime import datetime, timezone, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.sites.models import (
    CustomDomain,
    DomainStatus,
    GscConnection,
    GscConnectionStatus,
)

logger = logging.getLogger(__name__)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"

# Search Console API
GSC_SITES_URL = "https://www.googleapis.com/webmasters/v3/sites"

# Scopes needed for Search Console management
GSC_SCOPES = [
    "https://www.googleapis.com/auth/webmasters",
    "https://www.googleapis.com/auth/userinfo.email",
]


async def exchange_gsc_code(code: str, redirect_uri: str) -> dict:
    """Exchange an authorization code for GSC tokens + user info.

    Returns dict with: access_token, refresh_token, expires_in, email.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if token_resp.status_code != 200:
            logger.warning("GSC token exchange failed: %s", token_resp.text)
            raise ValueError("Failed to exchange authorization code")

        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")

        if not access_token:
            raise ValueError("No access token in response")
        if not refresh_token:
            raise ValueError(
                "No refresh token — user may need to re-authorize with prompt=consent"
            )

        # Fetch email
        userinfo_resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        email = ""
        if userinfo_resp.status_code == 200:
            email = userinfo_resp.json().get("email", "")

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": token_data.get("expires_in", 3600),
            "email": email,
        }


async def refresh_access_token(connection: GscConnection) -> str:
    """Refresh an expired access token using the stored refresh token.

    Updates the connection in-place and returns the new access token.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "refresh_token": connection.refresh_token,
                "grant_type": "refresh_token",
            },
        )
        if resp.status_code != 200:
            logger.warning("GSC token refresh failed: %s", resp.text)
            connection.status = GscConnectionStatus.EXPIRED
            raise ValueError("Failed to refresh token — user must reconnect")

        data = resp.json()
        connection.access_token = data["access_token"]
        connection.token_expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=data.get("expires_in", 3600)
        )
        return connection.access_token


async def _get_valid_token(connection: GscConnection) -> str:
    """Return a valid access token, refreshing if needed."""
    if (
        connection.token_expires_at
        and connection.token_expires_at > datetime.now(timezone.utc) + timedelta(minutes=2)
    ):
        return connection.access_token
    return await refresh_access_token(connection)


async def add_site_to_gsc(connection: GscConnection, domain: str) -> bool:
    """Add a domain as a URL-prefix property in Google Search Console.

    Uses format: https://domain/
    """
    token = await _get_valid_token(connection)
    site_url = f"https://{domain}/"
    encoded = httpx.URL(f"{GSC_SITES_URL}/{site_url}")

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.put(
            str(encoded),
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code in (200, 204):
            logger.info("Added site %s to GSC", domain)
            return True
        logger.warning("Failed to add site %s to GSC: %s %s", domain, resp.status_code, resp.text)
        return False


async def submit_sitemap(connection: GscConnection, domain: str) -> bool:
    """Submit the sitemap URL to Google Search Console."""
    token = await _get_valid_token(connection)
    site_url = f"https://{domain}/"
    sitemap_url = f"https://{domain}/sitemap.xml"

    url = f"{GSC_SITES_URL}/{httpx.QueryParams({'siteUrl': site_url})}/sitemaps/{sitemap_url}"
    # The API expects: PUT /sites/{siteUrl}/sitemaps/{feedpath}
    # We need to properly encode the URLs
    api_url = f"https://www.googleapis.com/webmasters/v3/sites/{site_url}/sitemaps/{sitemap_url}"

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.put(
            api_url,
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code in (200, 204):
            logger.info("Submitted sitemap for %s", domain)
            return True
        logger.warning(
            "Failed to submit sitemap for %s: %s %s",
            domain, resp.status_code, resp.text,
        )
        return False


async def index_domain(
    db: AsyncSession,
    connection: GscConnection,
    domain: str,
) -> dict:
    """Full indexing flow: add site property + submit sitemap.

    Returns a status dict.
    """
    results = {"site_added": False, "sitemap_submitted": False}

    try:
        results["site_added"] = await add_site_to_gsc(connection, domain)
    except Exception:
        logger.exception("Error adding site to GSC for %s", domain)

    if results["site_added"]:
        try:
            results["sitemap_submitted"] = await submit_sitemap(connection, domain)
        except Exception:
            logger.exception("Error submitting sitemap for %s", domain)

    # Update connection record
    if results["site_added"]:
        connection.indexed_domain = domain
        connection.indexed_at = datetime.now(timezone.utc)

    return results


async def get_user_verified_domain(db: AsyncSession, user_id: str) -> str | None:
    """Get the user's first verified custom domain, if any."""
    result = await db.execute(
        select(CustomDomain)
        .where(
            CustomDomain.user_id == user_id,
            CustomDomain.status == DomainStatus.ACTIVE,
            CustomDomain.verified_at.isnot(None),
        )
        .order_by(CustomDomain.verified_at)
        .limit(1)
    )
    domain = result.scalar_one_or_none()
    return domain.domain if domain else None


async def get_gsc_connection(db: AsyncSession, user_id: str) -> GscConnection | None:
    """Get the user's GSC connection."""
    result = await db.execute(
        select(GscConnection).where(GscConnection.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def revoke_gsc_connection(connection: GscConnection) -> None:
    """Revoke Google OAuth tokens."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                GOOGLE_REVOKE_URL,
                params={"token": connection.refresh_token},
            )
    except Exception:
        logger.warning("Failed to revoke GSC token (non-critical)")
