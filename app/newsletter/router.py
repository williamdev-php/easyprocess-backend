import logging

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.newsletter.models import NewsletterSubscription
from app.rate_limit import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/newsletter", tags=["newsletter"])


class SubscribeRequest(BaseModel):
    email: EmailStr
    locale: str = "sv"
    source: str = "password_gate"


class SubscribeResponse(BaseModel):
    ok: bool = True
    message: str = "subscribed"


@router.post("/subscribe", response_model=SubscribeResponse)
@limiter.limit("10/minute")
async def subscribe(
    body: SubscribeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SubscribeResponse:
    """Subscribe an email to the newsletter.

    If the email already exists, return success silently (no duplicate created).
    """
    existing = await db.execute(
        select(NewsletterSubscription).where(
            NewsletterSubscription.email == body.email.lower()
        )
    )
    if existing.scalar_one_or_none() is not None:
        logger.info("Newsletter duplicate skip: %s", body.email)
        return SubscribeResponse()

    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or request.client.host if request.client else None
    ua = request.headers.get("user-agent")

    sub = NewsletterSubscription(
        email=body.email.lower(),
        locale=body.locale,
        source=body.source,
        ip_address=ip,
        user_agent=ua,
    )
    db.add(sub)
    logger.info("Newsletter subscription created: %s (locale=%s)", body.email, body.locale)
    return SubscribeResponse()
