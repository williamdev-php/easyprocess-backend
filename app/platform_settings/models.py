"""Platform-wide settings stored in the database.

Key-value table that lets superusers configure AI models and other
platform-level options without redeploying.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PlatformSetting(Base):
    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )


# Well-known setting keys and their defaults
SETTING_DEFAULTS: dict[str, str] = {
    "ai_model": "claude-haiku-4-5-20251001",
    "image_model": "nano-banana-2",
}
