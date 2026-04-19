"""
Database models for Smartlead integration.

Stores local references to Smartlead campaigns and email accounts
so we can track warmup state and enforce sending limits.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

SCHEMA = "easyprocess"


class SmartleadCampaign(Base):
    __tablename__ = "smartlead_campaigns"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    smartlead_campaign_id: Mapped[int] = mapped_column(
        Integer, unique=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="DRAFTED"
    )
    sending_account_email: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_sl_campaigns_sl_id", "smartlead_campaign_id"),
        {"schema": SCHEMA},
    )


class SmartleadEmailAccount(Base):
    __tablename__ = "smartlead_email_accounts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    smartlead_account_id: Mapped[int] = mapped_column(
        Integer, unique=True, nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)

    warmup_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    max_daily_sends: Mapped[int] = mapped_column(
        Integer, default=20, nullable=False
    )
    warmup_per_day: Mapped[int] = mapped_column(
        Integer, default=5, nullable=False
    )
    daily_rampup: Mapped[int] = mapped_column(
        Integer, default=2, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_sl_accounts_email", "email"),
        {"schema": SCHEMA},
    )
