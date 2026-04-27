"""OAuth provider endpoints for Qvicko.

These endpoints power the authorization-code flow that lets third-party
apps (like AutoBlogger) request scoped access to a user's Qvicko site.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.database import get_db
from app.oauth.models import OAUTH_CLIENTS
from app.oauth.service import (
    create_authorization_code,
    exchange_code_for_token,
    get_user_sites_for_oauth,
    revoke_access_token,
    validate_client,
    validate_redirect_uri,
    validate_scopes,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/oauth", tags=["oauth"])


# ------------------------------------------------------------------
# Schemas
# ------------------------------------------------------------------

class AuthorizeRequest(BaseModel):
    """Sent by the frontend when the user clicks 'Authorize'."""
    client_id: str
    site_id: str
    scopes: list[str]
    redirect_uri: str
    state: str | None = None


class TokenRequest(BaseModel):
    """Code-for-token exchange (called by the requesting app's backend)."""
    client_id: str
    code: str
    redirect_uri: str


class RevokeRequest(BaseModel):
    token_id: str


# ------------------------------------------------------------------
# 1. Client info  (public — the authorize page needs it before login)
# ------------------------------------------------------------------

@router.get("/client/{client_id}")
async def get_client_info(client_id: str):
    """Return public metadata about an OAuth client."""
    client = validate_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Unknown client")
    return {
        "client_id": client_id,
        "name": client["name"],
        "allowed_scopes": client["allowed_scopes"],
    }


# ------------------------------------------------------------------
# 2. List user's sites (authorize page — requires auth)
# ------------------------------------------------------------------

@router.get("/sites")
async def list_sites(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List sites the current user can authorize, with blog-app status."""
    sites = await get_user_sites_for_oauth(db, user.id)
    return {"sites": sites}


# ------------------------------------------------------------------
# 3. Authorize  (user consents — creates auth code)
# ------------------------------------------------------------------

@router.post("/authorize")
async def authorize(
    body: AuthorizeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """User consents to granting the app access to a site.

    Returns an authorization code that the app exchanges for a token.
    """
    client = validate_client(body.client_id)
    if not client:
        raise HTTPException(status_code=400, detail="Unknown client_id")

    scopes = validate_scopes(body.client_id, body.scopes)
    if scopes is None:
        raise HTTPException(status_code=400, detail="Invalid scopes")

    if not validate_redirect_uri(body.client_id, body.redirect_uri):
        raise HTTPException(status_code=400, detail="Invalid redirect_uri")

    raw_code = await create_authorization_code(
        db,
        client_id=body.client_id,
        user_id=user.id,
        site_id=body.site_id,
        scopes=scopes,
        redirect_uri=body.redirect_uri,
        state=body.state,
    )

    return {"code": raw_code, "state": body.state}


# ------------------------------------------------------------------
# 4. Token exchange  (app backend calls this)
# ------------------------------------------------------------------

@router.post("/token")
async def token_exchange(
    body: TokenRequest,
    db: AsyncSession = Depends(get_db),
):
    """Exchange an authorization code for an access token."""
    if not validate_redirect_uri(body.client_id, body.redirect_uri):
        raise HTTPException(status_code=400, detail="Invalid redirect_uri")

    result = await exchange_code_for_token(
        db,
        client_id=body.client_id,
        code=body.code,
        redirect_uri=body.redirect_uri,
    )

    if result[0] is None:
        raise HTTPException(status_code=400, detail=result[1])

    raw_token, token_obj = result
    return {
        "access_token": raw_token,
        "token_type": "Bearer",
        "scope": " ".join(token_obj.scopes),
        "site_id": token_obj.site_id,
    }


# ------------------------------------------------------------------
# 5. Revoke  (user or app revokes a token)
# ------------------------------------------------------------------

@router.post("/revoke")
async def revoke(
    body: RevokeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke an OAuth access token."""
    ok = await revoke_access_token(db, body.token_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Token not found or already revoked")
    return {"revoked": True}
