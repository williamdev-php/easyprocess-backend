"""GraphQL types for the media module."""

from __future__ import annotations

from datetime import datetime

import strawberry


@strawberry.type
class MediaFileType:
    id: str
    filename: str
    original_filename: str
    content_type: str
    size_bytes: int
    folder: str
    url: str
    width: int | None
    height: int | None
    created_at: datetime


@strawberry.type
class MediaListType:
    files: list[MediaFileType]
    folders: list[str]
    current_folder: str
    storage_used: int
    storage_limit: int
