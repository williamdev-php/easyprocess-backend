"""Shopify OAuth endpoints for AutoBlogger source connection."""
from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.autoblogger.auth_dependencies import get_current_autoblogger_user
from app.autoblogger.models import AutoBloggerUser
from app.autoblogger.integrations.shopify import (
    build_oauth_url,
    exchange_oauth_code,
    list_blogs,
    test_connection,
    _normalize_shop_domain,
)
from app.autoblogger.encryption import decrypt_platform_config, encrypt_platform_config
from app.autoblogger.models import PlatformType, Source
from app.cache import cache
from app.config import settings
from app.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/autoblogger/sources/shopify", tags=["autoblogger-shopify"])

_OAUTH_STATE_PREFIX = "autoblogger:shopify_oauth:"
_OAUTH_STATE_TTL = 600  # 10 minutes


class ShopifyConnectRequest(BaseModel):
    shop_domain: str
    source_name: str = "My Shopify Blog"


class ShopifyCallbackParams(BaseModel):
    code: str
    shop: str
    state: str


@router.post("/connect")
async def initiate_shopify_connect(
    body: ShopifyConnectRequest,
    request: Request,
    user: AutoBloggerUser = Depends(get_current_autoblogger_user),
):
    """Initiate Shopify OAuth — returns the authorization URL."""
    if not settings.SHOPIFY_API_KEY or not settings.SHOPIFY_API_SECRET:
        raise HTTPException(status_code=501, detail="Shopify integration not configured")

    state = secrets.token_urlsafe(32)
    callback_url = f"{settings.AUTOBLOGGER_FRONTEND_URL}/dashboard/sources/shopify/callback"

    await cache.set(
        f"{_OAUTH_STATE_PREFIX}{state}",
        {
            "user_id": str(user.id),
            "shop_domain": body.shop_domain,
            "source_name": body.source_name,
        },
        ttl=_OAUTH_STATE_TTL,
    )

    auth_url = build_oauth_url(body.shop_domain, state, callback_url)
    return {"auth_url": auth_url, "state": state}


@router.get("/callback")
async def shopify_oauth_callback(
    code: str = Query(...),
    shop: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Handle Shopify OAuth callback — exchange code for access token and create source."""
    cache_key = f"{_OAUTH_STATE_PREFIX}{state}"
    state_data = await cache.get(cache_key)
    if state_data:
        await cache.delete(cache_key)
    if not state_data:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    user_id = state_data["user_id"]
    source_name = state_data["source_name"]

    # Exchange code for access token
    try:
        token_data = await exchange_oauth_code(shop, code)
    except Exception as e:
        logger.error("Shopify OAuth exchange failed: %s", e)
        raise HTTPException(status_code=400, detail="Failed to exchange OAuth code")

    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="No access token received from Shopify")

    # Fetch available blogs
    try:
        blogs = await list_blogs(shop, access_token)
    except Exception:
        blogs = []

    default_blog_id = blogs[0]["id"] if blogs else None

    # Create the source (encrypt sensitive fields like access_token at rest)
    normalized_shop = _normalize_shop_domain(shop)
    source = Source(
        user_id=user_id,
        name=source_name,
        platform=PlatformType.SHOPIFY,
        platform_url=f"https://{normalized_shop}",
        platform_config=encrypt_platform_config({
            "access_token": access_token,
            "shop_domain": normalized_shop,
            "blog_id": default_blog_id,
            "blogs": [{"id": b["id"], "title": b["title"]} for b in blogs],
        }),
    )
    db.add(source)
    await db.flush()
    await db.refresh(source)

    # Redirect to frontend sources page with success
    return {
        "source_id": source.id,
        "shop_name": normalized_shop,
        "blogs": [{"id": b["id"], "title": b["title"]} for b in blogs],
    }


@router.get("/blogs/{source_id}")
async def get_shopify_blogs(
    source_id: str,
    user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
):
    """List available blogs for a connected Shopify source."""
    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.user_id == user.id)
    )
    source = result.scalar_one_or_none()
    if not source or source.platform != PlatformType.SHOPIFY:
        raise HTTPException(status_code=404, detail="Shopify source not found")

    config = decrypt_platform_config(source.platform_config) or {}
    access_token = config.get("access_token")
    shop_domain = config.get("shop_domain")

    if not access_token or not shop_domain:
        raise HTTPException(status_code=400, detail="Shopify credentials missing")

    blogs = await list_blogs(shop_domain, access_token)
    return {"blogs": [{"id": b["id"], "title": b["title"]} for b in blogs]}


@router.patch("/blogs/{source_id}")
async def set_shopify_blog(
    source_id: str,
    body: dict,
    user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
):
    """Set which Shopify blog to publish to."""
    blog_id = body.get("blog_id")
    if not blog_id:
        raise HTTPException(status_code=400, detail="blog_id is required")

    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.user_id == user.id)
    )
    source = result.scalar_one_or_none()
    if not source or source.platform != PlatformType.SHOPIFY:
        raise HTTPException(status_code=404, detail="Shopify source not found")

    config = source.platform_config or {}
    config["blog_id"] = blog_id
    source.platform_config = config
    await db.flush()

    return {"blog_id": blog_id}


@router.post("/test/{source_id}")
async def test_shopify_connection(
    source_id: str,
    user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
):
    """Test connection to a Shopify store."""
    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.user_id == user.id)
    )
    source = result.scalar_one_or_none()
    if not source or source.platform != PlatformType.SHOPIFY:
        raise HTTPException(status_code=404, detail="Shopify source not found")

    config = decrypt_platform_config(source.platform_config) or {}
    access_token = config.get("access_token")
    shop_domain = config.get("shop_domain")

    if not access_token or not shop_domain:
        raise HTTPException(status_code=400, detail="Shopify credentials missing")

    try:
        info = await test_connection(shop_domain, access_token)
        return {"connected": True, **info}
    except Exception as e:
        return {"connected": False, "error": str(e)}
