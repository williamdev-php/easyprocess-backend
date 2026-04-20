from __future__ import annotations

from datetime import datetime, timezone

import strawberry
from sqlalchemy import select, func, or_
from strawberry.types import Info

from app.auth.resolvers import _get_user_from_info, _require_user
from app.database import get_db_session
from app.support.graphql_types import (
    CreateSupportTicketInput,
    SupportTicketFilterInput,
    SupportTicketListType,
    SupportTicketType,
    UpdateSupportTicketInput,
)
from app.support.models import SupportTicket, TicketPriority, TicketStatus


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

            # Auto-mark as read
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
            await db.flush()
            await db.refresh(ticket)
            return _ticket_to_gql(ticket)

    @strawberry.mutation
    async def update_support_ticket(
        self, info: Info, input: UpdateSupportTicketInput
    ) -> SupportTicketType:
        """Update a support ticket (superadmin only)."""
        user = _require_user(await _get_user_from_info(info))
        if not user.is_superuser:
            raise PermissionError("Superuser access required")

        async with get_db_session() as db:
            result = await db.execute(
                select(SupportTicket).where(SupportTicket.id == input.ticket_id)
            )
            ticket = result.scalar_one_or_none()
            if not ticket:
                raise ValueError("Ticket not found")

            if input.status is not None:
                ticket.status = TicketStatus(input.status)
            if input.priority is not None:
                ticket.priority = TicketPriority(input.priority)
            if input.admin_reply is not None:
                ticket.admin_reply = input.admin_reply
                ticket.replied_at = datetime.now(timezone.utc)

            ticket.updated_at = datetime.now(timezone.utc)
            await db.flush()
            await db.refresh(ticket)
            return _ticket_to_gql(ticket)

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
