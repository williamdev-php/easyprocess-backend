"""Shopify integration — OAuth flow and blog post publishing via Shopify Admin API."""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Shopify API version
_API_VERSION = "2024-01"

# Rate limit: Shopify allows 2 requests per second for REST Admin API
_RATE_LIMIT_DELAY = 0.5  # seconds between requests

_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=30.0,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _http_client


async def close_http_client() -> None:
    global _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None


# ─── OAuth Flow ─────────────────────────────────────────────────────────────


def build_oauth_url(shop_domain: str, state: str, redirect_uri: str) -> str:
    """Build the Shopify OAuth authorization URL.

    Args:
        shop_domain: e.g. "mystore.myshopify.com"
        state: CSRF state parameter
        redirect_uri: The callback URL

    Returns:
        The full OAuth URL to redirect the user to.
    """
    shop = _normalize_shop_domain(shop_domain)
    params = {
        "client_id": settings.SHOPIFY_API_KEY,
        "scope": settings.SHOPIFY_SCOPES,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return f"https://{shop}/admin/oauth/authorize?{urlencode(params)}"


async def exchange_oauth_code(shop_domain: str, code: str) -> dict:
    """Exchange the OAuth code for a permanent access token.

    Returns: {"access_token": "...", "scope": "..."}
    """
    shop = _normalize_shop_domain(shop_domain)
    client = _get_http_client()

    resp = await client.post(
        f"https://{shop}/admin/oauth/access_token",
        json={
            "client_id": settings.SHOPIFY_API_KEY,
            "client_secret": settings.SHOPIFY_API_SECRET,
            "code": code,
        },
    )
    resp.raise_for_status()
    return resp.json()


def _normalize_shop_domain(shop: str) -> str:
    """Ensure the shop domain is in 'store.myshopify.com' format."""
    shop = shop.strip().lower()
    shop = re.sub(r'^https?://', '', shop)
    shop = shop.rstrip('/')
    if not shop.endswith('.myshopify.com'):
        shop = f"{shop}.myshopify.com"
    return shop


# ─── Shop API Helpers ───────────────────────────────────────────────────────


async def get_shop_info(shop_domain: str, access_token: str) -> dict:
    """Get shop info to verify connection."""
    shop = _normalize_shop_domain(shop_domain)
    client = _get_http_client()
    resp = await client.get(
        f"https://{shop}/admin/api/{_API_VERSION}/shop.json",
        headers={"X-Shopify-Access-Token": access_token},
    )
    resp.raise_for_status()
    return resp.json().get("shop", {})


async def list_blogs(shop_domain: str, access_token: str) -> list[dict]:
    """List all blogs in the Shopify store."""
    shop = _normalize_shop_domain(shop_domain)
    client = _get_http_client()
    resp = await client.get(
        f"https://{shop}/admin/api/{_API_VERSION}/blogs.json",
        headers={"X-Shopify-Access-Token": access_token},
    )
    resp.raise_for_status()
    return resp.json().get("blogs", [])


async def test_connection(shop_domain: str, access_token: str) -> dict:
    """Test Shopify connection — returns shop info or raises."""
    shop_info = await get_shop_info(shop_domain, access_token)
    blogs = await list_blogs(shop_domain, access_token)
    return {
        "shop_name": shop_info.get("name", ""),
        "shop_domain": shop_info.get("domain", ""),
        "blogs": [{"id": b["id"], "title": b["title"]} for b in blogs],
    }


# ─── Publishing ─────────────────────────────────────────────────────────────


async def publish_to_shopify(post, source) -> "PublishResult":
    """Publish a blog post to Shopify.

    Expects source.platform_config to contain:
    - access_token: str
    - shop_domain: str
    - blog_id: int (the Shopify blog ID to publish to)
    """
    from app.autoblogger.encryption import decrypt_platform_config
    from app.autoblogger.publisher import PublishResult

    config = decrypt_platform_config(source.platform_config) or {}
    access_token = config.get("access_token")
    shop_domain = config.get("shop_domain")
    blog_id = config.get("blog_id")

    if not access_token or not shop_domain:
        return PublishResult(success=False, error="Shopify credentials missing from source config")

    if not blog_id:
        # Try to get the default blog
        try:
            blogs = await list_blogs(shop_domain, access_token)
            if not blogs:
                return PublishResult(success=False, error="No blogs found in Shopify store")
            blog_id = blogs[0]["id"]
        except Exception as e:
            return PublishResult(success=False, error=f"Failed to fetch Shopify blogs: {e}")

    shop = _normalize_shop_domain(shop_domain)
    client = _get_http_client()

    # Build the article payload
    article_data = {
        "article": {
            "title": post.title,
            "body_html": post.content or "",
            "summary_html": post.excerpt or "",
            "tags": ", ".join(post.tags) if post.tags else "",
            "published": True,
        }
    }

    # Add featured image if available
    if post.featured_image_url:
        article_data["article"]["image"] = {"src": post.featured_image_url}

    # Add meta fields if supported
    if post.meta_title or post.meta_description:
        metafields = []
        if post.meta_title:
            metafields.append({
                "namespace": "global",
                "key": "title_tag",
                "value": post.meta_title,
                "type": "single_line_text_field",
            })
        if post.meta_description:
            metafields.append({
                "namespace": "global",
                "key": "description_tag",
                "value": post.meta_description,
                "type": "single_line_text_field",
            })
        article_data["article"]["metafields"] = metafields

    try:
        # Respect rate limits
        await asyncio.sleep(_RATE_LIMIT_DELAY)

        resp = await client.post(
            f"https://{shop}/admin/api/{_API_VERSION}/blogs/{blog_id}/articles.json",
            headers={"X-Shopify-Access-Token": access_token},
            json=article_data,
        )

        if resp.status_code == 429:
            # Rate limited — wait and retry once
            retry_after = float(resp.headers.get("Retry-After", "2"))
            logger.warning("Shopify rate limited, waiting %.1fs", retry_after)
            await asyncio.sleep(retry_after)
            resp = await client.post(
                f"https://{shop}/admin/api/{_API_VERSION}/blogs/{blog_id}/articles.json",
                headers={"X-Shopify-Access-Token": access_token},
                json=article_data,
            )

        resp.raise_for_status()
        article = resp.json().get("article", {})
        article_id = str(article.get("id", ""))

        logger.info("Published to Shopify: article_id=%s, shop=%s", article_id, shop)
        return PublishResult(success=True, platform_post_id=f"shopify-{article_id}")

    except httpx.HTTPStatusError as e:
        error_body = e.response.text[:500]
        logger.error("Shopify publish failed: %s — %s", e.response.status_code, error_body)
        return PublishResult(success=False, error=f"Shopify API error {e.response.status_code}: {error_body}")
    except Exception as e:
        logger.error("Shopify publish error: %s", e)
        return PublishResult(success=False, error=str(e))
