"""REST endpoints for Google Search Console integration.

Handles OAuth callback, connection status, disconnection, and manual indexing trigger.
"""

import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.config import settings
from app.database import get_db
from app.rate_limit import limiter
from app.sites.models import GscConnection, GscConnectionStatus

from app.gsc.service import (
    exchange_gsc_code,
    get_gsc_connection,
    get_user_verified_domain,
    index_domain,
    revoke_gsc_connection,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/gsc", tags=["gsc"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class GscConnectRequest(BaseModel):
    code: str
    redirect_uri: str


class GscConnectionResponse(BaseModel):
    connected: bool
    google_email: str | None = None
    indexed_domain: str | None = None
    indexed_at: str | None = None
    status: str | None = None


class GscIndexResponse(BaseModel):
    site_added: bool
    sitemap_submitted: bool
    domain: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/connect", response_model=GscConnectionResponse)
@limiter.limit("10/minute")
async def connect_gsc(
    body: GscConnectRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GscConnectionResponse:
    """Exchange Google OAuth code and store GSC connection.

    After connecting, automatically indexes the user's verified custom domain.
    """
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=501, detail="Google OAuth is not configured")

    # Check if user has a verified custom domain
    domain = await get_user_verified_domain(db, str(user.id))
    if not domain:
        raise HTTPException(
            status_code=400,
            detail="You need a verified custom domain before connecting Google Search Console",
        )

    try:
        token_data = await exchange_gsc_code(body.code, body.redirect_uri)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Upsert connection
    existing = await get_gsc_connection(db, str(user.id))
    if existing:
        existing.access_token = token_data["access_token"]
        existing.refresh_token = token_data["refresh_token"]
        existing.token_expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=token_data["expires_in"]
        )
        existing.google_email = token_data["email"]
        existing.status = GscConnectionStatus.CONNECTED
        connection = existing
    else:
        connection = GscConnection(
            user_id=str(user.id),
            google_email=token_data["email"],
            access_token=token_data["access_token"],
            refresh_token=token_data["refresh_token"],
            token_expires_at=datetime.now(timezone.utc) + timedelta(
                seconds=token_data["expires_in"]
            ),
            status=GscConnectionStatus.CONNECTED,
        )
        db.add(connection)

    await db.flush()

    # Auto-index the domain
    results = await index_domain(db, connection, domain)
    await db.flush()

    logger.info(
        "GSC connected for user %s, domain %s: site_added=%s, sitemap=%s",
        user.id, domain, results["site_added"], results["sitemap_submitted"],
    )

    return GscConnectionResponse(
        connected=True,
        google_email=connection.google_email,
        indexed_domain=connection.indexed_domain,
        indexed_at=connection.indexed_at.isoformat() if connection.indexed_at else None,
        status=connection.status.value,
    )


@router.get("/status", response_model=GscConnectionResponse)
async def gsc_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GscConnectionResponse:
    """Get the current user's GSC connection status."""
    connection = await get_gsc_connection(db, str(user.id))
    if not connection or connection.status != GscConnectionStatus.CONNECTED:
        return GscConnectionResponse(connected=False)

    return GscConnectionResponse(
        connected=True,
        google_email=connection.google_email,
        indexed_domain=connection.indexed_domain,
        indexed_at=connection.indexed_at.isoformat() if connection.indexed_at else None,
        status=connection.status.value,
    )


@router.post("/disconnect")
@limiter.limit("5/minute")
async def disconnect_gsc(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Disconnect Google Search Console and revoke tokens."""
    connection = await get_gsc_connection(db, str(user.id))
    if not connection:
        raise HTTPException(status_code=404, detail="No GSC connection found")

    await revoke_gsc_connection(connection)
    await db.delete(connection)
    await db.flush()

    logger.info("GSC disconnected for user %s", user.id)
    return {"disconnected": True}


@router.post("/index", response_model=GscIndexResponse)
@limiter.limit("5/minute")
async def trigger_index(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GscIndexResponse:
    """Manually trigger indexing for the user's verified domain."""
    connection = await get_gsc_connection(db, str(user.id))
    if not connection or connection.status != GscConnectionStatus.CONNECTED:
        raise HTTPException(status_code=400, detail="GSC is not connected")

    domain = await get_user_verified_domain(db, str(user.id))
    if not domain:
        raise HTTPException(status_code=400, detail="No verified custom domain found")

    results = await index_domain(db, connection, domain)
    await db.flush()

    return GscIndexResponse(
        site_added=results["site_added"],
        sitemap_submitted=results["sitemap_submitted"],
        domain=domain,
    )
