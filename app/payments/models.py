import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

SCHEMA = "easyprocess"


# ---------------------------------------------------------------------------
# Stripe Connect accounts
# ---------------------------------------------------------------------------

class ConnectedAccount(Base):
    """Stripe Connect account linked to a site."""
    __tablename__ = "connected_accounts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    site_id: Mapped[str] = mapped_column(
        String(36), ForeignKey(f"{SCHEMA}.generated_sites.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey(f"{SCHEMA}.users.id", ondelete="SET NULL"), nullable=True
    )
    stripe_account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    onboarding_status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    charges_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    payouts_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    details_submitted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="SE")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("site_id", name="uq_connected_accounts_site_id"),
        UniqueConstraint("stripe_account_id", name="uq_connected_accounts_stripe_account_id"),
        Index("idx_connected_accounts_site_id", "site_id"),
        Index("idx_connected_accounts_stripe_account_id", "stripe_account_id"),
        {"schema": SCHEMA},
    )


# ---------------------------------------------------------------------------
# Platform payment tracking
# ---------------------------------------------------------------------------

class PlatformPayment(Base):
    """Platform fee tracking for payments."""
    __tablename__ = "platform_payments"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    booking_id: Mapped[str] = mapped_column(
        String(36), ForeignKey(f"{SCHEMA}.bookings.id", ondelete="CASCADE"), nullable=False
    )
    connected_account_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey(f"{SCHEMA}.connected_accounts.id", ondelete="SET NULL"), nullable=True
    )
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stripe_charge_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    platform_fee: Mapped[int] = mapped_column(Integer, nullable=False)
    net_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="SEK")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    __table_args__ = (
        Index("idx_platform_payments_booking_id", "booking_id"),
        Index("idx_platform_payments_stripe_pi", "stripe_payment_intent_id"),
        Index("idx_platform_payments_connected_account_id", "connected_account_id"),
        {"schema": SCHEMA},
    )
