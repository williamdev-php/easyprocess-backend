from __future__ import annotations

from datetime import datetime

import strawberry


@strawberry.type
class UserType:
    id: str
    email: str
    full_name: str
    company_name: str | None = None
    org_number: str | None = None
    phone: str | None = None
    avatar_url: str | None = None
    locale: str
    role: str
    is_superuser: bool
    is_active: bool
    is_verified: bool
    two_factor_enabled: bool
    last_login_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


@strawberry.type
class SessionType:
    id: str
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime
    expires_at: datetime
    is_current: bool = False


@strawberry.type
class AuditLogType:
    id: str
    event_type: str
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime


@strawberry.input
class UpdateProfileInput:
    full_name: str | None = None
    company_name: str | None = None
    org_number: str | None = None
    phone: str | None = None
    avatar_url: str | None = None
    locale: str | None = None


@strawberry.input
class ChangePasswordInput:
    current_password: str
    new_password: str
