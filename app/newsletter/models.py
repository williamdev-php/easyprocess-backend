from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

SCHEMA = "easyprocess"


class NewsletterSubscription(Base):
    __tablename__ = "qvicko_newsletter"
    __table_args__ = (
        Index("idx_newsletter_email", "email", unique=True),
        Index("idx_newsletter_locale", "locale"),
        {"schema": SCHEMA},
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    locale: Mapped[str] = mapped_column(String(10), nullable=False, default="sv")
    source: Mapped[str] = mapped_column(
        String(50), nullable=False, default="password_gate"
    )
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    subscribed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
