from __future__ import annotations

from datetime import datetime, timezone

import strawberry
from sqlalchemy import select, and_, func, or_
from strawberry.types import Info

from app.auth.graphql_types import (
    AdminUpdateUserInput,
    AdminUpdateUserResult,
    AdminUpdateUserSuccess,
    AdminUserDetailType,
    AdminUserFilterInput,
    AdminUserListType,
    AdminUserSiteType,
    AdminUserStatsType,
    AdminUserType,
    AuditLogType,
    ChangePasswordInput,
    ChangePasswordResult,
    ChangePasswordSuccess,
    MutationError,
    RevokeAllSessionsResult,
    RevokeAllSessionsSuccess,
    RevokeSessionResult,
    RevokeSessionSuccess,
    SessionType,
    UpdateProfileInput,
    UpdateProfileResult,
    UpdateProfileSuccess,
    UserType,
)
from app.auth.models import AuditEventType, AuditLog, Session, User
from app.auth.service import (
    change_password,
    decode_access_token,
    get_client_ip,
    get_user_by_id,
    get_user_by_id_cached,
    invalidate_user_cache,
    log_audit_event,
    revoke_all_user_sessions,
    revoke_session,
    verify_password,
)
from app.database import get_db_session


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
        country=user.billing_country,
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
    # Try cache first (skips DB on hit)
    user = await get_user_by_id_cached(user_id)
    if user is None:
        async with get_db_session() as db:
            user = await get_user_by_id(db, user_id)
    if user and (not user.is_active or user.deleted_at is not None):
        return None
    return user


def _require_user(user: User | None) -> User:
    if user is None:
        raise PermissionError("Authentication required")
    return user


def _require_superuser(user: User) -> User:
    """Verify that the authenticated user has superuser privileges."""
    if not user.is_superuser:
        raise PermissionError("Superuser access required")
    return user


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

@strawberry.type
class Query:

    # ------------------------------------------------------------------
    # User queries (authenticated user)
    # ------------------------------------------------------------------

    @strawberry.field(description="Get the currently authenticated user's profile.")
    async def me(self, info: Info) -> UserType | None:
        user = await _get_user_from_info(info)
        return _user_to_gql(user) if user else None

    @strawberry.field(description="List the current user's active sessions.")
    async def my_sessions(self, info: Info) -> list[SessionType]:
        user = _require_user(await _get_user_from_info(info))
        request = info.context["request"]

        async with get_db_session() as db:
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
                    is_trusted=s.is_trusted,
                    created_at=s.created_at,
                    expires_at=s.expires_at,
                    master_expires_at=s.master_expires_at,
                    is_current=s.token_hash == current_hash if current_hash else False,
                )
                for s in sessions
            ]

    @strawberry.field
    async def my_audit_log(self, info: Info, page: int = 1, page_size: int = 50) -> list[AuditLogType]:
        """Fetch the current user's audit log entries with pagination."""
        user = _require_user(await _get_user_from_info(info))
        clamped_page_size = min(max(page_size, 1), 100)
        offset = (max(page, 1) - 1) * clamped_page_size
        async with get_db_session() as db:
            result = await db.execute(
                select(AuditLog)
                .where(AuditLog.user_id == user.id)
                .order_by(AuditLog.created_at.desc())
                .limit(clamped_page_size)
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

    # ------------------------------------------------------------------
    # Admin-only queries
    # ------------------------------------------------------------------

    @strawberry.field(description="[Admin] List all users. Requires superuser privileges.")
    async def all_users(self, info: Info, filter: AdminUserFilterInput | None = None) -> AdminUserListType:
        """List all users (superadmin only)."""
        user = _require_superuser(_require_user(await _get_user_from_info(info)))

        f = filter or AdminUserFilterInput()
        page_size = f.validated_page_size(max_size=50)
        offset = f.offset(max_size=50)

        async with get_db_session() as db:
            query = select(User)
            count_query = select(func.count()).select_from(User)

            if f.search:
                pattern = f"%{f.search}%"
                search_filter = or_(
                    User.email.ilike(pattern),
                    User.full_name.ilike(pattern),
                    User.company_name.ilike(pattern),
                )
                query = query.where(search_filter)
                count_query = count_query.where(search_filter)

            if f.is_active is not None:
                query = query.where(User.is_active == f.is_active)
                count_query = count_query.where(User.is_active == f.is_active)

            if f.is_verified is not None:
                query = query.where(User.is_verified == f.is_verified)
                count_query = count_query.where(User.is_verified == f.is_verified)

            total_result = await db.execute(count_query)
            total = total_result.scalar() or 0

            result = await db.execute(
                query.order_by(User.created_at.desc())
                .limit(page_size)
                .offset(offset)
            )
            users = result.scalars().all()

            # Get site counts per user
            from app.sites.models import GeneratedSite, Lead
            site_counts_result = await db.execute(
                select(Lead.created_by, func.count(GeneratedSite.id))
                .join(GeneratedSite, GeneratedSite.lead_id == Lead.id)
                .where(GeneratedSite.deleted_at.is_(None))
                .group_by(Lead.created_by)
            )
            site_counts = {str(uid): cnt for uid, cnt in site_counts_result}

            # Get subscription status per user (batch query instead of N+1)
            from app.billing.models import Subscription, SubscriptionStatus
            user_ids = [u.id for u in users]
            if user_ids:
                sub_result = await db.execute(
                    select(Subscription.user_id)
                    .where(
                        Subscription.user_id.in_(user_ids),
                        Subscription.status.in_([
                            SubscriptionStatus.ACTIVE,
                            SubscriptionStatus.TRIALING,
                            SubscriptionStatus.PAST_DUE,
                        ]),
                    )
                )
                active_sub_user_ids = {str(uid) for uid, in sub_result}
            else:
                active_sub_user_ids = set()
            sub_statuses = {str(u.id): str(u.id) in active_sub_user_ids for u in users}

            items = [
                AdminUserType(
                    id=u.id,
                    email=u.email,
                    full_name=u.full_name,
                    company_name=u.company_name,
                    phone=u.phone,
                    country=u.billing_country,
                    avatar_url=u.avatar_url,
                    role=u.role.value,
                    is_superuser=u.is_superuser,
                    is_active=u.is_active,
                    is_verified=u.is_verified,
                    created_at=u.created_at,
                    last_login_at=u.last_login_at,
                    sites_count=site_counts.get(str(u.id), 0),
                    has_subscription=sub_statuses.get(str(u.id), False),
                )
                for u in users
            ]

            return AdminUserListType(
                items=items,
                total=total,
                page=f.page,
                page_size=page_size,
            )

    @strawberry.field(description="[Admin] Aggregate user statistics. Requires superuser privileges.")
    async def admin_user_stats(self, info: Info) -> AdminUserStatsType:
        """Aggregate user stats (superadmin only)."""
        user = _require_superuser(_require_user(await _get_user_from_info(info)))

        async with get_db_session() as db:
            total = (await db.execute(select(func.count()).select_from(User))).scalar() or 0
            active = (await db.execute(
                select(func.count()).select_from(User).where(User.is_active == True)
            )).scalar() or 0
            verified = (await db.execute(
                select(func.count()).select_from(User).where(User.is_verified == True)
            )).scalar() or 0

            from datetime import timedelta
            thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
            new_30d = (await db.execute(
                select(func.count()).select_from(User).where(User.created_at >= thirty_days_ago)
            )).scalar() or 0

            return AdminUserStatsType(
                total_users=total,
                active_users=active,
                verified_users=verified,
                users_with_subscription=0,  # Computed on demand if needed
                new_users_30d=new_30d,
            )

    @strawberry.field(description="[Admin] Get full user details by ID. Requires superuser privileges.")
    async def admin_user(self, info: Info, id: str) -> AdminUserDetailType:
        """[Admin] Get full user details. Requires superuser privileges."""
        caller = _require_superuser(_require_user(await _get_user_from_info(info)))

        async with get_db_session() as db:
            target = await get_user_by_id(db, id)
            if not target:
                raise ValueError("USER_NOT_FOUND: User not found")

            # Sessions (active only)
            result = await db.execute(
                select(Session)
                .where(
                    and_(
                        Session.user_id == id,
                        Session.revoked_at.is_(None),
                        Session.expires_at > datetime.now(timezone.utc),
                    )
                )
                .order_by(Session.created_at.desc())
                .limit(20)
            )
            sessions = [
                SessionType(
                    id=s.id,
                    ip_address=s.ip_address,
                    user_agent=s.user_agent,
                    is_trusted=s.is_trusted,
                    created_at=s.created_at,
                    expires_at=s.expires_at,
                    master_expires_at=s.master_expires_at,
                    is_current=False,
                )
                for s in result.scalars().all()
            ]

            # Audit log (last 50)
            audit_result = await db.execute(
                select(AuditLog)
                .where(AuditLog.user_id == id)
                .order_by(AuditLog.created_at.desc())
                .limit(50)
            )
            audit_log = [
                AuditLogType(
                    id=log.id,
                    event_type=log.event_type.value,
                    ip_address=log.ip_address,
                    user_agent=log.user_agent,
                    created_at=log.created_at,
                )
                for log in audit_result.scalars().all()
            ]

            # Recent sites
            from app.sites.models import GeneratedSite, Lead
            sites_result = await db.execute(
                select(GeneratedSite, Lead)
                .join(Lead, GeneratedSite.lead_id == Lead.id)
                .where(
                    Lead.created_by == id,
                    GeneratedSite.deleted_at.is_(None),
                )
                .order_by(GeneratedSite.created_at.desc())
                .limit(10)
            )
            recent_sites = [
                AdminUserSiteType(
                    id=site.id,
                    business_name=lead.business_name,
                    subdomain=site.subdomain,
                    status=site.status.value,
                    views=site.views,
                    created_at=site.created_at,
                )
                for site, lead in sites_result.all()
            ]

            site_count = len(recent_sites)

            # Subscription status
            from app.billing.service import get_active_subscription
            sub = await get_active_subscription(db, target.id)

            return AdminUserDetailType(
                id=target.id,
                email=target.email,
                full_name=target.full_name,
                company_name=target.company_name,
                org_number=target.org_number,
                phone=target.phone,
                country=target.billing_country,
                avatar_url=target.avatar_url,
                locale=target.locale,
                role=target.role.value,
                is_superuser=target.is_superuser,
                is_active=target.is_active,
                is_verified=target.is_verified,
                two_factor_enabled=target.two_factor_enabled,
                failed_login_attempts=target.failed_login_attempts,
                locked_until=target.locked_until,
                last_login_at=target.last_login_at,
                password_changed_at=target.password_changed_at,
                created_at=target.created_at,
                updated_at=target.updated_at,
                billing_street=target.billing_street,
                billing_city=target.billing_city,
                billing_zip=target.billing_zip,
                billing_country=target.billing_country,
                stripe_customer_id=target.stripe_customer_id,
                sites_count=site_count,
                has_subscription=sub is not None,
                sessions=sessions,
                audit_log=audit_log,
                recent_sites=recent_sites,
            )


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------

@strawberry.type
class Mutation:

    # ------------------------------------------------------------------
    # User mutations (authenticated user)
    # ------------------------------------------------------------------

    @strawberry.mutation
    async def update_profile(self, info: Info, input: UpdateProfileInput) -> UpdateProfileResult:  # type: ignore[return]
        user = _require_user(await _get_user_from_info(info))
        async with get_db_session() as db:
            db_user = await get_user_by_id(db, user.id)
            if not db_user:
                return MutationError(error_code="USER_NOT_FOUND", message="User not found")

            # Validate country code if provided
            if input.country is not None and input.country != "":
                from app.auth.validators import VALID_COUNTRY_CODES
                if input.country.upper() not in VALID_COUNTRY_CODES:
                    return MutationError(
                        error_code="INVALID_COUNTRY",
                        message=f"Invalid country code: {input.country}",
                    )

            updates = {k: v for k, v in {
                "full_name": input.full_name,
                "company_name": input.company_name,
                "org_number": input.org_number,
                "phone": input.phone,
                "avatar_url": input.avatar_url,
                "locale": input.locale,
                "billing_country": input.country.upper() if input.country else input.country,
            }.items() if v is not None}

            for field, value in updates.items():
                setattr(db_user, field, value)

            db_user.updated_at = datetime.now(timezone.utc)
            await db.commit()
            await invalidate_user_cache(db_user.id, db_user.email)
            await db.refresh(db_user)
            return UpdateProfileSuccess(user=_user_to_gql(db_user))

    @strawberry.mutation
    async def change_password(self, info: Info, input: ChangePasswordInput) -> ChangePasswordResult:  # type: ignore[return]
        user = _require_user(await _get_user_from_info(info))
        async with get_db_session() as db:
            db_user = await get_user_by_id(db, user.id)
            if not db_user or not db_user.password_hash:
                return MutationError(error_code="PASSWORD_CHANGE_DENIED", message="Cannot change password")

            if not verify_password(input.current_password, db_user.password_hash):
                return MutationError(error_code="INVALID_PASSWORD", message="Current password is incorrect")

            await change_password(db, db_user, input.new_password)
            await invalidate_user_cache(db_user.id, db_user.email)

            request = info.context["request"]
            ip = get_client_ip(request)
            ua = request.headers.get("user-agent")
            await log_audit_event(db, AuditEventType.PASSWORD_CHANGE, db_user.id, ip, ua)

            await db.commit()
            return ChangePasswordSuccess()

    @strawberry.mutation
    async def revoke_session(self, info: Info, session_id: str) -> RevokeSessionResult:  # type: ignore[return]
        user = _require_user(await _get_user_from_info(info))
        async with get_db_session() as db:
            result = await db.execute(
                select(Session).where(
                    and_(Session.id == session_id, Session.user_id == user.id)
                )
            )
            session = result.scalar_one_or_none()
            if not session:
                return MutationError(error_code="SESSION_NOT_FOUND", message="Session not found")

            await revoke_session(db, session.id)

            request = info.context["request"]
            ip = get_client_ip(request)
            ua = request.headers.get("user-agent")
            await log_audit_event(db, AuditEventType.SESSION_REVOKED, user.id, ip, ua)

            await db.commit()
            return RevokeSessionSuccess()

    @strawberry.mutation
    async def revoke_all_sessions(self, info: Info) -> RevokeAllSessionsResult:  # type: ignore[return]
        user = _require_user(await _get_user_from_info(info))
        async with get_db_session() as db:
            count = await revoke_all_user_sessions(db, user.id)

            request = info.context["request"]
            ip = get_client_ip(request)
            ua = request.headers.get("user-agent")
            await log_audit_event(
                db, AuditEventType.SESSION_REVOKED, user.id, ip, ua,
                {"sessions_revoked": count},
            )

            await db.commit()
            return RevokeAllSessionsSuccess(revoked_count=count)

    # ------------------------------------------------------------------
    # Admin-only mutations
    # ------------------------------------------------------------------

    @strawberry.mutation(description="[Admin] Update a user's profile or status. Requires superuser privileges.")
    async def admin_update_user(self, info: Info, input: AdminUpdateUserInput) -> AdminUpdateUserResult:  # type: ignore[return]
        """Update a user's profile/status (superadmin only).

        Security:
        - Superuser promotion is rate-limited to max 1 per week.
        - Users cannot be hard-deleted via this mutation (soft delete only).
        """
        user = await _get_user_from_info(info)
        if user is None:
            return MutationError(error_code="AUTH_REQUIRED", message="Authentication required")
        if not user.is_superuser:
            return MutationError(error_code="FORBIDDEN", message="Superuser access required")
        caller = user

        async with get_db_session() as db:
            target = await get_user_by_id(db, input.user_id)
            if not target:
                return MutationError(error_code="USER_NOT_FOUND", message="User not found")

            # --- Superuser promotion rate limit: max 1 per week ---
            if input.is_superuser is not None and input.is_superuser and not target.is_superuser:
                from datetime import timedelta
                from app.auth.models import SuperuserPromotion
                one_week_ago = datetime.now(timezone.utc) - timedelta(weeks=1)
                recent = (await db.execute(
                    select(func.count()).select_from(SuperuserPromotion)
                    .where(SuperuserPromotion.created_at >= one_week_ago)
                )).scalar() or 0
                if recent >= 1:
                    return MutationError(
                        error_code="RATE_LIMITED",
                        message="Superuser promotion rate limit: max 1 promotion per week. Try again later.",
                    )

            if input.full_name is not None:
                target.full_name = input.full_name
            if input.email is not None:
                target.email = input.email
            if input.company_name is not None:
                target.company_name = input.company_name
            if input.org_number is not None:
                target.org_number = input.org_number
            if input.phone is not None:
                target.phone = input.phone
            if input.locale is not None:
                target.locale = input.locale
            if input.role is not None:
                from app.auth.models import UserRole
                target.role = UserRole(input.role)
            if input.is_active is not None:
                target.is_active = input.is_active
                # Log deactivation/reactivation
                request = info.context["request"]
                ip = get_client_ip(request)
                ua = request.headers.get("user-agent")
                event = AuditEventType.ACCOUNT_DEACTIVATED if not input.is_active else AuditEventType.ACCOUNT_REACTIVATED
                await log_audit_event(db, event, target.id, ip, ua, {"by": caller.id})
            if input.is_verified is not None:
                target.is_verified = input.is_verified
            if input.is_superuser is not None:
                was_superuser = target.is_superuser
                target.is_superuser = input.is_superuser
                # Log promotion
                if input.is_superuser and not was_superuser:
                    from app.auth.models import SuperuserPromotion
                    promo = SuperuserPromotion(
                        promoted_user_id=target.id,
                        promoted_by_id=caller.id,
                    )
                    db.add(promo)

            target.updated_at = datetime.now(timezone.utc)
            await db.commit()
            await invalidate_user_cache(target.id, target.email)
            await db.refresh(target)

        # Re-fetch via the query to return full detail
        detail = await Query.admin_user(Query(), info, input.user_id)
        return AdminUpdateUserSuccess(user=detail)
