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
    country: str | None = None
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
    is_trusted: bool = False
    created_at: datetime
    expires_at: datetime
    master_expires_at: datetime | None = None
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
    country: str | None = None


@strawberry.type
class AdminUserType:
    """Extended user type for admin views — includes site/subscription counts."""
    id: str
    email: str
    full_name: str
    company_name: str | None = None
    phone: str | None = None
    country: str | None = None
    avatar_url: str | None = None
    role: str
    is_superuser: bool
    is_active: bool
    is_verified: bool
    created_at: datetime
    last_login_at: datetime | None = None
    sites_count: int = 0
    has_subscription: bool = False


@strawberry.type
class AdminUserListType:
    items: list[AdminUserType]
    total: int
    page: int
    page_size: int


@strawberry.type
class AdminUserStatsType:
    total_users: int = 0
    active_users: int = 0
    verified_users: int = 0
    users_with_subscription: int = 0
    new_users_30d: int = 0


@strawberry.input
class AdminUserFilterInput:
    search: str | None = None
    is_active: bool | None = None
    is_verified: bool | None = None
    has_subscription: bool | None = None
    page: int = 1
    page_size: int = 20


@strawberry.type
class AdminUserDetailType:
    """Full user detail for admin user detail page."""
    id: str
    email: str
    full_name: str
    company_name: str | None = None
    org_number: str | None = None
    phone: str | None = None
    country: str | None = None
    avatar_url: str | None = None
    locale: str = "sv"
    role: str = "USER"
    is_superuser: bool = False
    is_active: bool = True
    is_verified: bool = False
    two_factor_enabled: bool = False
    failed_login_attempts: int = 0
    locked_until: datetime | None = None
    last_login_at: datetime | None = None
    password_changed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # Billing
    billing_street: str | None = None
    billing_city: str | None = None
    billing_zip: str | None = None
    billing_country: str | None = None
    stripe_customer_id: str | None = None
    # Related data
    sites_count: int = 0
    has_subscription: bool = False
    sessions: list[SessionType] = strawberry.field(default_factory=list)
    audit_log: list[AuditLogType] = strawberry.field(default_factory=list)
    recent_sites: list["AdminUserSiteType"] = strawberry.field(default_factory=list)


@strawberry.type
class AdminUserSiteType:
    """Minimal site info for admin user detail."""
    id: str
    business_name: str | None = None
    subdomain: str | None = None
    status: str = "DRAFT"
    views: int = 0
    created_at: datetime | None = None


@strawberry.input
class AdminUpdateUserInput:
    user_id: str
    full_name: str | None = None
    email: str | None = None
    company_name: str | None = None
    org_number: str | None = None
    phone: str | None = None
    locale: str | None = None
    role: str | None = None
    is_active: bool | None = None
    is_verified: bool | None = None
    is_superuser: bool | None = None


@strawberry.input
class ChangePasswordInput:
    current_password: str
    new_password: str
