from __future__ import annotations

import strawberry


@strawberry.type
class PlatformSettingType:
    key: str
    value: str


@strawberry.input
class UpdatePlatformSettingInput:
    key: str
    value: str
