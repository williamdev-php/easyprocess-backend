"""Tests for AutoBlogger sanitization utilities and exception handling."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.autoblogger.sanitize import sanitize_html, sanitize_text
from app.autoblogger.exceptions import (
    AutoBloggerError,
    InsufficientCreditsError,
    PostGenerationError,
    PublishError,
    IntegrationError,
    InvalidSourceError,
    autoblogger_exception_handler,
    _STATUS_CODES,
)


# ── sanitize_html ──────────────────────────────────────────────────────────


class TestSanitizeHtml:
    def test_strips_script_tags_and_content(self):
        html = '<p>Hello</p><script>alert("xss")</script><p>World</p>'
        assert "<script" not in sanitize_html(html)
        assert "alert" not in sanitize_html(html)
        assert "<p>Hello</p>" in sanitize_html(html)
        assert "<p>World</p>" in sanitize_html(html)

    def test_strips_iframe_tags(self):
        html = '<p>Safe</p><iframe src="https://evil.com"></iframe>'
        result = sanitize_html(html)
        assert "<iframe" not in result
        assert "<p>Safe</p>" in result

    def test_strips_onclick_attribute(self):
        html = '<p onclick="alert(1)">Click me</p>'
        result = sanitize_html(html)
        assert "onclick" not in result
        assert "<p>" in result

    def test_strips_onerror_attribute(self):
        html = '<img onerror="alert(1)" src="x.jpg">'
        result = sanitize_html(html)
        assert "onerror" not in result

    def test_strips_onmouseover_attribute(self):
        html = '<div onmouseover="steal()">hover</div>'
        result = sanitize_html(html)
        assert "onmouseover" not in result

    def test_preserves_p_tag(self):
        assert "<p>" in sanitize_html("<p>text</p>")

    def test_preserves_strong_tag(self):
        assert "<strong>" in sanitize_html("<strong>bold</strong>")

    def test_preserves_em_tag(self):
        assert "<em>" in sanitize_html("<em>italic</em>")

    def test_preserves_heading_tags(self):
        for level in range(1, 7):
            tag = f"h{level}"
            html = f"<{tag}>Heading</{tag}>"
            result = sanitize_html(html)
            assert f"<{tag}>" in result
            assert f"</{tag}>" in result

    def test_preserves_list_tags(self):
        html = "<ul><li>Item 1</li></ul><ol><li>Item 2</li></ol>"
        result = sanitize_html(html)
        assert "<ul>" in result
        assert "<ol>" in result
        assert "<li>" in result

    def test_preserves_anchor_tag(self):
        result = sanitize_html("<a>link</a>")
        assert "<a>" in result

    def test_preserves_blockquote_code_pre(self):
        html = "<blockquote>quote</blockquote><code>x</code><pre>y</pre>"
        result = sanitize_html(html)
        assert "<blockquote>" in result
        assert "<code>" in result
        assert "<pre>" in result

    def test_preserves_href_on_links(self):
        html = '<a href="https://example.com" title="Example">link</a>'
        result = sanitize_html(html)
        assert 'href="https://example.com"' in result

    def test_strips_javascript_uri_in_href(self):
        html = '<a href="javascript:alert(1)">link</a>'
        result = sanitize_html(html)
        assert "javascript" not in result

    def test_nested_dangerous_content(self):
        html = '<div><script>alert("xss")</script></div>'
        result = sanitize_html(html)
        assert "<script" not in result
        assert "alert" not in result

    def test_empty_string(self):
        assert sanitize_html("") == ""

    def test_none_input(self):
        # sanitize_html guards with `if not content: return content`
        assert sanitize_html(None) is None

    def test_strips_style_tag(self):
        html = "<style>body{display:none}</style><p>visible</p>"
        result = sanitize_html(html)
        assert "<style" not in result
        assert "<p>visible</p>" in result

    def test_strips_object_embed_form_tags(self):
        html = "<object>bad</object><embed>bad</embed><form>bad</form>"
        result = sanitize_html(html)
        assert "<object" not in result
        assert "<embed" not in result
        assert "<form" not in result

    def test_unsafe_tag_content_preserved(self):
        # An unknown (but not dangerous) tag is stripped but inner text kept
        html = "<custom>inner text</custom>"
        result = sanitize_html(html)
        assert "inner text" in result
        assert "<custom" not in result


# ── sanitize_text ──────────────────────────────────────────────────────────


class TestSanitizeText:
    def test_strips_all_html_tags(self):
        html = "<p>Hello <strong>world</strong></p>"
        assert sanitize_text(html) == "Hello world"

    def test_returns_plain_text(self):
        assert sanitize_text("no tags here") == "no tags here"

    def test_handles_empty_string(self):
        assert sanitize_text("") == ""

    def test_handles_none(self):
        assert sanitize_text(None) is None

    def test_unescapes_html_entities(self):
        assert sanitize_text("&amp; &lt; &gt;") == "& < >"


# ── Exceptions ─────────────────────────────────────────────────────────────


class TestExceptions:
    def test_insufficient_credits_status_code(self):
        assert _STATUS_CODES[InsufficientCreditsError] == 402

    def test_post_generation_error_status_code(self):
        assert _STATUS_CODES[PostGenerationError] == 500

    def test_publish_error_status_code(self):
        assert _STATUS_CODES[PublishError] == 502

    def test_integration_error_status_code(self):
        assert _STATUS_CODES[IntegrationError] == 502

    def test_invalid_source_error_status_code(self):
        assert _STATUS_CODES[InvalidSourceError] == 422

    def test_all_inherit_from_autoblogger_error(self):
        for cls in (
            InsufficientCreditsError,
            PostGenerationError,
            PublishError,
            IntegrationError,
            InvalidSourceError,
        ):
            assert issubclass(cls, AutoBloggerError), f"{cls.__name__} does not inherit AutoBloggerError"

    def test_exception_stores_message_and_detail(self):
        exc = PostGenerationError(message="boom", detail={"key": "val"})
        assert exc.message == "boom"
        assert exc.detail == {"key": "val"}

    @pytest.mark.asyncio
    async def test_handler_returns_json_response(self):
        request = MagicMock()
        exc = InsufficientCreditsError(message="No credits left")
        response = await autoblogger_exception_handler(request, exc)

        assert response.status_code == 402
        # Decode the response body
        import json
        body = json.loads(response.body.decode())
        assert body["error"]["code"] == "INSUFFICIENT_CREDITS"
        assert body["error"]["message"] == "No credits left"

    @pytest.mark.asyncio
    async def test_handler_includes_detail_when_present(self):
        request = MagicMock()
        exc = PublishError(message="fail", detail={"reason": "timeout"})
        response = await autoblogger_exception_handler(request, exc)

        import json
        body = json.loads(response.body.decode())
        assert body["error"]["detail"] == {"reason": "timeout"}

    @pytest.mark.asyncio
    async def test_handler_omits_detail_when_none(self):
        request = MagicMock()
        exc = InvalidSourceError(message="bad source")
        response = await autoblogger_exception_handler(request, exc)

        import json
        body = json.loads(response.body.decode())
        assert "detail" not in body["error"]
