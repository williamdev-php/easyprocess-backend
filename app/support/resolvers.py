from __future__ import annotations

import logging
from datetime import datetime, timezone

import strawberry
from sqlalchemy import select, func, or_
from strawberry.types import Info

from app.auth.resolvers import _get_user_from_info, _require_user
from app.database import get_db_session
from app.support.graphql_types import (
    CreateSupportTicketInput,
    NotificationListType,
    NotificationType as NotificationGQLType,
    SupportTicketFilterInput,
    SupportTicketListType,
    SupportTicketType,
    UpdateSupportTicketInput,
)
from app.support.models import SupportTicket, TicketPriority, TicketStatus
from app.support.notifications import Notification, NotificationType

logger = logging.getLogger(__name__)


def _ticket_to_gql(ticket: SupportTicket) -> SupportTicketType:
    return SupportTicketType(
        id=ticket.id,
        user_id=ticket.user_id,
        user_email=ticket.user.email if ticket.user else None,
        user_name=ticket.user.full_name if ticket.user else None,
        subject=ticket.subject,
        message=ticket.message,
        status=ticket.status.value,
        priority=ticket.priority.value,
        is_read=ticket.is_read,
        is_archived=ticket.is_archived,
        admin_reply=ticket.admin_reply,
        replied_at=ticket.replied_at.isoformat() if ticket.replied_at else None,
        created_at=ticket.created_at.isoformat(),
        updated_at=ticket.updated_at.isoformat(),
    )


def _notif_to_gql(n: Notification) -> NotificationGQLType:
    return NotificationGQLType(
        id=n.id,
        type=n.type.value,
        title=n.title,
        body=n.body,
        link=n.link,
        is_read=n.is_read,
        created_at=n.created_at.isoformat(),
    )


async def _send_ticket_email_bg(
    email_type: str,
    user_email: str,
    user_name: str,
    ticket_subject: str,
    admin_reply: str | None = None,
    new_status: str | None = None,
    locale: str = "sv",
) -> None:
    """Send ticket-related email (fire-and-forget, errors are logged)."""
    try:
        from app.config import settings
        from app.email.service import send_transactional_email
        from app.email.templates import (
            build_ticket_created_email,
            build_ticket_replied_email,
            build_ticket_status_email,
        )

        dashboard_url = f"{settings.FRONTEND_URL}/dashboard/contact"

        if email_type == "created":
            subject, html, text = build_ticket_created_email(
                user_name, ticket_subject, dashboard_url, locale=locale
            )
        elif email_type == "replied" and admin_reply:
            subject, html, text = build_ticket_replied_email(
                user_name, ticket_subject, admin_reply, dashboard_url, locale=locale
            )
        elif email_type == "status" and new_status:
            subject, html, text = build_ticket_status_email(
                user_name, ticket_subject, new_status, dashboard_url, locale=locale
            )
        else:
            return

        await send_transactional_email(user_email, subject, html, text)
        logger.info("Sent %s email for ticket '%s' to %s", email_type, ticket_subject, user_email)
    except Exception:
        logger.exception("Failed to send %s email to %s", email_type, user_email)


async def _create_notification(
    db: object,
    user_id: str,
    notif_type: NotificationType,
    title: str,
    body: str | None = None,
    link: str | None = None,
) -> Notification:
    """Create an in-app notification for a user."""
    notif = Notification(
        user_id=user_id,
        type=notif_type,
        title=title,
        body=body,
        link=link or "/dashboard/contact",
    )
    db.add(notif)  # type: ignore
    return notif


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

@strawberry.type
class SupportQuery:

    @strawberry.field
    async def my_support_tickets(self, info: Info) -> list[SupportTicketType]:
        """Get current user's own support tickets."""
        user = _require_user(await _get_user_from_info(info))
        async with get_db_session() as db:
            result = await db.execute(
                select(SupportTicket)
                .where(SupportTicket.user_id == user.id)
                .order_by(SupportTicket.created_at.desc())
                .limit(50)
            )
            return [_ticket_to_gql(t) for t in result.scalars().all()]

    @strawberry.field
    async def my_notifications(self, info: Info) -> NotificationListType:
        """Get current user's notifications (most recent 30)."""
        user = _require_user(await _get_user_from_info(info))
        async with get_db_session() as db:
            result = await db.execute(
                select(Notification)
                .where(Notification.user_id == user.id)
                .order_by(Notification.created_at.desc())
                .limit(30)
            )
            items = [_notif_to_gql(n) for n in result.scalars().all()]

            unread = (await db.execute(
                select(func.count()).select_from(Notification)
                .where(Notification.user_id == user.id, Notification.is_read == False)
            )).scalar() or 0

            return NotificationListType(items=items, unread_count=unread)

    @strawberry.field
    async def support_ticket(self, info: Info, id: str) -> SupportTicketType | None:
        """Get a single support ticket (superadmin only)."""
        user = _require_user(await _get_user_from_info(info))
        if not user.is_superuser:
            raise PermissionError("Superuser access required")

        async with get_db_session() as db:
            result = await db.execute(
                select(SupportTicket).where(SupportTicket.id == id)
            )
            ticket = result.scalar_one_or_none()
            if not ticket:
                return None

            if not ticket.is_read:
                ticket.is_read = True
                await db.flush()

            return _ticket_to_gql(ticket)

    @strawberry.field
    async def support_tickets(
        self, info: Info, filter: SupportTicketFilterInput | None = None
    ) -> SupportTicketListType:
        """List all support tickets (superadmin only)."""
        user = _require_user(await _get_user_from_info(info))
        if not user.is_superuser:
            raise PermissionError("Superuser access required")

        async with get_db_session() as db:
            f = filter or SupportTicketFilterInput()
            page_size = min(f.page_size, 100)

            query = select(SupportTicket)
            count_query = select(func.count()).select_from(SupportTicket)

            if f.status:
                query = query.where(SupportTicket.status == f.status)
                count_query = count_query.where(SupportTicket.status == f.status)
            if f.is_read is not None:
                query = query.where(SupportTicket.is_read == f.is_read)
                count_query = count_query.where(SupportTicket.is_read == f.is_read)
            if f.is_archived is not None:
                query = query.where(SupportTicket.is_archived == f.is_archived)
                count_query = count_query.where(SupportTicket.is_archived == f.is_archived)
            if f.search:
                search = f"%{f.search}%"
                query = query.where(
                    or_(
                        SupportTicket.subject.ilike(search),
                        SupportTicket.message.ilike(search),
                    )
                )
                count_query = count_query.where(
                    or_(
                        SupportTicket.subject.ilike(search),
                        SupportTicket.message.ilike(search),
                    )
                )

            total = (await db.execute(count_query)).scalar() or 0

            query = query.order_by(SupportTicket.created_at.desc())
            query = query.offset((f.page - 1) * page_size).limit(page_size)

            result = await db.execute(query)
            tickets = result.scalars().all()

            return SupportTicketListType(
                items=[_ticket_to_gql(t) for t in tickets],
                total=total,
                page=f.page,
                page_size=page_size,
            )


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------

@strawberry.type
class SupportMutation:

    @strawberry.mutation
    async def create_support_ticket(
        self, info: Info, input: CreateSupportTicketInput
    ) -> SupportTicketType:
        """Create a support ticket (authenticated users)."""
        user = _require_user(await _get_user_from_info(info))

        subject = input.subject.strip()
        message = input.message.strip()
        if not subject or len(subject) > 255:
            raise ValueError("Subject is required and must be under 255 characters")
        if not message or len(message) > 5000:
            raise ValueError("Message is required and must be under 5000 characters")

        async with get_db_session() as db:
            ticket = SupportTicket(
                user_id=user.id,
                subject=subject,
                message=message,
            )
            db.add(ticket)

            # Create notification for the user (confirmation)
            await _create_notification(
                db, user.id,
                NotificationType.TICKET_CREATED,
                title="Ditt ärende har tagits emot",
                body=f"Vi har tagit emot ditt ärende \"{subject}\". Vi återkommer så snart som möjligt.",
                link="/dashboard/contact",
            )

            await db.flush()
            await db.refresh(ticket)

        # Send confirmation email (fire-and-forget)
        await _send_ticket_email_bg(
            "created", user.email, user.full_name or "användare", subject,
            locale=user.locale,
        )

        return _ticket_to_gql(ticket)

    @strawberry.mutation
    async def update_support_ticket(
        self, info: Info, input: UpdateSupportTicketInput
    ) -> SupportTicketType:
        """Update a support ticket (superadmin only)."""
        caller = _require_user(await _get_user_from_info(info))
        if not caller.is_superuser:
            raise PermissionError("Superuser access required")

        async with get_db_session() as db:
            result = await db.execute(
                select(SupportTicket).where(SupportTicket.id == input.ticket_id)
            )
            ticket = result.scalar_one_or_none()
            if not ticket:
                raise ValueError("Ticket not found")

            old_status = ticket.status.value
            reply_changed = False
            status_changed = False

            if input.status is not None:
                new_status = TicketStatus(input.status)
                if new_status != ticket.status:
                    ticket.status = new_status
                    status_changed = True
            if input.priority is not None:
                ticket.priority = TicketPriority(input.priority)
            if input.admin_reply is not None and input.admin_reply != ticket.admin_reply:
                ticket.admin_reply = input.admin_reply
                ticket.replied_at = datetime.now(timezone.utc)
                reply_changed = True

            ticket.updated_at = datetime.now(timezone.utc)

            # Create notifications and send emails to the ticket owner
            ticket_user_id = ticket.user_id
            ticket_user_email = ticket.user.email if ticket.user else None
            ticket_user_name = ticket.user.full_name if ticket.user else "användare"
            ticket_user_locale = ticket.user.locale if ticket.user else "sv"

            if reply_changed and ticket_user_id:
                await _create_notification(
                    db, ticket_user_id,
                    NotificationType.TICKET_REPLIED,
                    title="Nytt svar på ditt ärende",
                    body=f"Vi har svarat på ditt ärende \"{ticket.subject}\".",
                    link="/dashboard/contact",
                )

            if status_changed and ticket_user_id and input.status != old_status:
                status_labels = {
                    "IN_PROGRESS": "påbörjats",
                    "RESOLVED": "lösts",
                    "CLOSED": "stängts",
                }
                label = status_labels.get(input.status, input.status)
                await _create_notification(
                    db, ticket_user_id,
                    NotificationType.TICKET_STATUS_CHANGED,
                    title=f"Ditt ärende har {label}",
                    body=f"Ärendet \"{ticket.subject}\" har uppdaterats.",
                    link="/dashboard/contact",
                )

            await db.flush()
            await db.refresh(ticket)

        # Send emails after commit (fire-and-forget)
        if ticket_user_email:
            if reply_changed and input.admin_reply:
                await _send_ticket_email_bg(
                    "replied", ticket_user_email, ticket_user_name,
                    ticket.subject, admin_reply=input.admin_reply,
                    locale=ticket_user_locale,
                )
            elif status_changed and input.status in ("IN_PROGRESS", "RESOLVED", "CLOSED"):
                await _send_ticket_email_bg(
                    "status", ticket_user_email, ticket_user_name,
                    ticket.subject, new_status=input.status,
                    locale=ticket_user_locale,
                )

        return _ticket_to_gql(ticket)

    @strawberry.mutation
    async def mark_notification_read(self, info: Info, notification_id: str) -> bool:
        """Mark a notification as read."""
        user = _require_user(await _get_user_from_info(info))
        async with get_db_session() as db:
            result = await db.execute(
                select(Notification).where(
                    Notification.id == notification_id,
                    Notification.user_id == user.id,
                )
            )
            notif = result.scalar_one_or_none()
            if notif:
                notif.is_read = True
        return True

    @strawberry.mutation
    async def mark_all_notifications_read(self, info: Info) -> bool:
        """Mark all notifications as read for the current user."""
        user = _require_user(await _get_user_from_info(info))
        async with get_db_session() as db:
            from sqlalchemy import update
            await db.execute(
                update(Notification)
                .where(Notification.user_id == user.id, Notification.is_read == False)
                .values(is_read=True)
            )
        return True

    @strawberry.mutation
    async def mark_ticket_read(
        self, info: Info, ticket_id: str, is_read: bool
    ) -> SupportTicketType:
        """Mark support ticket as read/unread (superadmin only)."""
        user = _require_user(await _get_user_from_info(info))
        if not user.is_superuser:
            raise PermissionError("Superuser access required")

        async with get_db_session() as db:
            result = await db.execute(
                select(SupportTicket).where(SupportTicket.id == ticket_id)
            )
            ticket = result.scalar_one_or_none()
            if not ticket:
                raise ValueError("Ticket not found")

            ticket.is_read = is_read
            await db.flush()
            await db.refresh(ticket)
            return _ticket_to_gql(ticket)

    @strawberry.mutation
    async def archive_ticket(
        self, info: Info, ticket_id: str, is_archived: bool
    ) -> SupportTicketType:
        """Archive/unarchive support ticket (superadmin only)."""
        user = _require_user(await _get_user_from_info(info))
        if not user.is_superuser:
            raise PermissionError("Superuser access required")

        async with get_db_session() as db:
            result = await db.execute(
                select(SupportTicket).where(SupportTicket.id == ticket_id)
            )
            ticket = result.scalar_one_or_none()
            if not ticket:
                raise ValueError("Ticket not found")

            ticket.is_archived = is_archived
            await db.flush()
            await db.refresh(ticket)
            return _ticket_to_gql(ticket)
