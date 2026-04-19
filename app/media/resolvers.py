"""GraphQL resolvers for the media module."""

from __future__ import annotations

import logging

import strawberry
from sqlalchemy import select, func
from strawberry.types import Info

from app.auth.models import User
from app.auth.service import decode_access_token, get_user_by_id_cached, get_user_by_id
from app.database import get_db_session
from app.media.graphql_types import MediaFileType, MediaListType
from app.media.models import MediaFile
from app.media.service import delete_media_file
from app.media.router import USER_STORAGE_LIMIT

logger = logging.getLogger(__name__)


async def _get_user_from_context(info: Info) -> User:
    """Extract authenticated user from GraphQL context."""
    request = info.context.get("request")
    if not request:
        raise PermissionError("Not authenticated")

    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise PermissionError("Not authenticated")

    token = auth_header[7:]
    user_id = decode_access_token(token)
    if not user_id:
        raise PermissionError("Invalid token")

    user = await get_user_by_id_cached(user_id)
    if not user:
        async with get_db_session() as db:
            user = await get_user_by_id(db, user_id)
    if not user or not user.is_active:
        raise PermissionError("User not found or inactive")

    return user


def _media_to_gql(m: MediaFile) -> MediaFileType:
    return MediaFileType(
        id=m.id,
        filename=m.filename,
        original_filename=m.original_filename,
        content_type=m.content_type,
        size_bytes=m.size_bytes,
        folder=m.folder,
        url=m.url,
        width=m.width,
        height=m.height,
        created_at=m.created_at,
    )


@strawberry.type
class MediaQuery:
    @strawberry.field
    async def my_media(self, info: Info, folder: str = "") -> MediaListType:
        """List media files for the current user."""
        user = await _get_user_from_context(info)

        async with get_db_session() as db:
            # Get files in folder
            query = (
                select(MediaFile)
                .where(MediaFile.user_id == user.id, MediaFile.folder == folder)
                .order_by(MediaFile.created_at.desc())
            )
            result = await db.execute(query)
            files = result.scalars().all()

            # Get subfolders
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

            subfolders = set()
            for f in all_folders:
                relative = f[len(folder_prefix):] if folder_prefix else f
                if relative:
                    top_level = relative.split("/")[0]
                    if top_level:
                        subfolders.add(top_level)

            # Storage usage
            usage_result = await db.execute(
                select(func.coalesce(func.sum(MediaFile.size_bytes), 0)).where(
                    MediaFile.user_id == user.id
                )
            )
            total_used = usage_result.scalar_one()

        return MediaListType(
            files=[_media_to_gql(f) for f in files],
            folders=sorted(subfolders),
            current_folder=folder,
            storage_used=total_used,
            storage_limit=USER_STORAGE_LIMIT,
        )


@strawberry.type
class MediaMutation:
    @strawberry.mutation
    async def delete_media(self, info: Info, media_id: str) -> bool:
        """Delete a media file."""
        user = await _get_user_from_context(info)

        async with get_db_session() as db:
            result = await db.execute(
                select(MediaFile).where(
                    MediaFile.id == media_id, MediaFile.user_id == user.id
                )
            )
            media = result.scalar_one_or_none()
            if not media:
                raise ValueError("Filen hittades inte.")

            try:
                delete_media_file(media.url)
            except Exception:
                logger.warning("Failed to delete from storage: %s", media.url, exc_info=True)

            await db.delete(media)

        return True
