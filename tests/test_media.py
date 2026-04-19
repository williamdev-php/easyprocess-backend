"""Tests for the media module — compression, validation, and service logic."""

from __future__ import annotations

import io
from unittest.mock import patch, MagicMock

import pytest
import pytest_asyncio
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.media.models  # noqa: F401 — register model on Base
from app.media.models import MediaFile
from app.media.service import (
    validate_file,
    compress_image,
    get_storage_prefix,
    upload_media_file,
    MAX_FILE_SIZE,
    ALLOWED_TYPES,
    WEBP_QUALITY,
)


# ---------------------------------------------------------------------------
# validate_file tests
# ---------------------------------------------------------------------------


class TestValidateFile:
    def test_valid_image_types(self):
        for ct in ["image/jpeg", "image/png", "image/webp", "image/gif", "image/svg+xml"]:
            validate_file(ct, 1000, "test.jpg")

    def test_valid_document_types(self):
        validate_file("application/pdf", 5000, "doc.pdf")

    def test_valid_video_types(self):
        for ct in ["video/mp4", "video/webm", "video/quicktime"]:
            validate_file(ct, 1000, "video.mp4")

    def test_invalid_content_type(self):
        with pytest.raises(ValueError, match="stöds inte"):
            validate_file("text/html", 1000, "page.html")

    def test_invalid_executable(self):
        with pytest.raises(ValueError, match="stöds inte"):
            validate_file("application/x-executable", 1000, "evil.exe")

    def test_file_too_large(self):
        with pytest.raises(ValueError, match="för stor"):
            validate_file("image/jpeg", MAX_FILE_SIZE + 1, "big.jpg")

    def test_file_at_limit(self):
        # Should not raise
        validate_file("image/jpeg", MAX_FILE_SIZE, "at-limit.jpg")

    def test_empty_filename(self):
        with pytest.raises(ValueError, match="filnamn"):
            validate_file("image/jpeg", 1000, "")

    def test_long_filename(self):
        with pytest.raises(ValueError, match="filnamn"):
            validate_file("image/jpeg", 1000, "x" * 256)


# ---------------------------------------------------------------------------
# compress_image tests
# ---------------------------------------------------------------------------


def _make_test_image(fmt: str = "PNG", size: tuple = (200, 200), color: str = "red") -> bytes:
    """Create a test image in the given format."""
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def _make_rgba_image() -> bytes:
    """Create a test RGBA PNG image."""
    img = Image.new("RGBA", (200, 200), (255, 0, 0, 128))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestCompressImage:
    def test_png_to_webp(self):
        png_data = _make_test_image("PNG", (500, 500))
        result, content_type, w, h = compress_image(png_data, "image/png")
        # Should convert to WebP (or keep original if larger)
        assert content_type in ("image/webp", "image/png")
        assert w == 500
        assert h == 500

    def test_jpeg_to_webp(self):
        jpeg_data = _make_test_image("JPEG", (400, 300))
        result, content_type, w, h = compress_image(jpeg_data, "image/jpeg")
        assert content_type in ("image/webp", "image/jpeg")
        assert w == 400
        assert h == 300

    def test_webp_passthrough(self):
        """WebP images should not be re-compressed."""
        webp_data = _make_test_image("WEBP", (100, 100))
        result, content_type, w, h = compress_image(webp_data, "image/webp")
        assert content_type == "image/webp"
        assert result == webp_data  # unchanged

    def test_gif_passthrough(self):
        gif_data = _make_test_image("GIF", (50, 50))
        result, content_type, w, h = compress_image(gif_data, "image/gif")
        assert content_type == "image/gif"
        assert result == gif_data

    def test_svg_passthrough(self):
        svg_data = b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"></svg>'
        result, content_type, w, h = compress_image(svg_data, "image/svg+xml")
        assert content_type == "image/svg+xml"
        assert result == svg_data
        assert w is None  # SVGs don't have pixel dimensions

    def test_rgba_conversion(self):
        """RGBA images should be handled without errors."""
        rgba_data = _make_rgba_image()
        result, content_type, w, h = compress_image(rgba_data, "image/png")
        assert content_type in ("image/webp", "image/png")
        assert w == 200
        assert h == 200

    def test_large_image_downscaled(self):
        """Images larger than MAX_IMAGE_DIMENSION should be downscaled."""
        large_data = _make_test_image("PNG", (5000, 3000))
        result, content_type, w, h = compress_image(large_data, "image/png")
        # Should be downscaled to fit within 4096x4096
        assert w is not None and h is not None
        assert w <= 4096
        assert h <= 4096

    def test_dimensions_extracted(self):
        data = _make_test_image("PNG", (800, 600))
        _, _, w, h = compress_image(data, "image/png")
        assert w == 800
        assert h == 600

    def test_corrupt_image_returns_original(self):
        """Corrupt image data should return original without crashing."""
        corrupt = b"not an image at all"
        result, content_type, w, h = compress_image(corrupt, "image/png")
        assert result == corrupt
        assert content_type == "image/png"
        assert w is None
        assert h is None


# ---------------------------------------------------------------------------
# get_storage_prefix tests
# ---------------------------------------------------------------------------


class TestGetStoragePrefix:
    def test_default(self):
        assert get_storage_prefix("user123") == "media/user123"

    def test_with_folder(self):
        assert get_storage_prefix("user123", "gallery") == "media/user123/gallery"

    def test_nested_folder(self):
        assert get_storage_prefix("u1", "a/b/c") == "media/u1/a/b/c"

    def test_traversal_prevented(self):
        """Path traversal attempts should be stripped."""
        result = get_storage_prefix("u1", "../../../etc")
        assert ".." not in result

    def test_empty_folder(self):
        assert get_storage_prefix("u1", "") == "media/u1"

    def test_whitespace_folder(self):
        assert get_storage_prefix("u1", "  ") == "media/u1"


# ---------------------------------------------------------------------------
# upload_media_file tests (with mocked storage)
# ---------------------------------------------------------------------------


class TestUploadMediaFile:
    @patch("app.media.service.upload_file")
    def test_uploads_image_with_compression(self, mock_upload: MagicMock):
        mock_upload.return_value = "https://storage.example.com/media/u1/test_abc123.webp"

        png_data = _make_test_image("PNG", (300, 300))
        url, filename, size, content_type, w, h = upload_media_file(
            png_data, "photo.png", "image/png", "user123", "gallery"
        )

        assert mock_upload.called
        assert "photo" in filename
        assert w == 300
        assert h == 300
        assert url.startswith("https://")

    @patch("app.media.service.upload_file")
    def test_uploads_pdf_without_compression(self, mock_upload: MagicMock):
        mock_upload.return_value = "https://storage.example.com/media/u1/doc_abc123.pdf"

        pdf_data = b"%PDF-1.4 fake pdf content"
        url, filename, size, content_type, w, h = upload_media_file(
            pdf_data, "document.pdf", "application/pdf", "user123"
        )

        assert content_type == "application/pdf"
        assert filename.endswith(".pdf")
        assert w is None
        assert h is None

    def test_rejects_invalid_type(self):
        with pytest.raises(ValueError, match="stöds inte"):
            upload_media_file(b"data", "evil.exe", "application/x-executable", "user1")

    def test_rejects_oversized_file(self):
        with pytest.raises(ValueError, match="för stor"):
            upload_media_file(
                b"x" * (MAX_FILE_SIZE + 1), "big.jpg", "image/jpeg", "user1"
            )

    @patch("app.media.service.upload_file")
    def test_unique_filenames(self, mock_upload: MagicMock):
        mock_upload.return_value = "https://example.com/file"
        png_data = _make_test_image("PNG", (10, 10))

        _, fn1, *_ = upload_media_file(png_data, "same.png", "image/png", "u1")
        _, fn2, *_ = upload_media_file(png_data, "same.png", "image/png", "u1")

        # Filenames should be unique due to UUID component
        assert fn1 != fn2


# ---------------------------------------------------------------------------
# MediaFile model tests (database)
# ---------------------------------------------------------------------------


class TestMediaFileModel:
    @pytest.mark.asyncio
    async def test_create_and_query(self, db: AsyncSession):
        media = MediaFile(
            user_id="test-user-id",
            filename="test_abc123.webp",
            original_filename="photo.png",
            content_type="image/webp",
            size_bytes=12345,
            folder="gallery",
            url="https://storage.example.com/media/test-user-id/gallery/test_abc123.webp",
            width=800,
            height=600,
        )
        db.add(media)
        await db.flush()

        result = await db.execute(
            select(MediaFile).where(MediaFile.user_id == "test-user-id")
        )
        found = result.scalar_one()
        assert found.original_filename == "photo.png"
        assert found.content_type == "image/webp"
        assert found.folder == "gallery"
        assert found.width == 800

    @pytest.mark.asyncio
    async def test_folder_filtering(self, db: AsyncSession):
        for folder in ["gallery", "gallery", "team", ""]:
            media = MediaFile(
                user_id="u1",
                filename=f"f_{folder}.webp",
                original_filename="f.png",
                content_type="image/webp",
                size_bytes=100,
                folder=folder,
                url=f"https://example.com/{folder}/f.webp",
            )
            db.add(media)
        await db.flush()

        result = await db.execute(
            select(MediaFile).where(
                MediaFile.user_id == "u1", MediaFile.folder == "gallery"
            )
        )
        gallery_files = result.scalars().all()
        assert len(gallery_files) == 2

    @pytest.mark.asyncio
    async def test_cascade_fields(self, db: AsyncSession):
        media = MediaFile(
            user_id="u2",
            filename="vid.mp4",
            original_filename="video.mp4",
            content_type="video/mp4",
            size_bytes=5000000,
            folder="",
            url="https://example.com/vid.mp4",
            width=None,
            height=None,
        )
        db.add(media)
        await db.flush()

        assert media.id is not None
        assert media.created_at is not None
        assert media.width is None
