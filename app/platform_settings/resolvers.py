"""GraphQL resolvers for platform settings (superuser only)."""

from __future__ import annotations

import strawberry
from strawberry.types import Info

from app.auth.resolvers import _get_user_from_info, _require_user
from app.database import get_db_session
from app.platform_settings.graphql_types import (
    PlatformSettingType,
    UpdatePlatformSettingInput,
)
from app.platform_settings.service import get_all_settings, upsert_setting

# Keys that superusers are allowed to modify
ALLOWED_KEYS = {"ai_model", "image_model"}

# Valid values per key
VALID_VALUES: dict[str, set[str]] = {
    "ai_model": {
        "claude-haiku-4-5-20251001",
        "gemini-2.5-flash",
    },
    "image_model": {
        "nano-banana",
        "nano-banana-2",
        "nano-banana-pro",
    },
}


@strawberry.type
class PlatformSettingsQuery:

    @strawberry.field
    async def platform_settings(self, info: Info) -> list[PlatformSettingType]:
        """Return all platform settings (superuser only)."""
        user = _require_user(await _get_user_from_info(info))
        if not user.is_superuser:
            raise PermissionError("Superuser access required")

        async with get_db_session() as db:
            settings = await get_all_settings(db)
            return [
                PlatformSettingType(key=k, value=v)
                for k, v in sorted(settings.items())
            ]


@strawberry.type
class PlatformSettingsMutation:

    @strawberry.mutation
    async def update_platform_setting(
        self, info: Info, input: UpdatePlatformSettingInput
    ) -> PlatformSettingType:
        """Update a single platform setting (superuser only)."""
        user = _require_user(await _get_user_from_info(info))
        if not user.is_superuser:
            raise PermissionError("Superuser access required")

        if input.key not in ALLOWED_KEYS:
            raise ValueError(f"Unknown setting key: {input.key}")

        valid = VALID_VALUES.get(input.key)
        if valid and input.value not in valid:
            raise ValueError(
                f"Invalid value '{input.value}' for '{input.key}'. "
                f"Allowed: {', '.join(sorted(valid))}"
            )

        async with get_db_session() as db:
            setting = await upsert_setting(db, input.key, input.value)
            return PlatformSettingType(key=setting.key, value=setting.value)
