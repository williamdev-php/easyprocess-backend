"""Media service — image compression, validation, and storage."""

import io
import logging
import uuid
from typing import BinaryIO

from PIL import Image

from app.config import settings
from app.storage.supabase import upload_file, delete_file

logger = logging.getLogger(__name__)

# Limits
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_IMAGE_DIMENSION = 4096  # Max width/height after resize
WEBP_QUALITY = 82

ALLOWED_IMAGE_TYPES = {
    "image/jpeg", "image/png", "image/webp", "image/gif", "image/svg+xml",
}
ALLOWED_DOCUMENT_TYPES = {
    "application/pdf",
}
ALLOWED_VIDEO_TYPES = {
    "video/mp4", "video/webm", "video/quicktime",
}
ALLOWED_TYPES = ALLOWED_IMAGE_TYPES | ALLOWED_DOCUMENT_TYPES | ALLOWED_VIDEO_TYPES

# Types that should be compressed to WebP
COMPRESSIBLE_IMAGE_TYPES = {"image/jpeg", "image/png"}


def validate_file(content_type: str, size: int, filename: str) -> None:
    """Validate file type and size. Raises ValueError on invalid input."""
    if content_type not in ALLOWED_TYPES:
        raise ValueError(
            f"Filtypen '{content_type}' stöds inte. "
            f"Tillåtna typer: bilder (JPEG, PNG, WebP, GIF, SVG), PDF, video (MP4, WebM)."
        )
    if size > MAX_FILE_SIZE:
        max_mb = MAX_FILE_SIZE // (1024 * 1024)
        raise ValueError(f"Filen är för stor. Maxstorlek: {max_mb} MB.")
    if not filename or len(filename) > 255:
        raise ValueError("Ogiltigt filnamn.")


def compress_image(file_data: bytes, content_type: str) -> tuple[bytes, str, int | None, int | None]:
    """Compress an image to WebP format if applicable.

    Returns (compressed_bytes, new_content_type, width, height).
    For non-compressible types, returns the original data unchanged.
    """
    if content_type not in COMPRESSIBLE_IMAGE_TYPES:
        # For WebP/GIF/SVG, just extract dimensions if possible
        width, height = None, None
        if content_type in ALLOWED_IMAGE_TYPES and content_type != "image/svg+xml":
            try:
                with Image.open(io.BytesIO(file_data)) as img:
                    width, height = img.size
            except Exception:
                pass
        return file_data, content_type, width, height

    try:
        with Image.open(io.BytesIO(file_data)) as img:
            # Convert RGBA/P to RGB for WebP compatibility
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGBA")
            elif img.mode != "RGB":
                img = img.convert("RGB")

            # Downscale if too large
            if img.width > MAX_IMAGE_DIMENSION or img.height > MAX_IMAGE_DIMENSION:
                img.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION), Image.LANCZOS)

            width, height = img.size

            # Compress to WebP
            buf = io.BytesIO()
            img.save(buf, format="WEBP", quality=WEBP_QUALITY, method=4)
            compressed = buf.getvalue()

            # Only use compressed version if it's actually smaller
            if len(compressed) < len(file_data):
                logger.info(
                    "Compressed image %d bytes -> %d bytes (%.0f%% reduction)",
                    len(file_data), len(compressed),
                    (1 - len(compressed) / len(file_data)) * 100,
                )
                return compressed, "image/webp", width, height

            return file_data, content_type, width, height
    except Exception:
        logger.warning("Image compression failed, using original", exc_info=True)
        return file_data, content_type, None, None


def get_storage_prefix(user_id: str, folder: str = "") -> str:
    """Build the Supabase storage prefix for a user's media files."""
    base = f"media/{user_id}"
    if folder:
        # Sanitize folder path
        parts = [p.strip() for p in folder.split("/") if p.strip() and p != ".."]
        if parts:
            base = f"{base}/{'/'.join(parts)}"
    return base


def upload_media_file(
    file_data: bytes,
    filename: str,
    content_type: str,
    user_id: str,
    folder: str = "",
) -> tuple[str, str, int, str, int | None, int | None]:
    """Process, compress (if applicable), and upload a media file.

    Returns (url, stored_filename, size_bytes, final_content_type, width, height).
    """
    validate_file(content_type, len(file_data), filename)

    # Compress images
    processed_data, final_content_type, width, height = compress_image(file_data, content_type)

    # Determine file extension
    ext_map = {
        "image/webp": "webp",
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/gif": "gif",
        "image/svg+xml": "svg",
        "application/pdf": "pdf",
        "video/mp4": "mp4",
        "video/webm": "webm",
        "video/quicktime": "mov",
    }
    ext = ext_map.get(final_content_type, "bin")

    # Generate unique filename
    unique_id = uuid.uuid4().hex[:12]
    # Keep a sanitized version of the original name for readability
    safe_name = "".join(c for c in filename.rsplit(".", 1)[0] if c.isalnum() or c in "-_ ")[:40]
    stored_filename = f"{safe_name}_{unique_id}.{ext}"

    prefix = get_storage_prefix(user_id, folder)
    url = upload_file(processed_data, stored_filename, final_content_type, prefix=prefix)

    return url, stored_filename, len(processed_data), final_content_type, width, height


def delete_media_file(url: str) -> None:
    """Delete a media file from storage."""
    delete_file(url)
