from __future__ import annotations

from datetime import datetime, timezone

import strawberry
from sqlalchemy import select, and_
from strawberry.types import Info

from app.auth.graphql_types import (
    AuditLogType,
    ChangePasswordInput,
    SessionType,
    UpdateProfileInput,
    UserType,
)
from app.auth.models import AuditEventType, AuditLog, Session, User
from app.auth.service import (
    change_password,
    decode_access_token,
    get_client_ip,
    get_user_by_id,
    log_audit_event,
    revoke_all_user_sessions,
    revoke_session,
    verify_password,
)
from app.database import async_session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user_to_gql(user: User) -> UserType:
    return UserType(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        company_name=user.company_name,
        org_number=user.org_number,
        phone=user.phone,
        avatar_url=user.avatar_url,
        locale=user.locale,
        role=user.role.value,
        is_superuser=user.is_superuser,
        is_active=user.is_active,
        is_verified=user.is_verified,
        two_factor_enabled=user.two_factor_enabled,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


async def _get_user_from_info(info: Info) -> User | None:
    request = info.context["request"]
    auth_header: str | None = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    token = auth_header[7:]
    user_id = decode_access_token(token)
    if not user_id:
        return None
    async with async_session() as db:
        user = await get_user_by_id(db, user_id)
        if user and not user.is_active:
            return None
        return user


def _require_user(user: User | None) -> User:
    if user is None:
        raise PermissionError("Authentication required")
    return user


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

@strawberry.type
class Query:

    @strawberry.field
    async def me(self, info: Info) -> UserType | None:
        user = await _get_user_from_info(info)
        return _user_to_gql(user) if user else None

    @strawberry.field
    async def my_sessions(self, info: Info) -> list[SessionType]:
        user = _require_user(await _get_user_from_info(info))
        request = info.context["request"]

        async with async_session() as db:
            result = await db.execute(
                select(Session)
                .where(
                    and_(
                        Session.user_id == user.id,
                        Session.revoked_at.is_(None),
                        Session.expires_at > datetime.now(timezone.utc),
                    )
                )
                .order_by(Session.created_at.desc())
            )
            sessions = result.scalars().all()

            # Detect current session from cookie
            from app.auth.service import _hash_token
            current_token = request.cookies.get("refresh_token")
            current_hash = _hash_token(current_token) if current_token else None

            return [
                SessionType(
                    id=s.id,
                    ip_address=s.ip_address,
                    user_agent=s.user_agent,
                    created_at=s.created_at,
                    expires_at=s.expires_at,
                    is_current=s.token_hash == current_hash if current_hash else False,
                )
                for s in sessions
            ]

    @strawberry.field
    async def my_audit_log(self, info: Info, limit: int = 50, offset: int = 0) -> list[AuditLogType]:
        user = _require_user(await _get_user_from_info(info))
        async with async_session() as db:
            result = await db.execute(
                select(AuditLog)
                .where(AuditLog.user_id == user.id)
                .order_by(AuditLog.created_at.desc())
                .limit(min(limit, 100))
                .offset(offset)
            )
            logs = result.scalars().all()
            return [
                AuditLogType(
                    id=log.id,
                    event_type=log.event_type.value,
                    ip_address=log.ip_address,
                    user_agent=log.user_agent,
                    created_at=log.created_at,
                )
                for log in logs
            ]


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------

@strawberry.type
class Mutation:

    @strawberry.mutation
    async def update_profile(self, info: Info, input: UpdateProfileInput) -> UserType:
        user = _require_user(await _get_user_from_info(info))
        async with async_session() as db:
            db_user = await get_user_by_id(db, user.id)
            if not db_user:
                raise ValueError("User not found")

            updates = {k: v for k, v in {
                "full_name": input.full_name,
                "company_name": input.company_name,
                "org_number": input.org_number,
                "phone": input.phone,
                "avatar_url": input.avatar_url,
                "locale": input.locale,
            }.items() if v is not None}

            for field, value in updates.items():
                setattr(db_user, field, value)

            db_user.updated_at = datetime.now(timezone.utc)
            await db.commit()
            await db.refresh(db_user)
            return _user_to_gql(db_user)

    @strawberry.mutation
    async def change_password(self, info: Info, input: ChangePasswordInput) -> bool:
        user = _require_user(await _get_user_from_info(info))
        async with async_session() as db:
            db_user = await get_user_by_id(db, user.id)
            if not db_user or not db_user.password_hash:
                raise ValueError("Cannot change password")

            if not verify_password(input.current_password, db_user.password_hash):
                raise ValueError("Current password is incorrect")

            await change_password(db, db_user, input.new_password)

            request = info.context["request"]
            ip = get_client_ip(request)
            ua = request.headers.get("user-agent")
            await log_audit_event(db, AuditEventType.PASSWORD_CHANGE, db_user.id, ip, ua)

            await db.commit()
            return True

    @strawberry.mutation
    async def revoke_session(self, info: Info, session_id: str) -> bool:
        user = _require_user(await _get_user_from_info(info))
        async with async_session() as db:
            result = await db.execute(
                select(Session).where(
                    and_(Session.id == session_id, Session.user_id == user.id)
                )
            )
            session = result.scalar_one_or_none()
            if not session:
                raise ValueError("Session not found")

            await revoke_session(db, session.id)

            request = info.context["request"]
            ip = get_client_ip(request)
            ua = request.headers.get("user-agent")
            await log_audit_event(db, AuditEventType.SESSION_REVOKED, user.id, ip, ua)

            await db.commit()
            return True

    @strawberry.mutation
    async def revoke_all_sessions(self, info: Info) -> int:
        user = _require_user(await _get_user_from_info(info))
        async with async_session() as db:
            count = await revoke_all_user_sessions(db, user.id)

            request = info.context["request"]
            ip = get_client_ip(request)
            ua = request.headers.get("user-agent")
            await log_audit_event(
                db, AuditEventType.SESSION_REVOKED, user.id, ip, ua,
                {"sessions_revoked": count},
            )

            await db.commit()
            return count
