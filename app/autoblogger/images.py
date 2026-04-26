"""NanoBanana 2 — Google Imagen 3 image generation for blog featured images."""

from __future__ import annotations

import base64
import logging
from uuid import uuid4

import httpx

from app.config import settings
from app.storage.supabase import upload_file

logger = logging.getLogger(__name__)

_IMAGEN_URL = (
    "https://generativelanguage.googleapis.com/v1beta/"
    "models/imagen-3.0-generate-002:predict"
)

_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=httpx.Timeout(60.0))
    return _http_client


async def close_http_client() -> None:
    """Shut down the shared HTTP client (call on app shutdown)."""
    global _http_client
    if _http_client is not None and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None


def _build_prompt(title: str, keywords: list[str], style: str) -> str:
    kw_text = ", ".join(keywords) if keywords else ""
    return (
        f'Professional blog header image for article titled "{title}". '
        f"Keywords: {kw_text}. "
        f"Style: {style}. Clean, modern, suitable for a professional blog. "
        "No text or watermarks in the image."
    )


async def _call_imagen(prompt: str) -> bytes | None:
    """Call Google Imagen 3 API and return raw image bytes, or None on failure."""
    client = _get_http_client()
    payload = {
        "instances": [{"prompt": prompt}],
        "parameters": {
            "sampleCount": 1,
            "aspectRatio": "16:9",
            "safetyFilterLevel": "BLOCK_MEDIUM_AND_ABOVE",
        },
    }
    params = {"key": settings.GOOGLE_AI_API_KEY}

    last_exc: Exception | None = None
    for attempt in range(2):  # retry once on 5xx
        try:
            resp = await client.post(_IMAGEN_URL, json=payload, params=params)
            if resp.status_code >= 500 and attempt == 0:
                logger.warning(
                    "Imagen API returned %s, retrying once…", resp.status_code
                )
                continue
            resp.raise_for_status()
            data = resp.json()
            b64 = data["predictions"][0]["bytesBase64Encoded"]
            return base64.b64decode(b64)
        except Exception as exc:
            last_exc = exc
            if attempt == 0:
                logger.warning("Imagen API error (attempt 1): %s", exc)
                continue
            break

    logger.warning("Imagen API failed after retries: %s", last_exc)
    return None


async def generate_featured_image(
    title: str,
    keywords: list[str],
    brand_images: list[str] | None = None,  # URLs for style reference (future use)
    style: str = "professional blog header",
) -> str | None:
    """Generate a featured image and upload to Supabase Storage.

    Returns the public URL of the uploaded image, or None on failure.
    """
    if not getattr(settings, "GOOGLE_AI_API_KEY", None):
        logger.warning("GOOGLE_AI_API_KEY not set — skipping image generation")
        return None

    prompt = _build_prompt(title, keywords, style)
    logger.info("Generating featured image for: %s", title)

    image_bytes = await _call_imagen(prompt)
    if image_bytes is None:
        return None

    file_name = f"blog-{uuid4().hex[:8]}.png"
    try:
        public_url = upload_file(
            image_bytes,
            file_name,
            content_type="image/png",
            prefix="autoblogger/images",
        )
        logger.info("Uploaded featured image: %s", public_url)
        return public_url
    except Exception as exc:
        logger.warning("Failed to upload featured image: %s", exc)
        return None
