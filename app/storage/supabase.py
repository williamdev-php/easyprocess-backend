"""Supabase Storage helpers for file upload, deletion, and health checks."""

import logging
import uuid

import httpx

from app.config import settings


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
    }


def _make_key(file_name: str, prefix: str = "uploads") -> str:
    """Generate a unique object key to avoid collisions."""
    ext = ""
    if "." in file_name:
        ext = file_name.rsplit(".", 1)[-1]
    unique = uuid.uuid4().hex[:12]
    return f"{prefix}/{unique}.{ext}" if ext else f"{prefix}/{unique}"


def upload_file(
    file_data: bytes,
    file_name: str,
    content_type: str = "application/octet-stream",
    prefix: str = "uploads",
    timeout: float = 30.0,
) -> str:
    """Upload a file to Supabase Storage and return its public URL.

    For large files, pass a higher ``timeout`` (e.g. 120 for videos).
    Retries once on 5xx errors.
    """
    key = _make_key(file_name, prefix=prefix)
    bucket = settings.SUPABASE_STORAGE_BUCKET
    url = f"{settings.supabase_storage_url}/object/{bucket}/{key}"

    last_err: Exception | None = None
    for _attempt in range(2):
        try:
            resp = httpx.post(
                url,
                headers={**_headers(), "Content-Type": content_type},
                content=file_data,
                timeout=timeout,
            )
            resp.raise_for_status()
            return f"{settings.supabase_storage_url}/object/public/{bucket}/{key}"
        except httpx.HTTPStatusError as e:
            last_err = e
            if e.response.status_code < 500:
                raise
            # 5xx — retry once
            logging.getLogger(__name__).warning(
                "Supabase upload 5xx (attempt %d): %s", _attempt + 1, e,
            )
            continue
        except httpx.TimeoutException as e:
            last_err = e
            logging.getLogger(__name__).warning(
                "Supabase upload timeout (attempt %d): %s", _attempt + 1, e,
            )
            continue
    raise last_err  # type: ignore[misc]


def delete_file(url: str) -> None:
    """Delete a file from Supabase Storage given its public URL."""
    public_prefix = f"{settings.supabase_storage_url}/object/public/{settings.SUPABASE_STORAGE_BUCKET}/"
    if url.startswith(public_prefix):
        key = url[len(public_prefix):]
    else:
        key = url

    bucket = settings.SUPABASE_STORAGE_BUCKET
    resp = httpx.delete(
        f"{settings.supabase_storage_url}/object/{bucket}/{key}",
        headers=_headers(),
        timeout=10.0,
    )
    resp.raise_for_status()


def check_storage_health() -> bool:
    """Verify the Supabase Storage bucket exists and is accessible."""
    try:
        resp = httpx.get(
            f"{settings.supabase_storage_url}/bucket/{settings.SUPABASE_STORAGE_BUCKET}",
            headers=_headers(),
            timeout=5.0,
        )
        return resp.status_code == 200
    except Exception as e:
        logging.getLogger(__name__).error("Supabase storage health check failed: %s", e)
        return False
