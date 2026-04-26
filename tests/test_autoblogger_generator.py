"""Tests for AutoBlogger generator, publisher, and images modules."""

from __future__ import annotations

import asyncio
import json
from dataclasses import fields as dataclass_fields
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.autoblogger.generator import (
    BlogGenerationResult,
    _build_prompt,
    _count_words,
    _extract_json,
    _SYSTEM_PROMPT,
    _retry_api_call,
    generate_blog_post,
)
from app.autoblogger.models import BlogPostAB, PlatformType, PostStatus, Source
from app.autoblogger.publisher import PublishResult, publish_post
from app.autoblogger.images import (
    _build_prompt as _build_image_prompt,
    generate_featured_image,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_claude_json_response() -> dict:
    """Return a realistic Claude API JSON response body."""
    blog_json = {
        "title": "10 Tips for Better SEO",
        "slug": "10-tips-for-better-seo",
        "content": "<h2>Introduction</h2><p>SEO is important for driving organic traffic.</p>"
                   "<h2>Tip 1</h2><p>Use keywords naturally in your content.</p>",
        "excerpt": "Learn the top 10 tips for improving your SEO strategy.",
        "meta_title": "10 Tips for Better SEO | Expert Guide",
        "meta_description": "Discover 10 actionable tips to improve your SEO and drive more organic traffic to your website.",
        "tags": ["seo", "marketing", "content"],
        "schema_markup": {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": "10 Tips for Better SEO",
        },
        "internal_links": [
            {"anchor": "content marketing", "suggested_topic": "Content Marketing 101"},
        ],
    }
    return {
        "content": [{"text": json.dumps(blog_json)}],
        "usage": {"input_tokens": 500, "output_tokens": 1200},
    }


def _mock_httpx_response(status_code: int = 200, json_body: dict | None = None, text: str = "") -> httpx.Response:
    """Build a fake httpx.Response."""
    resp = httpx.Response(
        status_code=status_code,
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
    )
    if json_body is not None:
        resp._content = json.dumps(json_body).encode()
    else:
        resp._content = text.encode()
    return resp


# ===========================================================================
# Generator tests
# ===========================================================================

class TestSystemPrompt:
    def test_system_prompt_is_nonempty(self):
        assert len(_SYSTEM_PROMPT) > 0

    def test_system_prompt_contains_key_instructions(self):
        assert "JSON" in _SYSTEM_PROMPT
        assert "SEO" in _SYSTEM_PROMPT


class TestBuildPrompt:
    def test_basic_prompt(self):
        prompt = _build_prompt(
            topic="Python Testing",
            keywords=["pytest", "unittest"],
            language="en",
            brand_voice=None,
            word_count_target=1200,
            title=None,
            existing_posts=None,
        )
        assert "Python Testing" in prompt
        assert "pytest" in prompt
        assert "1200" in prompt
        assert "en" in prompt

    def test_prompt_with_brand_voice(self):
        prompt = _build_prompt(
            topic="AI Tools",
            keywords=["ai"],
            language="en",
            brand_voice="Friendly and professional",
            word_count_target=800,
            title=None,
            existing_posts=None,
        )
        assert "Friendly and professional" in prompt

    def test_prompt_with_title(self):
        prompt = _build_prompt(
            topic="AI Tools",
            keywords=["ai"],
            language="en",
            brand_voice=None,
            word_count_target=800,
            title="My Custom Title",
            existing_posts=None,
        )
        assert "My Custom Title" in prompt

    def test_prompt_with_existing_posts(self):
        prompt = _build_prompt(
            topic="AI Tools",
            keywords=["ai"],
            language="sv",
            brand_voice=None,
            word_count_target=1000,
            title=None,
            existing_posts=["Post A", "Post B"],
        )
        assert "Post A" in prompt
        assert "Post B" in prompt

    def test_prompt_language_appears(self):
        prompt = _build_prompt(
            topic="Cooking",
            keywords=["recipes"],
            language="fr",
            brand_voice=None,
            word_count_target=600,
            title=None,
            existing_posts=None,
        )
        assert "fr" in prompt


class TestBlogGenerationResultFields:
    def test_has_all_required_fields(self):
        expected = {
            "title", "slug", "content", "excerpt", "meta_title",
            "meta_description", "tags", "schema_markup", "internal_links",
            "word_count", "reading_time_minutes", "ai_model",
            "input_tokens", "output_tokens", "cost_usd", "generation_prompt",
        }
        actual = {f.name for f in dataclass_fields(BlogGenerationResult)}
        assert expected == actual


class TestHelpers:
    def test_count_words_simple(self):
        assert _count_words("<p>Hello world</p>") == 2

    def test_count_words_complex(self):
        html = "<h2>Title</h2><p>One two three four five.</p>"
        assert _count_words(html) == 6

    def test_extract_json_plain(self):
        raw = '{"title": "foo"}'
        assert _extract_json(raw) == raw

    def test_extract_json_fenced(self):
        raw = '```json\n{"title": "foo"}\n```'
        assert _extract_json(raw).strip() == '{"title": "foo"}'

    def test_extract_json_generic_fence(self):
        raw = '```\n{"title": "bar"}\n```'
        assert _extract_json(raw).strip() == '{"title": "bar"}'


class TestGenerateBlogPost:
    @pytest.mark.asyncio
    async def test_success(self):
        """Mock a successful Claude API call and verify parsing."""
        fake_resp = _mock_httpx_response(200, _make_claude_json_response())

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=fake_resp)
        mock_client.is_closed = False

        with patch("app.autoblogger.generator._get_http_client", return_value=mock_client), \
             patch("app.autoblogger.generator.settings") as mock_settings:
            mock_settings.ANTHROPIC_API_KEY = "test-key"

            result = await generate_blog_post(
                topic="SEO Tips",
                keywords=["seo", "marketing"],
                language="en",
                word_count_target=1200,
            )

        assert isinstance(result, BlogGenerationResult)
        assert result.title == "10 Tips for Better SEO"
        assert result.slug == "10-tips-for-better-seo"
        assert result.ai_model == "claude-sonnet-4-20250514"
        assert result.input_tokens == 500
        assert result.output_tokens == 1200
        assert result.cost_usd > 0
        assert len(result.tags) == 3
        assert isinstance(result.schema_markup, dict)

    @pytest.mark.asyncio
    async def test_retry_on_429(self):
        """Verify retry logic on 429 status."""
        resp_429 = _mock_httpx_response(429, text="rate limited")
        resp_200 = _mock_httpx_response(200, _make_claude_json_response())

        call_count = 0

        async def _mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.HTTPStatusError(
                    "429", request=resp_429.request, response=resp_429
                )
            return resp_200

        mock_client = AsyncMock()
        mock_client.post = _mock_post
        mock_client.is_closed = False

        with patch("app.autoblogger.generator._get_http_client", return_value=mock_client), \
             patch("app.autoblogger.generator.settings") as mock_settings, \
             patch("app.autoblogger.generator.asyncio.sleep", new_callable=AsyncMock):
            mock_settings.ANTHROPIC_API_KEY = "test-key"

            result = await generate_blog_post(
                topic="SEO Tips", keywords=["seo"],
            )

        assert call_count == 2
        assert isinstance(result, BlogGenerationResult)

    @pytest.mark.asyncio
    async def test_retry_exhausted_on_500(self):
        """After max retries on 500, should raise RuntimeError."""
        resp_500 = _mock_httpx_response(500, text="server error")

        async def _always_500(*args, **kwargs):
            raise httpx.HTTPStatusError(
                "500", request=resp_500.request, response=resp_500
            )

        mock_client = AsyncMock()
        mock_client.post = _always_500
        mock_client.is_closed = False

        with patch("app.autoblogger.generator._get_http_client", return_value=mock_client), \
             patch("app.autoblogger.generator.settings") as mock_settings, \
             patch("app.autoblogger.generator.asyncio.sleep", new_callable=AsyncMock):
            mock_settings.ANTHROPIC_API_KEY = "test-key"

            with pytest.raises(RuntimeError, match="failed after"):
                await generate_blog_post(topic="Fail", keywords=["fail"])


# ===========================================================================
# Publisher tests
# ===========================================================================

class TestPublishResult:
    def test_fields(self):
        r = PublishResult(success=True, platform_post_id="abc", error=None)
        assert r.success is True
        assert r.platform_post_id == "abc"
        assert r.error is None

    def test_failure_fields(self):
        r = PublishResult(success=False, error="boom")
        assert r.success is False
        assert r.platform_post_id is None
        assert r.error == "boom"


class TestPublishPost:
    def _make_post_and_source(self, platform: PlatformType):
        post = MagicMock(spec=BlogPostAB)
        post.id = "post-1234-5678"
        source = MagicMock(spec=Source)
        source.platform = platform
        return post, source

    @pytest.mark.asyncio
    async def test_manual_returns_success(self):
        """MANUAL platform should succeed without calling any external API."""
        post, source = self._make_post_and_source(PlatformType.MANUAL)
        db = AsyncMock()

        result = await publish_post(db, post, source)

        assert result.success is True
        assert result.platform_post_id is not None
        assert result.platform_post_id.startswith("manual-")

    @pytest.mark.asyncio
    async def test_shopify_routing(self):
        """Verify SHOPIFY routes to publish_to_shopify."""
        post, source = self._make_post_and_source(PlatformType.SHOPIFY)
        db = AsyncMock()

        mock_shopify_fn = AsyncMock(
            return_value=PublishResult(success=True, platform_post_id="shopify-99"),
        )
        fake_module = MagicMock()
        fake_module.publish_to_shopify = mock_shopify_fn

        import sys
        with patch.dict(sys.modules, {"app.autoblogger.integrations.shopify": fake_module}):
            result = await publish_post(db, post, source)

        assert result.success is True
        assert result.platform_post_id == "shopify-99"
        mock_shopify_fn.assert_awaited_once_with(post, source)

    @pytest.mark.asyncio
    async def test_unknown_platform_returns_error(self):
        post = MagicMock(spec=BlogPostAB)
        post.id = "post-1234"
        source = MagicMock(spec=Source)
        source.platform = "NONEXISTENT"

        db = AsyncMock()
        result = await publish_post(db, post, source)

        assert result.success is False
        assert "Unknown platform" in result.error


# ===========================================================================
# Images tests
# ===========================================================================

class TestBuildImagePrompt:
    def test_includes_title_and_keywords(self):
        prompt = _build_image_prompt("My Blog Post", ["seo", "marketing"], "clean")
        assert "My Blog Post" in prompt
        assert "seo" in prompt
        assert "marketing" in prompt


class TestGenerateFeaturedImage:
    @pytest.mark.asyncio
    async def test_success_returns_url(self):
        """With a mocked Imagen API and upload, should return a public URL."""
        import base64

        fake_image_bytes = b"fake-png-data"
        imagen_response = _mock_httpx_response(200, {
            "predictions": [{"bytesBase64Encoded": base64.b64encode(fake_image_bytes).decode()}]
        })

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=imagen_response)
        mock_client.is_closed = False

        with patch("app.autoblogger.images._get_http_client", return_value=mock_client), \
             patch("app.autoblogger.images.settings") as mock_settings, \
             patch("app.autoblogger.images.upload_file", return_value="https://cdn.example.com/img.png"):
            mock_settings.GOOGLE_AI_API_KEY = "test-key"

            url = await generate_featured_image("Test Post", ["keyword"])

        assert url == "https://cdn.example.com/img.png"

    @pytest.mark.asyncio
    async def test_returns_none_on_api_failure(self):
        """If the Imagen API fails, should return None (graceful degradation)."""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.HTTPStatusError(
            "400",
            request=httpx.Request("POST", "https://example.com"),
            response=_mock_httpx_response(400, text="bad request"),
        ))
        mock_client.is_closed = False

        with patch("app.autoblogger.images._get_http_client", return_value=mock_client), \
             patch("app.autoblogger.images.settings") as mock_settings:
            mock_settings.GOOGLE_AI_API_KEY = "test-key"

            url = await generate_featured_image("Fail Post", ["fail"])

        assert url is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_api_key(self):
        """Without GOOGLE_AI_API_KEY, should skip and return None."""
        with patch("app.autoblogger.images.settings") as mock_settings:
            mock_settings.GOOGLE_AI_API_KEY = ""

            url = await generate_featured_image("No Key", ["test"])

        assert url is None
