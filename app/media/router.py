"""Media REST endpoints for file upload, listing, and deletion."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.database import get_db
from app.media.models import MediaFile
from app.rate_limit import limiter
from app.media.service import (
    upload_media_file,
    delete_media_file,
    validate_file,
    MAX_FILE_SIZE,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/media", tags=["media"])

# Per-user storage limit: 100 MB
USER_STORAGE_LIMIT = 100 * 1024 * 1024


@router.post("/upload", status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def upload(
    request: Request,
    file: UploadFile = File(...),
    folder: str = Form(""),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a media file with automatic image compression."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Inget filnamn angett.")

    content_type = file.content_type or "application/octet-stream"

    # Read file data
    file_data = await file.read()
    if not file_data:
        raise HTTPException(status_code=400, detail="Tom fil.")

    # Validate
    try:
        validate_file(content_type, len(file_data), file.filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Check user storage quota
    result = await db.execute(
        select(func.coalesce(func.sum(MediaFile.size_bytes), 0)).where(
            MediaFile.user_id == user.id
        )
    )
    total_used = result.scalar_one()
    if total_used + len(file_data) > USER_STORAGE_LIMIT:
        max_mb = USER_STORAGE_LIMIT // (1024 * 1024)
        raise HTTPException(
            status_code=400,
            detail=f"Lagringsgränsen ({max_mb} MB) har nåtts. Ta bort filer för att frigöra utrymme.",
        )

    # Upload to storage
    try:
        url, stored_filename, size, final_type, width, height = upload_media_file(
            file_data, file.filename, content_type, user.id, folder
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Media upload failed")
        raise HTTPException(status_code=500, detail="Uppladdningen misslyckades.")

    # Save to database
    media = MediaFile(
        user_id=user.id,
        filename=stored_filename,
        original_filename=file.filename,
        content_type=final_type,
        size_bytes=size,
        folder=folder,
        url=url,
        width=width,
        height=height,
    )
    db.add(media)
    await db.flush()

    return {
        "id": media.id,
        "filename": media.filename,
        "original_filename": media.original_filename,
        "content_type": media.content_type,
        "size_bytes": media.size_bytes,
        "folder": media.folder,
        "url": media.url,
        "width": media.width,
        "height": media.height,
        "created_at": media.created_at.isoformat(),
    }


@router.get("")
async def list_media(
    folder: str = "",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List media files for the current user, optionally filtered by folder."""
    query = (
        select(MediaFile)
        .where(MediaFile.user_id == user.id, MediaFile.folder == folder)
        .order_by(MediaFile.created_at.desc())
    )
    result = await db.execute(query)
    files = result.scalars().all()

    # Get distinct subfolders within the current folder
    folder_prefix = f"{folder}/" if folder else ""
    all_folders_q = (
        select(MediaFile.folder)
        .where(
            MediaFile.user_id == user.id,
            MediaFile.folder.like(f"{folder_prefix}%" if folder_prefix else "%"),
            MediaFile.folder != folder,
        )
        .distinct()
    )
    folder_result = await db.execute(all_folders_q)
    all_folders = folder_result.scalars().all()

    # Extract immediate child folder names
    subfolders = set()
    for f in all_folders:
        relative = f[len(folder_prefix):] if folder_prefix else f
        if relative:
            top_level = relative.split("/")[0]
            if top_level:
                subfolders.add(top_level)

    # Get storage usage
    usage_result = await db.execute(
        select(func.coalesce(func.sum(MediaFile.size_bytes), 0)).where(
            MediaFile.user_id == user.id
        )
    )
    total_used = usage_result.scalar_one()

    return {
        "files": [
            {
                "id": f.id,
                "filename": f.filename,
                "original_filename": f.original_filename,
                "content_type": f.content_type,
                "size_bytes": f.size_bytes,
                "folder": f.folder,
                "url": f.url,
                "width": f.width,
                "height": f.height,
                "created_at": f.created_at.isoformat(),
            }
            for f in files
        ],
        "folders": sorted(subfolders),
        "current_folder": folder,
        "storage_used": total_used,
        "storage_limit": USER_STORAGE_LIMIT,
    }


@router.delete("/{media_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def delete_media(
    request: Request,
    media_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a media file."""
    result = await db.execute(
        select(MediaFile).where(MediaFile.id == media_id, MediaFile.user_id == user.id)
    )
    media = result.scalar_one_or_none()
    if not media:
        raise HTTPException(status_code=404, detail="Filen hittades inte.")

    # Delete from storage
    try:
        delete_media_file(media.url)
    except Exception:
        logger.warning("Failed to delete file from storage: %s", media.url, exc_info=True)

    await db.delete(media)


@router.post("/folders", status_code=status.HTTP_201_CREATED)
async def create_folder(
    folder_name: str = Form(...),
    parent_folder: str = Form(""),
    user: User = Depends(get_current_user),
):
    """Create a folder (virtual — folders are just prefixes on files).

    Returns the full folder path for client use. No DB entry needed since
    folders are derived from the `folder` field on MediaFile records.
    """
    # Sanitize
    safe_name = "".join(
        c for c in folder_name.strip() if c.isalnum() or c in "-_ "
    )[:50]
    if not safe_name:
        raise HTTPException(status_code=400, detail="Ogiltigt mappnamn.")

    full_path = f"{parent_folder}/{safe_name}" if parent_folder else safe_name
    return {"folder": full_path}
