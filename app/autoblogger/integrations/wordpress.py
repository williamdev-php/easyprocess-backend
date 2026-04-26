"""WordPress REST API integration -- publish posts to WordPress sites.

Uses the WordPress REST API (wp-json/wp/v2/posts) with Application Passwords
for authentication.
"""
from __future__ import annotations

import base64
import logging

import httpx

logger = logging.getLogger(__name__)

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


def _build_auth_header(username: str, app_password: str) -> str:
    """Build Basic auth header from WordPress username + Application Password."""
    credentials = f"{username}:{app_password}"
    encoded = base64.b64encode(credentials.encode()).decode()
    return f"Basic {encoded}"


def _normalize_api_url(url: str) -> str:
    """Ensure URL ends with /wp-json/wp/v2."""
    url = url.strip().rstrip("/")
    if not url.endswith("/wp-json/wp/v2"):
        if url.endswith("/wp-json"):
            url += "/wp/v2"
        elif not url.endswith("/wp/v2"):
            url += "/wp-json/wp/v2"
    return url


async def test_connection(api_url: str, username: str, app_password: str) -> dict:
    """Test WordPress connection by fetching user info.

    Returns: {"connected": True, "site_name": "...", "user": "..."} or raises.
    """
    base_url = _normalize_api_url(api_url)
    client = _get_http_client()
    auth = _build_auth_header(username, app_password)

    # Test by fetching "users/me"
    resp = await client.get(
        f"{base_url}/users/me",
        headers={"Authorization": auth},
    )
    resp.raise_for_status()
    user_data = resp.json()

    # Also get site title from wp-json root
    root_url = base_url.replace("/wp/v2", "")
    root_resp = await client.get(root_url)
    root_data = root_resp.json() if root_resp.status_code == 200 else {}

    return {
        "connected": True,
        "site_name": root_data.get("name", ""),
        "site_url": root_data.get("url", api_url),
        "user": user_data.get("name", username),
    }


async def _upload_featured_image(
    base_url: str, auth: str, image_url: str, title: str
) -> int | None:
    """Download an image from URL and upload it to WordPress media library.

    Returns the WordPress media ID or None on failure.
    """
    client = _get_http_client()

    try:
        # Download the image
        img_resp = await client.get(image_url, follow_redirects=True)
        img_resp.raise_for_status()
        image_bytes = img_resp.content
        content_type = img_resp.headers.get("content-type", "image/png")

        # Determine file extension
        ext = "png"
        if "jpeg" in content_type or "jpg" in content_type:
            ext = "jpg"
        elif "webp" in content_type:
            ext = "webp"

        filename = f"{title[:50].replace(' ', '-').lower()}.{ext}"

        # Upload to WordPress
        resp = await client.post(
            f"{base_url}/media",
            headers={
                "Authorization": auth,
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Type": content_type,
            },
            content=image_bytes,
        )
        resp.raise_for_status()
        return resp.json().get("id")
    except Exception as e:
        logger.warning("Failed to upload featured image to WordPress: %s", e)
        return None


async def publish_to_wordpress(post, source) -> "PublishResult":
    """Publish a blog post to WordPress via REST API.

    Expects source.platform_config to contain:
    - api_url: str (WordPress site URL, e.g. "https://example.com")
    - username: str
    - app_password: str (WordPress Application Password)
    """
    from app.autoblogger.encryption import decrypt_platform_config
    from app.autoblogger.publisher import PublishResult

    config = decrypt_platform_config(source.platform_config) or {}
    api_url = config.get("api_url")
    username = config.get("username")
    app_password = config.get("app_password")

    if not api_url or not username or not app_password:
        return PublishResult(success=False, error="WordPress credentials missing from source config")

    base_url = _normalize_api_url(api_url)
    client = _get_http_client()
    auth = _build_auth_header(username, app_password)

    # Upload featured image first if available
    featured_media_id = None
    if post.featured_image_url:
        featured_media_id = await _upload_featured_image(
            base_url, auth, post.featured_image_url, post.title
        )

    # Build post payload
    post_data = {
        "title": post.title,
        "content": post.content or "",
        "excerpt": post.excerpt or "",
        "status": "publish",
        "slug": post.slug or "",
    }

    if featured_media_id:
        post_data["featured_media"] = featured_media_id

    # Add Yoast SEO meta if the plugin is installed (best-effort)
    meta = {}
    if post.meta_title:
        meta["yoast_wpseo_title"] = post.meta_title
    if post.meta_description:
        meta["yoast_wpseo_metadesc"] = post.meta_description
    if meta:
        post_data["meta"] = meta

    try:
        resp = await client.post(
            f"{base_url}/posts",
            headers={"Authorization": auth, "Content-Type": "application/json"},
            json=post_data,
        )
        resp.raise_for_status()
        wp_post = resp.json()
        wp_post_id = str(wp_post.get("id", ""))

        # Try to set tags (best-effort)
        if post.tags:
            try:
                await _set_wordpress_tags(base_url, auth, wp_post_id, post.tags)
            except Exception:
                logger.warning("Failed to set tags on WordPress post %s", wp_post_id)

        logger.info("Published to WordPress: post_id=%s, url=%s", wp_post_id, wp_post.get("link", ""))
        return PublishResult(success=True, platform_post_id=f"wp-{wp_post_id}")

    except httpx.HTTPStatusError as e:
        error_body = e.response.text[:500]
        logger.error("WordPress publish failed: %s -- %s", e.response.status_code, error_body)
        return PublishResult(success=False, error=f"WordPress API error {e.response.status_code}: {error_body}")
    except Exception as e:
        logger.error("WordPress publish error: %s", e)
        return PublishResult(success=False, error=str(e))


async def _set_wordpress_tags(base_url: str, auth: str, post_id: str, tags: list[str]) -> None:
    """Create tags and assign them to a WordPress post."""
    client = _get_http_client()
    tag_ids = []

    for tag_name in tags[:10]:  # Limit to 10 tags
        # Try to find or create the tag
        resp = await client.get(
            f"{base_url}/tags",
            headers={"Authorization": auth},
            params={"search": tag_name, "per_page": 1},
        )
        existing = resp.json() if resp.status_code == 200 else []

        if existing:
            tag_ids.append(existing[0]["id"])
        else:
            # Create the tag
            create_resp = await client.post(
                f"{base_url}/tags",
                headers={"Authorization": auth, "Content-Type": "application/json"},
                json={"name": tag_name},
            )
            if create_resp.status_code in (200, 201):
                tag_ids.append(create_resp.json()["id"])

    if tag_ids:
        await client.post(
            f"{base_url}/posts/{post_id}",
            headers={"Authorization": auth, "Content-Type": "application/json"},
            json={"tags": tag_ids},
        )
