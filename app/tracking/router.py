import json
import logging
import uuid

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from app.database import get_db_session
from app.rate_limit import limiter
from app.tracking.models import TrackingEvent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/track", tags=["tracking"])


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class TrackEventRequest(BaseModel):
    visitor_id: str = Field(max_length=64)
    session_id: str = Field(max_length=64)
    event_type: str = Field(max_length=50)
    page_path: str = Field(max_length=500, default="/")
    referrer: str | None = Field(None, max_length=1000)
    utm_source: str | None = Field(None, max_length=255)
    utm_medium: str | None = Field(None, max_length=255)
    utm_campaign: str | None = Field(None, max_length=255)
    utm_content: str | None = Field(None, max_length=255)
    utm_term: str | None = Field(None, max_length=255)
    user_id: str | None = Field(None, max_length=36)
    metadata: dict | None = None


class TrackBatchRequest(BaseModel):
    events: list[TrackEventRequest] = Field(max_length=25)


class IdentifyRequest(BaseModel):
    visitor_id: str = Field(max_length=64)
    user_id: str = Field(max_length=36)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _parse_body(request: Request) -> dict | list:
    """Parse request body handling both JSON and text/plain (sendBeacon)."""
    content_type = request.headers.get("content-type", "")
    raw = await request.body()
    if "application/json" in content_type:
        return json.loads(raw)
    # sendBeacon with Blob sends text/plain
    return json.loads(raw)


def _build_event(data: TrackEventRequest, request: Request) -> TrackingEvent:
    return TrackingEvent(
        id=str(uuid.uuid4()),
        visitor_id=data.visitor_id,
        session_id=data.session_id,
        event_type=data.event_type,
        page_path=data.page_path,
        referrer=data.referrer,
        utm_source=data.utm_source,
        utm_medium=data.utm_medium,
        utm_campaign=data.utm_campaign,
        utm_content=data.utm_content,
        utm_term=data.utm_term,
        user_id=data.user_id,
        metadata_=data.metadata,
        ip_address=request.client.host if request.client else None,
        user_agent=(request.headers.get("user-agent") or "")[:500],
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", status_code=202)
@limiter.limit("120/minute")
async def track_event(request: Request):
    """Record a single tracking event."""
    try:
        body = await _parse_body(request)
        data = TrackEventRequest(**body)
    except Exception:
        return Response(status_code=400)

    try:
        async with get_db_session() as db:
            db.add(_build_event(data, request))
    except Exception:
        logger.exception("Failed to save tracking event")

    return {"ok": True}


@router.post("/batch", status_code=202)
@limiter.limit("60/minute")
async def track_batch(request: Request):
    """Record multiple tracking events (max 25)."""
    try:
        body = await _parse_body(request)
        batch = TrackBatchRequest(**body)
    except Exception:
        return Response(status_code=400)

    try:
        async with get_db_session() as db:
            for event_data in batch.events:
                db.add(_build_event(event_data, request))
    except Exception:
        logger.exception("Failed to save tracking batch")

    return {"ok": True}


@router.post("/identify", status_code=200)
@limiter.limit("10/minute")
async def identify_visitor(request: Request):
    """Link anonymous visitor_id to an authenticated user_id."""
    try:
        body = await _parse_body(request)
        data = IdentifyRequest(**body)
    except Exception:
        return Response(status_code=400)

    try:
        from sqlalchemy import update

        async with get_db_session() as db:
            await db.execute(
                update(TrackingEvent)
                .where(
                    TrackingEvent.visitor_id == data.visitor_id,
                    TrackingEvent.user_id.is_(None),
                )
                .values(user_id=data.user_id)
            )
    except Exception:
        logger.exception("Failed to identify visitor")

    return {"ok": True}
