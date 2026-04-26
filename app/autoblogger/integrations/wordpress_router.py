"""WordPress (Custom) source connection endpoints for AutoBlogger."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.autoblogger.auth_dependencies import get_current_autoblogger_user
from app.autoblogger.models import AutoBloggerUser
from app.autoblogger.encryption import decrypt_platform_config, encrypt_platform_config
from app.autoblogger.integrations.wordpress import test_connection
from app.autoblogger.models import PlatformType, Source
from app.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/autoblogger/sources/wordpress", tags=["autoblogger-wordpress"])


class WordPressConnectRequest(BaseModel):
    source_name: str = Field(..., max_length=255)
    api_url: str = Field(..., max_length=1000)  # e.g. "https://myblog.com"
    username: str = Field(..., max_length=255)
    app_password: str = Field(..., max_length=255)


@router.post("/connect")
async def connect_wordpress(
    body: WordPressConnectRequest,
    user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
):
    """Connect a WordPress site as an AutoBlogger source.

    Tests the connection first, then creates the source.
    """
    # Test connection
    try:
        info = await test_connection(body.api_url, body.username, body.app_password)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"WordPress connection failed: {e}")

    # Create source (encrypt sensitive fields like app_password at rest)
    source = Source(
        user_id=user.id,
        name=body.source_name,
        platform=PlatformType.CUSTOM,
        platform_url=body.api_url,
        platform_config=encrypt_platform_config({
            "api_url": body.api_url,
            "username": body.username,
            "app_password": body.app_password,
            "site_name": info.get("site_name", ""),
        }),
    )
    db.add(source)
    await db.flush()
    await db.refresh(source)

    return {
        "source_id": source.id,
        "site_name": info.get("site_name", ""),
        "connected": True,
    }


@router.post("/test/{source_id}")
async def test_wordpress_connection(
    source_id: str,
    user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
):
    """Test connection to a WordPress site."""
    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.user_id == user.id)
    )
    source = result.scalar_one_or_none()
    if not source or source.platform != PlatformType.CUSTOM:
        raise HTTPException(status_code=404, detail="WordPress source not found")

    config = decrypt_platform_config(source.platform_config) or {}
    try:
        info = await test_connection(
            config.get("api_url", ""),
            config.get("username", ""),
            config.get("app_password", ""),
        )
        return {"connected": True, **info}
    except Exception as e:
        return {"connected": False, "error": str(e)}


@router.post("/test")
async def test_wordpress_credentials(
    body: WordPressConnectRequest,
    user: AutoBloggerUser = Depends(get_current_autoblogger_user),
):
    """Test WordPress credentials before creating a source."""
    try:
        info = await test_connection(body.api_url, body.username, body.app_password)
        return {"connected": True, **info}
    except Exception as e:
        return {"connected": False, "error": str(e)}
