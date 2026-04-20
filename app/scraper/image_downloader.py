"""
Download scraped images and upload them to Supabase Storage for reliable hosting.

Replaces external image URLs with Supabase URLs so generated sites don't depend
on the original server's hotlink policy or availability.
Includes image quality checks to ensure gallery-worthy resolution.
"""

from __future__ import annotations

import asyncio
import io
import logging
import mimetypes
from urllib.parse import urlparse

import httpx

from app.scraper.extractor import HEADERS, _is_safe_url
from app.storage.supabase import upload_file

logger = logging.getLogger(__name__)

_MAX_IMAGES = 20
_MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB
_DOWNLOAD_TIMEOUT = 15.0
_ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/svg+xml"}

# Minimum dimensions for gallery-quality images
_MIN_WIDTH = 200
_MIN_HEIGHT = 200


def _check_image_dimensions(data: bytes, content_type: str) -> tuple[int, int] | None:
    """Check image dimensions without full PIL dependency. Returns (width, height) or None."""
    try:
        if content_type == "image/png":
            # PNG: width at bytes 16-20, height at bytes 20-24 (big-endian)
            if len(data) >= 24 and data[:8] == b'\x89PNG\r\n\x1a\n':
                width = int.from_bytes(data[16:20], "big")
                height = int.from_bytes(data[20:24], "big")
                return (width, height)

        elif content_type in ("image/jpeg", "image/jpg"):
            # JPEG: scan for SOF markers
            i = 2
            while i < len(data) - 9:
                if data[i] != 0xFF:
                    break
                marker = data[i + 1]
                # SOF markers (0xC0-0xCF except 0xC4 and 0xC8)
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    height = int.from_bytes(data[i + 5:i + 7], "big")
                    width = int.from_bytes(data[i + 7:i + 9], "big")
                    return (width, height)
                # Skip to next marker
                length = int.from_bytes(data[i + 2:i + 4], "big")
                i += 2 + length

        elif content_type == "image/webp":
            # WebP: check for VP8 header
            if len(data) >= 30 and data[:4] == b'RIFF' and data[8:12] == b'WEBP':
                if data[12:16] == b'VP8 ':
                    width = int.from_bytes(data[26:28], "little") & 0x3FFF
                    height = int.from_bytes(data[28:30], "little") & 0x3FFF
                    return (width, height)
                elif data[12:16] == b'VP8L':
                    bits = int.from_bytes(data[21:25], "little")
                    width = (bits & 0x3FFF) + 1
                    height = ((bits >> 14) & 0x3FFF) + 1
                    return (width, height)

    except Exception as e:
        logger.debug("Failed to parse image dimensions (%s): %s", content_type, e)
    return None


async def _download_one(url: str, lead_id: str) -> tuple[str | None, tuple[int, int] | None]:
    """Download a single image and upload to Supabase Storage.

    Returns (public_url, (width, height)) or (None, None).
    """
    if not _is_safe_url(url):
        return None, None

    try:
        async with httpx.AsyncClient(
            headers=HEADERS, follow_redirects=True, timeout=_DOWNLOAD_TIMEOUT, max_redirects=3
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

            content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
            if content_type not in _ALLOWED_CONTENT_TYPES:
                return None, None

            if len(resp.content) > _MAX_IMAGE_SIZE:
                return None, None

            # Check dimensions
            dims = _check_image_dimensions(resp.content, content_type)
            if dims:
                w, h = dims
                if w < _MIN_WIDTH or h < _MIN_HEIGHT:
                    logger.debug("Image too small (%dx%d), skipping: %s", w, h, url[:80])
                    return None, None

            # Determine file extension from URL or content type
            path = urlparse(url).path
            ext = ""
            if "." in path.split("/")[-1]:
                ext = path.rsplit(".", 1)[-1].lower()
                # Strip query params from extension
                if "?" in ext:
                    ext = ext.split("?")[0]
            if not ext or len(ext) > 5:
                ext = mimetypes.guess_extension(content_type, strict=False) or ""
                ext = ext.lstrip(".")

            file_name = f"image.{ext}" if ext else "image"
            prefix = f"scraped-images/{lead_id}"

            stored_url = upload_file(
                file_data=resp.content,
                file_name=file_name,
                content_type=content_type,
                prefix=prefix,
            )
            return stored_url, dims

    except Exception as e:
        logger.warning("Failed to download image %s: %s", url, e)
        return None, None


async def _download_favicon(url: str, lead_id: str) -> str | None:
    """Download a favicon and upload to Supabase Storage. No dimension check."""
    if not _is_safe_url(url):
        return None

    try:
        async with httpx.AsyncClient(
            headers=HEADERS, follow_redirects=True, timeout=_DOWNLOAD_TIMEOUT, max_redirects=3
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

            content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
            allowed = _ALLOWED_CONTENT_TYPES | {"image/x-icon", "image/vnd.microsoft.icon"}
            if content_type not in allowed:
                return None

            if len(resp.content) > 1 * 1024 * 1024:  # 1 MB max for favicon
                return None

            path = urlparse(url).path
            ext = ""
            if "." in path.split("/")[-1]:
                ext = path.rsplit(".", 1)[-1].lower().split("?")[0]
            if not ext or len(ext) > 5:
                ext = "ico" if "icon" in content_type else (mimetypes.guess_extension(content_type, strict=False) or ".png").lstrip(".")

            stored_url = upload_file(
                file_data=resp.content,
                file_name=f"favicon.{ext}",
                content_type=content_type,
                prefix=f"scraped-images/{lead_id}",
            )
            return stored_url
    except Exception as e:
        logger.warning("Failed to download favicon %s: %s", url, e)
        return None


async def download_and_store_images(
    images: list[dict],
    logo_url: str | None,
    lead_id: str,
    favicon_url: str | None = None,
) -> tuple[list[dict], str | None, str | None]:
    """
    Download extracted images, logo, and favicon, upload to Supabase Storage.

    Returns (updated_images, updated_logo_url, updated_favicon_url) with storage URLs
    where successful. Original URLs are kept as fallback when download fails.
    Images that are too small are filtered out.
    """
    # Download logo first
    new_logo_url = logo_url
    if logo_url:
        stored_logo, _ = await _download_one(logo_url, lead_id)
        if stored_logo:
            new_logo_url = stored_logo

    # Download favicon
    new_favicon_url = favicon_url
    if favicon_url:
        stored_favicon = await _download_favicon(favicon_url, lead_id)
        if stored_favicon:
            new_favicon_url = stored_favicon

    # Download images (prioritise hero > gallery > team > general, limit to _MAX_IMAGES)
    priority = {"hero": 0, "gallery": 1, "team": 2, "general": 3}
    sorted_images = sorted(images, key=lambda img: priority.get(img.get("category", "general"), 3))
    to_download = sorted_images[:_MAX_IMAGES]

    tasks = [_download_one(img["url"], lead_id) for img in to_download]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    new_images = []
    for img, result in zip(to_download, results):
        if isinstance(result, tuple):
            stored_url, dims = result
            if stored_url:
                updated = {**img, "url": stored_url}
                if dims:
                    updated["width"] = dims[0]
                    updated["height"] = dims[1]
                new_images.append(updated)
            else:
                # Download failed or image too small — still keep original URL
                new_images.append(img)
        else:
            new_images.append(img)  # keep original URL as fallback

    # Add any remaining images beyond the download limit unchanged
    new_images.extend(sorted_images[_MAX_IMAGES:])

    logger.info(
        "Image download complete: %d/%d stored, logo=%s",
        sum(1 for img in new_images if "supabase" in img.get("url", "")),
        len(new_images),
        "stored" if new_logo_url != logo_url else "original",
    )

    return new_images, new_logo_url, new_favicon_url
