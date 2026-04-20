"""In-app notifications for support tickets and other events."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

SCHEMA = "easyprocess"


class NotificationType(str, enum.Enum):
    TICKET_CREATED = "TICKET_CREATED"
    TICKET_REPLIED = "TICKET_REPLIED"
    TICKET_STATUS_CHANGED = "TICKET_STATUS_CHANGED"


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    __table_args__ = (
        Index("idx_notifications_user_id", "user_id"),
        Index("idx_notifications_user_unread", "user_id", "is_read"),
        Index("idx_notifications_created_at", "created_at"),
        {"schema": SCHEMA},
    )
