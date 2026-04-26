"""Qvicko source connection endpoints for AutoBlogger.

Uses OAuth to get scoped access to a user's Qvicko site for blog operations.
"""
from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.autoblogger.auth_dependencies import get_current_autoblogger_user
from app.autoblogger.encryption import encrypt_platform_config
from app.autoblogger.models import AutoBloggerUser, PlatformType, Source
from app.cache import cache
from app.config import settings
from app.database import get_db
from app.oauth.service import exchange_code_for_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/autoblogger/sources/qvicko", tags=["autoblogger-qvicko"])

_OAUTH_STATE_PREFIX = "autoblogger:qvicko_oauth:"
_OAUTH_STATE_TTL = 600  # 10 minutes
_OAUTH_CLIENT_ID = "autoblogger"
_OAUTH_SCOPES = "blog:read+blog:write"


class QvickoOAuthInitiateRequest(BaseModel):
    pass


class QvickoOAuthCallbackRequest(BaseModel):
    code: str
    state: str | None = None


@router.post("/oauth/initiate")
async def initiate_qvicko_oauth(
    body: QvickoOAuthInitiateRequest,
    user: AutoBloggerUser = Depends(get_current_autoblogger_user),
):
    """Start the OAuth flow — returns the Qvicko authorize URL."""
    state = secrets.token_urlsafe(32)
    callback_url = f"{settings.AUTOBLOGGER_FRONTEND_URL}/dashboard/sources/qvicko/callback"

    # Store state in cache so we can validate on callback
    await cache.set(
        f"{_OAUTH_STATE_PREFIX}{state}",
        {
            "user_id": str(user.id),
        },
        ttl=_OAUTH_STATE_TTL,
    )

    # Build the Qvicko OAuth authorize URL
    authorize_url = (
        f"{settings.FRONTEND_URL}/oauth/authorize"
        f"?client_id={_OAUTH_CLIENT_ID}"
        f"&scope={_OAUTH_SCOPES}"
        f"&redirect_uri={callback_url}"
        f"&state={state}"
    )

    return {"authorize_url": authorize_url, "state": state}


@router.post("/oauth/callback")
async def qvicko_oauth_callback(
    body: QvickoOAuthCallbackRequest,
    user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
):
    """Handle the OAuth callback — exchange code for token and create source."""
    # Validate state
    if body.state:
        cache_key = f"{_OAUTH_STATE_PREFIX}{body.state}"
        state_data = await cache.get(cache_key)
        if state_data:
            await cache.delete(cache_key)
        if not state_data:
            raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
        if state_data["user_id"] != str(user.id):
            raise HTTPException(status_code=403, detail="State does not match user")

    # Exchange the authorization code for an access token
    callback_url = f"{settings.AUTOBLOGGER_FRONTEND_URL}/dashboard/sources/qvicko/callback"
    result = await exchange_code_for_token(
        db,
        client_id=_OAUTH_CLIENT_ID,
        code=body.code,
        redirect_uri=callback_url,
    )

    if result[0] is None:
        raise HTTPException(status_code=400, detail=result[1])

    raw_token, token_obj = result

    # Get site info from the token
    from app.sites.models import GeneratedSite, Lead
    site_result = await db.execute(
        select(GeneratedSite, Lead)
        .join(Lead, GeneratedSite.lead_id == Lead.id)
        .where(GeneratedSite.id == token_obj.site_id)
    )
    row = site_result.first()
    if not row:
        raise HTTPException(status_code=400, detail="Authorized site not found")

    site, lead = row
    site_data = site.site_data or {}
    business_info = site_data.get("business_info", {})
    business_name = business_info.get("name", lead.business_name or "")

    source_name = business_name if business_name else "Qvicko"

    # Create the source with encrypted OAuth token
    source = Source(
        user_id=user.id,
        name=source_name,
        platform=PlatformType.QVICKO,
        platform_url=f"https://{site.subdomain}.qvickosite.com" if site.subdomain else "",
        platform_config=encrypt_platform_config({
            "site_id": str(site.id),
            "subdomain": site.subdomain,
            "business_name": business_name,
            "oauth_access_token": raw_token,
            "oauth_token_id": token_obj.id,
            "scopes": token_obj.scopes,
        }),
    )
    db.add(source)
    await db.flush()
    await db.refresh(source)

    logger.info(
        "Qvicko OAuth source created: user=%s site=%s source=%s",
        user.id, site.id, source.id,
    )

    return {
        "id": source.id,
        "name": source.name,
        "platform": source.platform.value,
        "platform_url": source.platform_url,
        "platform_config": {
            "subdomain": site.subdomain,
            "business_name": business_name,
        },
        "is_active": source.is_active,
        "created_at": source.created_at.isoformat(),
    }
