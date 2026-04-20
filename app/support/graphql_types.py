from __future__ import annotations

import enum

import strawberry


@strawberry.enum
class TicketStatusGQL(enum.Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


@strawberry.enum
class TicketPriorityGQL(enum.Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"


@strawberry.type
class SupportTicketType:
    id: str
    user_id: str | None
    user_email: str | None
    user_name: str | None
    subject: str
    message: str
    status: str
    priority: str
    is_read: bool
    is_archived: bool
    admin_reply: str | None
    replied_at: str | None
    created_at: str
    updated_at: str


@strawberry.type
class SupportTicketListType:
    items: list[SupportTicketType]
    total: int
    page: int
    page_size: int


@strawberry.input
class CreateSupportTicketInput:
    subject: str
    message: str


@strawberry.input
class UpdateSupportTicketInput:
    ticket_id: str
    status: str | None = None
    priority: str | None = None
    admin_reply: str | None = None


@strawberry.input
class SupportTicketFilterInput:
    status: str | None = None
    is_read: bool | None = None
    is_archived: bool | None = None
    search: str | None = None
    page: int = 1
    page_size: int = 20


# ---------------------------------------------------------------------------
# Notification types
# ---------------------------------------------------------------------------

@strawberry.type
class NotificationType:
    id: str
    type: str
    title: str
    body: str | None
    link: str | None
    is_read: bool
    created_at: str


@strawberry.type
class NotificationListType:
    items: list[NotificationType]
    unread_count: int
