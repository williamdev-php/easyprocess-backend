"""CRUD helpers for platform settings."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform_settings.models import PlatformSetting, SETTING_DEFAULTS


async def get_setting(db: AsyncSession, key: str) -> str:
    """Return the value for *key*, falling back to the compiled default."""
    result = await db.execute(
        select(PlatformSetting.value).where(PlatformSetting.key == key)
    )
    value = result.scalar_one_or_none()
    if value is not None:
        return value
    return SETTING_DEFAULTS.get(key, "")


async def get_all_settings(db: AsyncSession) -> dict[str, str]:
    """Return all settings merged with defaults."""
    result = await db.execute(select(PlatformSetting))
    rows = {row.key: row.value for row in result.scalars().all()}
    merged = {**SETTING_DEFAULTS, **rows}
    return merged


async def upsert_setting(db: AsyncSession, key: str, value: str) -> PlatformSetting:
    """Create or update a single setting."""
    result = await db.execute(
        select(PlatformSetting).where(PlatformSetting.key == key)
    )
    setting = result.scalar_one_or_none()
    if setting is None:
        setting = PlatformSetting(key=key, value=value)
        db.add(setting)
    else:
        setting.value = value
    await db.flush()
    return setting
