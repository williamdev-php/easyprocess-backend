"""Tests for Google Search Console integration.

Covers: model CRUD, service functions (with mocked HTTP), and router endpoints.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.sites.models import (
    CustomDomain,
    DomainStatus,
    GscConnection,
    GscConnectionStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user(**overrides) -> User:
    defaults = dict(
        id=str(uuid.uuid4()),
        email=f"test-{uuid.uuid4().hex[:6]}@example.com",
        full_name="Test User",
        password_hash="fakehash",
        locale="sv",
        is_active=True,
        is_superuser=False,
        is_verified=True,
    )
    defaults.update(overrides)
    return User(**defaults)


def _domain(user_id: str, domain: str = "example.com", verified: bool = True, **kw) -> CustomDomain:
    return CustomDomain(
        id=str(uuid.uuid4()),
        user_id=user_id,
        domain=domain,
        status=DomainStatus.ACTIVE if verified else DomainStatus.PENDING,
        verified_at=datetime.now(timezone.utc) if verified else None,
        **kw,
    )


def _gsc_connection(user_id: str, **overrides) -> GscConnection:
    defaults = dict(
        id=str(uuid.uuid4()),
        user_id=user_id,
        google_email="user@gmail.com",
        access_token="ya29.fake-access-token",
        refresh_token="1//fake-refresh-token",
        token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        status=GscConnectionStatus.CONNECTED,
    )
    defaults.update(overrides)
    return GscConnection(**defaults)


# ===================================================================
# 1. Model tests
# ===================================================================


class TestGscConnectionModel:
    """Verify GscConnection can be inserted and queried."""

    @pytest.mark.asyncio
    async def test_insert_and_query(self, db: AsyncSession):
        user = _user()
        db.add(user)
        await db.flush()

        conn = _gsc_connection(user.id)
        db.add(conn)
        await db.flush()

        result = await db.execute(
            select(GscConnection).where(GscConnection.user_id == user.id)
        )
        row = result.scalar_one()

        assert row.google_email == "user@gmail.com"
        assert row.status == GscConnectionStatus.CONNECTED
        assert row.refresh_token == "1//fake-refresh-token"

    @pytest.mark.asyncio
    async def test_one_connection_per_user(self, db: AsyncSession):
        """user_id has a unique constraint — second insert should fail."""
        user = _user()
        db.add(user)
        await db.flush()

        db.add(_gsc_connection(user.id))
        await db.flush()

        from sqlalchemy.exc import IntegrityError

        db.add(_gsc_connection(user.id, id=str(uuid.uuid4())))
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()

    @pytest.mark.asyncio
    async def test_status_values(self, db: AsyncSession):
        user = _user()
        db.add(user)
        await db.flush()

        conn = _gsc_connection(user.id, status=GscConnectionStatus.EXPIRED)
        db.add(conn)
        await db.flush()

        result = await db.execute(
            select(GscConnection).where(GscConnection.id == conn.id)
        )
        assert result.scalar_one().status == GscConnectionStatus.EXPIRED


# ===================================================================
# 2. Service tests (mocked HTTP)
# ===================================================================


class TestGscService:
    """Test service functions with mocked Google API calls."""

    @pytest.mark.asyncio
    async def test_exchange_gsc_code_success(self):
        """Successful code exchange returns tokens + email."""
        from app.gsc.service import exchange_gsc_code

        mock_token_response = MagicMock()
        mock_token_response.status_code = 200
        mock_token_response.json.return_value = {
            "access_token": "ya29.new-token",
            "refresh_token": "1//new-refresh",
            "expires_in": 3600,
        }

        mock_userinfo_response = MagicMock()
        mock_userinfo_response.status_code = 200
        mock_userinfo_response.json.return_value = {
            "email": "user@gmail.com",
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_token_response
        mock_client.get.return_value = mock_userinfo_response

        with patch("app.gsc.service.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await exchange_gsc_code("auth-code-123", "http://localhost:3000/api/auth/google/callback")

        assert result["access_token"] == "ya29.new-token"
        assert result["refresh_token"] == "1//new-refresh"
        assert result["email"] == "user@gmail.com"

    @pytest.mark.asyncio
    async def test_exchange_gsc_code_no_refresh_token(self):
        """Should raise if Google doesn't return a refresh token."""
        from app.gsc.service import exchange_gsc_code

        mock_token_response = MagicMock()
        mock_token_response.status_code = 200
        mock_token_response.json.return_value = {
            "access_token": "ya29.new-token",
            "expires_in": 3600,
            # no refresh_token!
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_token_response

        with patch("app.gsc.service.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(ValueError, match="refresh token"):
                await exchange_gsc_code("code", "http://localhost:3000/callback")

    @pytest.mark.asyncio
    async def test_exchange_gsc_code_token_exchange_fails(self):
        """Should raise on failed token exchange."""
        from app.gsc.service import exchange_gsc_code

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "invalid_grant"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch("app.gsc.service.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(ValueError, match="Failed to exchange"):
                await exchange_gsc_code("bad-code", "http://localhost:3000/callback")

    @pytest.mark.asyncio
    async def test_refresh_access_token_success(self):
        """Refresh updates the connection's token fields."""
        from app.gsc.service import refresh_access_token

        conn = _gsc_connection("user-123", token_expires_at=datetime.now(timezone.utc) - timedelta(hours=1))

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "ya29.refreshed",
            "expires_in": 3600,
        }

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch("app.gsc.service.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            new_token = await refresh_access_token(conn)

        assert new_token == "ya29.refreshed"
        assert conn.access_token == "ya29.refreshed"
        assert conn.token_expires_at > datetime.now(timezone.utc)

    @pytest.mark.asyncio
    async def test_refresh_access_token_failure_marks_expired(self):
        """Failed refresh marks the connection as EXPIRED."""
        from app.gsc.service import refresh_access_token

        conn = _gsc_connection("user-123")

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Token has been revoked"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch("app.gsc.service.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(ValueError, match="reconnect"):
                await refresh_access_token(conn)

        assert conn.status == GscConnectionStatus.EXPIRED

    @pytest.mark.asyncio
    async def test_add_site_to_gsc_success(self):
        """Successful PUT to Search Console API."""
        from app.gsc.service import add_site_to_gsc

        conn = _gsc_connection("user-123")

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.put.return_value = mock_response

        with patch("app.gsc.service.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await add_site_to_gsc(conn, "example.com")

        assert result is True
        # Verify correct URL was called
        call_args = mock_client.put.call_args
        assert "example.com" in str(call_args)

    @pytest.mark.asyncio
    async def test_submit_sitemap_success(self):
        """Successful sitemap submission."""
        from app.gsc.service import submit_sitemap

        conn = _gsc_connection("user-123")

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.put.return_value = mock_response

        with patch("app.gsc.service.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await submit_sitemap(conn, "example.com")

        assert result is True
        call_args = mock_client.put.call_args
        assert "sitemap.xml" in str(call_args)

    @pytest.mark.asyncio
    async def test_get_user_verified_domain(self, db: AsyncSession):
        """Returns the first verified domain for a user."""
        from app.gsc.service import get_user_verified_domain

        user = _user()
        db.add(user)
        await db.flush()

        # No domain yet
        result = await get_user_verified_domain(db, user.id)
        assert result is None

        # Add unverified domain
        db.add(_domain(user.id, "pending.com", verified=False))
        await db.flush()
        result = await get_user_verified_domain(db, user.id)
        assert result is None

        # Add verified domain
        db.add(_domain(user.id, "verified.com", verified=True))
        await db.flush()
        result = await get_user_verified_domain(db, user.id)
        assert result == "verified.com"

    @pytest.mark.asyncio
    async def test_get_gsc_connection(self, db: AsyncSession):
        """Returns None when no connection, connection when exists."""
        from app.gsc.service import get_gsc_connection

        user = _user()
        db.add(user)
        await db.flush()

        assert await get_gsc_connection(db, user.id) is None

        conn = _gsc_connection(user.id)
        db.add(conn)
        await db.flush()

        result = await get_gsc_connection(db, user.id)
        assert result is not None
        assert result.google_email == "user@gmail.com"

    @pytest.mark.asyncio
    async def test_index_domain_full_flow(self, db: AsyncSession):
        """Full indexing flow: add site + submit sitemap."""
        from app.gsc.service import index_domain

        user = _user()
        db.add(user)
        await db.flush()

        conn = _gsc_connection(user.id)
        db.add(conn)
        await db.flush()

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.put.return_value = mock_response

        with patch("app.gsc.service.httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            results = await index_domain(db, conn, "example.com")

        assert results["site_added"] is True
        assert results["sitemap_submitted"] is True
        assert conn.indexed_domain == "example.com"
        assert conn.indexed_at is not None


# ===================================================================
# 3. Router / endpoint tests (full HTTP via ASGI)
# ===================================================================


@pytest_asyncio.fixture
async def authenticated_user(db: AsyncSession):
    """Create a user and return (user, access_token)."""
    from app.auth.service import create_access_token

    user = _user()
    db.add(user)
    await db.flush()
    token = create_access_token(user.id)
    return user, token


@pytest_asyncio.fixture
async def user_with_domain(db: AsyncSession, authenticated_user):
    """User with a verified custom domain."""
    user, token = authenticated_user
    domain = _domain(user.id, "mysite.com", verified=True)
    db.add(domain)
    await db.flush()
    return user, token, domain


def _make_test_app(db: AsyncSession):
    """Create a test app with dependency overrides for db and auth cache."""
    from app.main import app
    from app.database import get_db

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return app


def _patch_cache_and_auth():
    """Context manager that patches Redis cache + user cache lookups for tests."""
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        with patch("app.auth.dependencies.get_user_by_id_cached", return_value=None):
            with patch("app.auth.service._cache_user", new_callable=AsyncMock):
                yield

    return _ctx()


class TestGscRouter:
    """Test GSC REST endpoints via ASGI transport."""

    @pytest.mark.asyncio
    async def test_status_not_connected(self, db: AsyncSession, authenticated_user):
        """GET /api/gsc/status returns connected=false when no connection."""
        _, token = authenticated_user
        app = _make_test_app(db)

        try:
            with _patch_cache_and_auth():
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    resp = await client.get(
                        "/api/gsc/status",
                        headers={"Authorization": f"Bearer {token}"},
                    )

            assert resp.status_code == 200
            data = resp.json()
            assert data["connected"] is False
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_status_connected(self, db: AsyncSession, authenticated_user):
        """GET /api/gsc/status returns connection info when connected."""
        user, token = authenticated_user
        conn = _gsc_connection(user.id, indexed_domain="mysite.com")
        db.add(conn)
        await db.flush()

        app = _make_test_app(db)
        try:
            with _patch_cache_and_auth():
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    resp = await client.get(
                        "/api/gsc/status",
                        headers={"Authorization": f"Bearer {token}"},
                    )

            assert resp.status_code == 200
            data = resp.json()
            assert data["connected"] is True
            assert data["google_email"] == "user@gmail.com"
            assert data["indexed_domain"] == "mysite.com"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_connect_requires_domain(self, db: AsyncSession, authenticated_user):
        """POST /api/gsc/connect fails without a verified custom domain."""
        _, token = authenticated_user
        app = _make_test_app(db)

        try:
            with _patch_cache_and_auth():
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    resp = await client.post(
                        "/api/gsc/connect",
                        json={"code": "test-code", "redirect_uri": "http://localhost:3000/api/auth/google/callback"},
                        headers={"Authorization": f"Bearer {token}"},
                    )

            assert resp.status_code == 400
            assert "verified custom domain" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_connect_success(self, db: AsyncSession, user_with_domain):
        """POST /api/gsc/connect exchanges code, stores tokens, indexes."""
        user, token, domain = user_with_domain
        app = _make_test_app(db)

        mock_exchange = {
            "access_token": "ya29.connected",
            "refresh_token": "1//connected-refresh",
            "expires_in": 3600,
            "email": "user@gmail.com",
        }

        mock_put_response = MagicMock()
        mock_put_response.status_code = 200

        mock_http_client = AsyncMock()
        mock_http_client.put.return_value = mock_put_response

        try:
            with _patch_cache_and_auth():
                with patch("app.gsc.router.exchange_gsc_code", new_callable=AsyncMock, return_value=mock_exchange):
                    with patch("app.gsc.service.httpx.AsyncClient") as MockClient:
                        MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_http_client)
                        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

                        async with AsyncClient(
                            transport=ASGITransport(app=app),
                            base_url="http://test",
                        ) as client:
                            resp = await client.post(
                                "/api/gsc/connect",
                                json={
                                    "code": "test-code",
                                    "redirect_uri": "http://localhost:3000/api/auth/google/callback",
                                },
                                headers={"Authorization": f"Bearer {token}"},
                            )

            assert resp.status_code == 200
            data = resp.json()
            assert data["connected"] is True
            assert data["google_email"] == "user@gmail.com"
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_disconnect(self, db: AsyncSession, authenticated_user):
        """POST /api/gsc/disconnect removes the connection."""
        user, token = authenticated_user
        conn = _gsc_connection(user.id)
        db.add(conn)
        await db.flush()

        app = _make_test_app(db)
        try:
            with _patch_cache_and_auth():
                with patch("app.gsc.service.revoke_gsc_connection", new_callable=AsyncMock):
                    async with AsyncClient(
                        transport=ASGITransport(app=app),
                        base_url="http://test",
                    ) as client:
                        resp = await client.post(
                            "/api/gsc/disconnect",
                            headers={"Authorization": f"Bearer {token}"},
                        )

            assert resp.status_code == 200
            assert resp.json()["disconnected"] is True

            # Verify deleted from DB
            result = await db.execute(
                select(GscConnection).where(GscConnection.user_id == user.id)
            )
            assert result.scalar_one_or_none() is None
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_disconnect_not_found(self, db: AsyncSession, authenticated_user):
        """POST /api/gsc/disconnect returns 404 when no connection exists."""
        _, token = authenticated_user
        app = _make_test_app(db)

        try:
            with _patch_cache_and_auth():
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                ) as client:
                    resp = await client.post(
                        "/api/gsc/disconnect",
                        headers={"Authorization": f"Bearer {token}"},
                    )

            assert resp.status_code == 404
        finally:
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_unauthenticated_request(self):
        """Endpoints require authentication."""
        from app.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/api/gsc/status")
            assert resp.status_code == 401

            resp = await client.post("/api/gsc/connect", json={"code": "x", "redirect_uri": "y"})
            assert resp.status_code == 401
