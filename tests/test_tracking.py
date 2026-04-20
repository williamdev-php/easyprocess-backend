"""Tests for the tracking module: models, service aggregation, and router endpoints."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.tracking.models import TrackingEvent
from app.tracking.service import (
    FUNNEL_STEPS,
    get_analytics_overview,
    get_funnel_stats,
    get_top_pages,
    get_utm_stats,
    get_visitor_stats,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _event(
    event_type: str = "page_view",
    visitor_id: str | None = None,
    session_id: str | None = None,
    page_path: str = "/",
    utm_source: str | None = None,
    utm_medium: str | None = None,
    utm_campaign: str | None = None,
    user_id: str | None = None,
    created_at: datetime | None = None,
) -> TrackingEvent:
    return TrackingEvent(
        id=str(uuid.uuid4()),
        visitor_id=visitor_id or str(uuid.uuid4()),
        session_id=session_id or str(uuid.uuid4()),
        event_type=event_type,
        page_path=page_path,
        utm_source=utm_source,
        utm_medium=utm_medium,
        utm_campaign=utm_campaign,
        user_id=user_id,
        created_at=created_at or datetime.now(timezone.utc),
    )


NOW = datetime.now(timezone.utc) + timedelta(minutes=5)  # buffer for test timing
WEEK_AGO = NOW - timedelta(days=7)
MONTH_AGO = NOW - timedelta(days=30)


# ===================================================================
# 1. Model tests
# ===================================================================


class TestTrackingEventModel:
    """Verify TrackingEvent can be inserted and queried."""

    @pytest.mark.asyncio
    async def test_insert_and_query(self, db: AsyncSession):
        ev = _event(page_path="/pricing", utm_source="google")
        db.add(ev)
        await db.flush()

        result = await db.execute(
            select(TrackingEvent).where(TrackingEvent.id == ev.id)
        )
        row = result.scalar_one()

        assert row.event_type == "page_view"
        assert row.page_path == "/pricing"
        assert row.utm_source == "google"
        assert row.visitor_id == ev.visitor_id

    @pytest.mark.asyncio
    async def test_nullable_fields(self, db: AsyncSession):
        ev = _event()
        db.add(ev)
        await db.flush()

        result = await db.execute(
            select(TrackingEvent).where(TrackingEvent.id == ev.id)
        )
        row = result.scalar_one()

        assert row.referrer is None
        assert row.utm_source is None
        assert row.user_id is None
        assert row.metadata_ is None
        assert row.ip_address is None

    @pytest.mark.asyncio
    async def test_metadata_json(self, db: AsyncSession):
        ev = _event()
        ev.metadata_ = {"plan": "pro", "price": 299}
        db.add(ev)
        await db.flush()

        result = await db.execute(
            select(TrackingEvent).where(TrackingEvent.id == ev.id)
        )
        row = result.scalar_one()
        assert row.metadata_["plan"] == "pro"
        assert row.metadata_["price"] == 299


# ===================================================================
# 2. Service aggregation tests
# ===================================================================


class TestFunnelStats:
    """Test funnel stats aggregation."""

    @pytest.mark.asyncio
    async def test_empty_funnel(self, db: AsyncSession):
        results = await get_funnel_stats(db, MONTH_AGO, NOW)
        assert len(results) == len(FUNNEL_STEPS)
        assert all(s["count"] == 0 for s in results)

    @pytest.mark.asyncio
    async def test_funnel_counts_unique_visitors(self, db: AsyncSession):
        v1 = str(uuid.uuid4())
        v2 = str(uuid.uuid4())

        # v1 does page_view twice — should count as 1
        db.add(_event("page_view", visitor_id=v1))
        db.add(_event("page_view", visitor_id=v1))
        db.add(_event("page_view", visitor_id=v2))
        db.add(_event("cta_click", visitor_id=v1))
        db.add(_event("signup", visitor_id=v1))
        await db.flush()

        results = await get_funnel_stats(db, MONTH_AGO, NOW)
        steps = {s["name"]: s for s in results}

        assert steps["page_view"]["count"] == 2  # 2 unique visitors
        assert steps["cta_click"]["count"] == 1
        assert steps["signup"]["count"] == 1
        assert steps["create_site_started"]["count"] == 0

    @pytest.mark.asyncio
    async def test_funnel_conversion_rates(self, db: AsyncSession):
        v1 = str(uuid.uuid4())
        v2 = str(uuid.uuid4())

        db.add(_event("page_view", visitor_id=v1))
        db.add(_event("page_view", visitor_id=v2))
        db.add(_event("cta_click", visitor_id=v1))
        await db.flush()

        results = await get_funnel_stats(db, MONTH_AGO, NOW)
        steps = {s["name"]: s for s in results}

        assert steps["page_view"]["conversion_rate"] is None  # first step
        assert steps["cta_click"]["conversion_rate"] == 50.0  # 1/2 * 100

    @pytest.mark.asyncio
    async def test_funnel_utm_filter(self, db: AsyncSession):
        v1 = str(uuid.uuid4())
        v2 = str(uuid.uuid4())

        db.add(_event("page_view", visitor_id=v1, utm_source="google"))
        db.add(_event("page_view", visitor_id=v2, utm_source="facebook"))
        await db.flush()

        results = await get_funnel_stats(db, MONTH_AGO, NOW, utm_source="google")
        steps = {s["name"]: s for s in results}
        assert steps["page_view"]["count"] == 1


class TestVisitorStats:
    """Test daily visitor stats."""

    @pytest.mark.asyncio
    async def test_empty(self, db: AsyncSession):
        data = await get_visitor_stats(db, MONTH_AGO, NOW)
        assert data["total"] == 0
        assert data["points"] == []

    @pytest.mark.asyncio
    async def test_daily_grouping(self, db: AsyncSession):
        v1 = str(uuid.uuid4())
        v2 = str(uuid.uuid4())
        today = datetime.now(timezone.utc).replace(hour=12)

        db.add(_event("page_view", visitor_id=v1, created_at=today))
        db.add(_event("page_view", visitor_id=v2, created_at=today))
        db.add(_event("page_view", visitor_id=v1, created_at=today))  # dupe
        await db.flush()

        data = await get_visitor_stats(db, MONTH_AGO, NOW)
        assert data["total"] == 2
        assert len(data["points"]) == 1
        assert data["points"][0]["count"] == 2


class TestUtmStats:
    """Test UTM breakdown stats."""

    @pytest.mark.asyncio
    async def test_groups_by_utm(self, db: AsyncSession):
        v1 = str(uuid.uuid4())
        v2 = str(uuid.uuid4())

        db.add(_event("page_view", visitor_id=v1, utm_source="google", utm_medium="cpc"))
        db.add(_event("page_view", visitor_id=v2, utm_source="google", utm_medium="cpc"))
        db.add(_event("page_view", visitor_id=v1, utm_source="facebook"))
        await db.flush()

        entries = await get_utm_stats(db, MONTH_AGO, NOW)
        assert len(entries) >= 1

        google_cpc = [e for e in entries if e["source"] == "google" and e["medium"] == "cpc"]
        assert len(google_cpc) == 1
        assert google_cpc[0]["count"] == 2

    @pytest.mark.asyncio
    async def test_excludes_null_utm(self, db: AsyncSession):
        db.add(_event("page_view"))  # no utm
        await db.flush()

        entries = await get_utm_stats(db, MONTH_AGO, NOW)
        assert len(entries) == 0


class TestTopPages:
    """Test top pages aggregation."""

    @pytest.mark.asyncio
    async def test_ordered_by_count(self, db: AsyncSession):
        v1 = str(uuid.uuid4())
        v2 = str(uuid.uuid4())
        v3 = str(uuid.uuid4())

        db.add(_event("page_view", visitor_id=v1, page_path="/pricing"))
        db.add(_event("page_view", visitor_id=v2, page_path="/pricing"))
        db.add(_event("page_view", visitor_id=v3, page_path="/pricing"))
        db.add(_event("page_view", visitor_id=v1, page_path="/"))
        await db.flush()

        pages = await get_top_pages(db, MONTH_AGO, NOW)
        assert len(pages) >= 2
        assert pages[0]["path"] == "/pricing"
        assert pages[0]["count"] == 3
        assert pages[1]["count"] == 1

    @pytest.mark.asyncio
    async def test_respects_limit(self, db: AsyncSession):
        for i in range(5):
            db.add(_event("page_view", page_path=f"/page-{i}"))
        await db.flush()

        pages = await get_top_pages(db, MONTH_AGO, NOW, limit=3)
        assert len(pages) == 3


class TestAnalyticsOverview:
    """Test analytics overview metrics."""

    @pytest.mark.asyncio
    async def test_basic_overview(self, db: AsyncSession):
        v1 = str(uuid.uuid4())

        db.add(_event("page_view", visitor_id=v1))
        db.add(_event("signup", visitor_id=v1))
        db.add(_event("trial_started", visitor_id=v1))
        await db.flush()

        overview = await get_analytics_overview(db, MONTH_AGO, NOW)

        assert overview["unique_visitors"] == 1
        assert overview["total_signups"] == 1
        assert overview["total_trials"] == 1
        assert overview["total_subscriptions"] == 0
        assert overview["trial_start_rate"] == 100.0
        assert overview["trial_conversion_rate"] == 0.0
        assert overview["total_revenue_sek"] == 0

    @pytest.mark.asyncio
    async def test_zero_division_safety(self, db: AsyncSession):
        """No signups → trial_start_rate should be 0, not crash."""
        overview = await get_analytics_overview(db, MONTH_AGO, NOW)
        assert overview["trial_start_rate"] == 0.0
        assert overview["trial_conversion_rate"] == 0.0


# ===================================================================
# 3. Router / endpoint tests
# ===================================================================


class TestTrackRouter:
    """Test the REST tracking endpoints via HTTPX test client."""

    @pytest_asyncio.fixture
    async def client(self):
        """Create an async test client for the FastAPI app."""
        from app.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    @pytest.mark.asyncio
    async def test_single_event(self, client: AsyncClient):
        payload = {
            "visitor_id": str(uuid.uuid4()),
            "session_id": str(uuid.uuid4()),
            "event_type": "page_view",
            "page_path": "/test",
        }
        resp = await client.post("/api/track", json=payload)
        assert resp.status_code == 202
        assert resp.json()["ok"] is True

    @pytest.mark.asyncio
    async def test_single_event_with_utm(self, client: AsyncClient):
        payload = {
            "visitor_id": str(uuid.uuid4()),
            "session_id": str(uuid.uuid4()),
            "event_type": "cta_click",
            "page_path": "/pricing",
            "utm_source": "google",
            "utm_medium": "cpc",
            "utm_campaign": "spring2026",
        }
        resp = await client.post("/api/track", json=payload)
        assert resp.status_code == 202

    @pytest.mark.asyncio
    async def test_single_event_with_metadata(self, client: AsyncClient):
        payload = {
            "visitor_id": str(uuid.uuid4()),
            "session_id": str(uuid.uuid4()),
            "event_type": "create_site_completed",
            "page_path": "/create-site",
            "metadata": {"site_id": "abc-123", "mode": "new"},
        }
        resp = await client.post("/api/track", json=payload)
        assert resp.status_code == 202

    @pytest.mark.asyncio
    async def test_batch_events(self, client: AsyncClient):
        events = [
            {
                "visitor_id": str(uuid.uuid4()),
                "session_id": str(uuid.uuid4()),
                "event_type": f"event_{i}",
                "page_path": f"/page-{i}",
            }
            for i in range(5)
        ]
        resp = await client.post("/api/track/batch", json={"events": events})
        assert resp.status_code == 202
        assert resp.json()["ok"] is True

    @pytest.mark.asyncio
    async def test_batch_max_25(self, client: AsyncClient):
        events = [
            {
                "visitor_id": str(uuid.uuid4()),
                "session_id": str(uuid.uuid4()),
                "event_type": "page_view",
                "page_path": "/",
            }
            for _ in range(30)
        ]
        resp = await client.post("/api/track/batch", json={"events": events})
        # Pydantic validation should reject > 25 events
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_identify(self, client: AsyncClient):
        visitor_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())

        resp = await client.post(
            "/api/track/identify",
            json={"visitor_id": visitor_id, "user_id": user_id},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    @pytest.mark.asyncio
    async def test_invalid_payload_returns_400(self, client: AsyncClient):
        resp = await client.post("/api/track", json={"bad": "data"})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_sendbeacon_text_plain(self, client: AsyncClient):
        """sendBeacon sends text/plain content type — should still parse."""
        payload = json.dumps({
            "visitor_id": str(uuid.uuid4()),
            "session_id": str(uuid.uuid4()),
            "event_type": "page_view",
            "page_path": "/beacon-test",
        })
        resp = await client.post(
            "/api/track",
            content=payload,
            headers={"content-type": "text/plain"},
        )
        assert resp.status_code == 202

    @pytest.mark.asyncio
    async def test_all_funnel_event_types(self, client: AsyncClient):
        """Verify all funnel event types are accepted."""
        for event_type in FUNNEL_STEPS:
            payload = {
                "visitor_id": str(uuid.uuid4()),
                "session_id": str(uuid.uuid4()),
                "event_type": event_type,
                "page_path": "/test",
            }
            resp = await client.post("/api/track", json=payload)
            assert resp.status_code == 202, f"Failed for event_type={event_type}"


# ===================================================================
# 4. Pydantic validation tests
# ===================================================================


class TestPydanticSchemas:
    """Test request validation schemas directly."""

    def test_track_event_minimal(self):
        from app.tracking.router import TrackEventRequest

        req = TrackEventRequest(
            visitor_id="v1",
            session_id="s1",
            event_type="page_view",
        )
        assert req.page_path == "/"
        assert req.referrer is None

    def test_track_event_full(self):
        from app.tracking.router import TrackEventRequest

        req = TrackEventRequest(
            visitor_id="v1",
            session_id="s1",
            event_type="signup",
            page_path="/register",
            referrer="https://google.com",
            utm_source="google",
            utm_medium="cpc",
            utm_campaign="spring",
            utm_content="ad1",
            utm_term="website builder",
            user_id="user-123",
            metadata={"step": 2},
        )
        assert req.utm_source == "google"
        assert req.metadata == {"step": 2}

    def test_track_event_max_length(self):
        from app.tracking.router import TrackEventRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            TrackEventRequest(
                visitor_id="x" * 100,  # exceeds 64
                session_id="s1",
                event_type="page_view",
            )

    def test_batch_max_25(self):
        from app.tracking.router import TrackBatchRequest, TrackEventRequest
        from pydantic import ValidationError

        events = [
            TrackEventRequest(
                visitor_id="v1", session_id="s1", event_type="page_view"
            )
            for _ in range(30)
        ]
        with pytest.raises(ValidationError):
            TrackBatchRequest(events=events)

    def test_identify_request(self):
        from app.tracking.router import IdentifyRequest

        req = IdentifyRequest(visitor_id="v1", user_id="u1")
        assert req.visitor_id == "v1"
        assert req.user_id == "u1"
