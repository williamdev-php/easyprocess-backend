"""Tests for AutoBlogger platform integrations (Shopify, WordPress, Qvicko)."""
from __future__ import annotations

import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio

from app.autoblogger.integrations.shopify import (
    _normalize_shop_domain,
    build_oauth_url,
    test_connection as shopify_test_connection,
    publish_to_shopify,
)
from app.autoblogger.integrations.wordpress import (
    _build_auth_header,
    _normalize_api_url,
    test_connection as wp_test_connection,
    publish_to_wordpress,
)
from app.autoblogger.integrations.qvicko import publish_to_qvicko
from app.autoblogger.publisher import PublishResult
from app.sites.models import GeneratedSite, SiteStatus


# ─── Shopify: _normalize_shop_domain ──────────────────────────────────────────

class TestNormalizeShopDomain:
    def test_bare_name(self):
        assert _normalize_shop_domain("mystore") == "mystore.myshopify.com"

    def test_already_full(self):
        assert _normalize_shop_domain("mystore.myshopify.com") == "mystore.myshopify.com"

    def test_with_https_and_trailing_slash(self):
        assert _normalize_shop_domain("https://mystore.myshopify.com/") == "mystore.myshopify.com"

    def test_with_http(self):
        assert _normalize_shop_domain("http://mystore.myshopify.com") == "mystore.myshopify.com"

    def test_uppercase(self):
        assert _normalize_shop_domain("MyStore") == "mystore.myshopify.com"

    def test_whitespace(self):
        assert _normalize_shop_domain("  mystore  ") == "mystore.myshopify.com"


# ─── Shopify: build_oauth_url ─────────────────────────────────────────────────

class TestBuildOAuthUrl:
    @patch("app.autoblogger.integrations.shopify.settings")
    def test_returns_valid_url_with_params(self, mock_settings):
        mock_settings.SHOPIFY_API_KEY = "test-client-id"
        mock_settings.SHOPIFY_SCOPES = "write_content,read_content"

        url = build_oauth_url("mystore", "random-state", "https://example.com/callback")

        assert url.startswith("https://mystore.myshopify.com/admin/oauth/authorize?")
        assert "client_id=test-client-id" in url
        assert "scope=write_content" in url
        assert "redirect_uri=https" in url
        assert "state=random-state" in url


# ─── Shopify: test_connection ─────────────────────────────────────────────────

class TestShopifyTestConnection:
    @pytest.mark.asyncio
    async def test_success(self):
        mock_response_shop = MagicMock()
        mock_response_shop.status_code = 200
        mock_response_shop.raise_for_status = MagicMock()
        mock_response_shop.json.return_value = {
            "shop": {"name": "My Store", "domain": "mystore.myshopify.com"}
        }

        mock_response_blogs = MagicMock()
        mock_response_blogs.status_code = 200
        mock_response_blogs.raise_for_status = MagicMock()
        mock_response_blogs.json.return_value = {
            "blogs": [{"id": 1, "title": "News"}]
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[mock_response_shop, mock_response_blogs])
        mock_client.is_closed = False

        with patch("app.autoblogger.integrations.shopify._get_http_client", return_value=mock_client):
            result = await shopify_test_connection("mystore", "token123")

        assert result["shop_name"] == "My Store"
        assert result["shop_domain"] == "mystore.myshopify.com"
        assert len(result["blogs"]) == 1
        assert result["blogs"][0]["title"] == "News"

    @pytest.mark.asyncio
    async def test_failure_401(self):
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401 Unauthorized",
            request=MagicMock(),
            response=mock_response,
        )

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False

        with patch("app.autoblogger.integrations.shopify._get_http_client", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await shopify_test_connection("mystore", "bad-token")


# ─── Shopify: publish ─────────────────────────────────────────────────────────

class TestShopifyPublish:
    @pytest.mark.asyncio
    async def test_publish_constructs_correct_url(self):
        post = SimpleNamespace(
            title="Test Post",
            content="<p>Hello</p>",
            excerpt="Hello",
            tags=["tag1"],
            featured_image_url=None,
            meta_title=None,
            meta_description=None,
            slug="test-post",
        )
        source = SimpleNamespace(
            platform_config={
                "access_token": "tok",
                "shop_domain": "mystore",
                "blog_id": 42,
            }
        )

        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"article": {"id": 999}}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False

        with patch("app.autoblogger.integrations.shopify._get_http_client", return_value=mock_client):
            with patch("app.autoblogger.integrations.shopify.asyncio.sleep", new_callable=AsyncMock):
                result = await publish_to_shopify(post, source)

        assert result.success is True
        assert result.platform_post_id == "shopify-999"

        # Check the URL used
        call_args = mock_client.post.call_args
        url_used = call_args[0][0]
        assert "mystore.myshopify.com" in url_used
        assert "/blogs/42/articles.json" in url_used


# ─── WordPress: _normalize_api_url ────────────────────────────────────────────

class TestNormalizeApiUrl:
    def test_bare_url(self):
        assert _normalize_api_url("https://example.com") == "https://example.com/wp-json/wp/v2"

    def test_already_full(self):
        assert _normalize_api_url("https://example.com/wp-json/wp/v2") == "https://example.com/wp-json/wp/v2"

    def test_trailing_slash(self):
        assert _normalize_api_url("https://example.com/") == "https://example.com/wp-json/wp/v2"

    def test_wp_json_only(self):
        assert _normalize_api_url("https://example.com/wp-json") == "https://example.com/wp-json/wp/v2"


# ─── WordPress: _build_auth_header ────────────────────────────────────────────

class TestBuildAuthHeader:
    def test_returns_valid_basic_header(self):
        header = _build_auth_header("admin", "pass1234")
        assert header.startswith("Basic ")
        decoded = base64.b64decode(header.split(" ")[1]).decode()
        assert decoded == "admin:pass1234"


# ─── WordPress: test_connection ───────────────────────────────────────────────

class TestWordPressTestConnection:
    @pytest.mark.asyncio
    async def test_success(self):
        mock_user_resp = MagicMock()
        mock_user_resp.status_code = 200
        mock_user_resp.raise_for_status = MagicMock()
        mock_user_resp.json.return_value = {"name": "admin"}

        mock_root_resp = MagicMock()
        mock_root_resp.status_code = 200
        mock_root_resp.json.return_value = {"name": "My WP Site", "url": "https://example.com"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[mock_user_resp, mock_root_resp])
        mock_client.is_closed = False

        with patch("app.autoblogger.integrations.wordpress._get_http_client", return_value=mock_client):
            result = await wp_test_connection("https://example.com", "admin", "apppass")

        assert result["connected"] is True
        assert result["site_name"] == "My WP Site"
        assert result["user"] == "admin"

    @pytest.mark.asyncio
    async def test_failure(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401", request=MagicMock(), response=mock_resp,
        )

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.is_closed = False

        with patch("app.autoblogger.integrations.wordpress._get_http_client", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await wp_test_connection("https://example.com", "admin", "bad")


# ─── WordPress: publish ──────────────────────────────────────────────────────

class TestWordPressPublish:
    @pytest.mark.asyncio
    async def test_publish_constructs_correct_url_and_payload(self):
        post = SimpleNamespace(
            title="WP Post",
            content="<p>Body</p>",
            excerpt="Short",
            slug="wp-post",
            tags=None,
            featured_image_url=None,
            meta_title="SEO Title",
            meta_description="SEO Desc",
        )
        source = SimpleNamespace(
            platform_config={
                "api_url": "https://myblog.com",
                "username": "admin",
                "app_password": "secret",
            }
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"id": 77, "link": "https://myblog.com/wp-post"}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.is_closed = False

        with patch("app.autoblogger.integrations.wordpress._get_http_client", return_value=mock_client):
            result = await publish_to_wordpress(post, source)

        assert result.success is True
        assert result.platform_post_id == "wp-77"

        call_args = mock_client.post.call_args
        url_used = call_args[0][0]
        assert url_used == "https://myblog.com/wp-json/wp/v2/posts"

        payload = call_args[1]["json"]
        assert payload["title"] == "WP Post"
        assert payload["status"] == "publish"
        assert payload["meta"]["yoast_wpseo_title"] == "SEO Title"


# ─── Qvicko: publish ─────────────────────────────────────────────────────────

class TestQvickoPublish:
    @pytest.mark.asyncio
    async def test_publish_appends_blog_post_to_site_data(self, db):
        from app.sites.models import Lead, LeadStatus

        # Create a lead first
        lead = Lead(
            website_url="https://test.se",
            business_name="Test AB",
            industry="Test",
            source="manual",
            status=LeadStatus.NEW,
        )
        db.add(lead)
        await db.flush()

        # Create a published site
        site = GeneratedSite(
            lead_id=lead.id,
            subdomain="testsite",
            status=SiteStatus.PUBLISHED,
            site_data={"blog_posts": []},
        )
        db.add(site)
        await db.flush()
        await db.refresh(site)

        post = SimpleNamespace(
            id=str(uuid4()),
            title="Qvicko Post",
            slug="qvicko-post",
            content="<p>Content</p>",
            excerpt="Excerpt",
            meta_title="Meta",
            meta_description="Desc",
            featured_image_url=None,
            tags=["seo"],
            schema_markup={},
        )
        source = SimpleNamespace(
            platform_config={"site_id": str(site.id)},
        )

        result = await publish_to_qvicko(db, post, source)

        assert result.success is True
        assert result.platform_post_id.startswith("qvicko-")

        # Verify site_data was updated
        await db.refresh(site)
        blog_posts = site.site_data.get("blog_posts", [])
        assert len(blog_posts) == 1
        assert blog_posts[0]["title"] == "Qvicko Post"

    @pytest.mark.asyncio
    async def test_publish_fails_if_site_not_found(self, db):
        post = SimpleNamespace(id="123", title="X")
        source = SimpleNamespace(
            platform_config={"site_id": str(uuid4())},
        )

        result = await publish_to_qvicko(db, post, source)
        assert result.success is False
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_publish_fails_if_no_site_id(self, db):
        post = SimpleNamespace(id="123", title="X")
        source = SimpleNamespace(platform_config={})

        result = await publish_to_qvicko(db, post, source)
        assert result.success is False
        assert "site_id" in result.error
