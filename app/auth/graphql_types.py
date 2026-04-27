from __future__ import annotations

from datetime import datetime
from typing import Annotated, Union

import strawberry

from app.graphql.pagination import PaginatedListType, PaginationInput


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

    _MAX_NAME = 200
    _MAX_COMPANY = 200
    _MAX_ORG = 50
    _MAX_PHONE = 30
    _MAX_URL = 2048
    _MAX_LOCALE = 10
    _MAX_COUNTRY = 3

    def __post_init__(self) -> None:
        if self.full_name and len(self.full_name) > self._MAX_NAME:
            raise ValueError(f"full_name exceeds max length of {self._MAX_NAME}")
        if self.company_name and len(self.company_name) > self._MAX_COMPANY:
            raise ValueError(f"company_name exceeds max length of {self._MAX_COMPANY}")
        if self.org_number and len(self.org_number) > self._MAX_ORG:
            raise ValueError(f"org_number exceeds max length of {self._MAX_ORG}")
        if self.phone and len(self.phone) > self._MAX_PHONE:
            raise ValueError(f"phone exceeds max length of {self._MAX_PHONE}")
        if self.avatar_url and len(self.avatar_url) > self._MAX_URL:
            raise ValueError(f"avatar_url exceeds max length of {self._MAX_URL}")
        if self.locale and len(self.locale) > self._MAX_LOCALE:
            raise ValueError(f"locale exceeds max length of {self._MAX_LOCALE}")
        if self.country and len(self.country) > self._MAX_COUNTRY:
            raise ValueError(f"country exceeds max length of {self._MAX_COUNTRY}")


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
class AdminUserListType(PaginatedListType):
    items: list[AdminUserType]


@strawberry.type
class AdminUserStatsType:
    total_users: int = 0
    active_users: int = 0
    verified_users: int = 0
    users_with_subscription: int = 0
    new_users_30d: int = 0


@strawberry.input
class AdminUserFilterInput(PaginationInput):
    search: str | None = None
    is_active: bool | None = None
    is_verified: bool | None = None
    has_subscription: bool | None = None


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

    def __post_init__(self) -> None:
        if len(self.current_password) > 256:
            raise ValueError("current_password exceeds max length of 256")
        if len(self.new_password) > 256:
            raise ValueError("new_password exceeds max length of 256")


# ---------------------------------------------------------------------------
# Result union types (Success | Error pattern)
# ---------------------------------------------------------------------------

@strawberry.type
class MutationSuccess:
    """Indicates a successful mutation."""
    success: bool = True
    message: str = "OK"


@strawberry.type
class MutationError:
    """Indicates a failed mutation with an error code and message."""
    success: bool = False
    error_code: str = "UNKNOWN_ERROR"
    message: str = "An error occurred"


@strawberry.type
class UpdateProfileSuccess:
    """Successful profile update."""
    success: bool = True
    user: UserType | None = None


UpdateProfileResult = Annotated[
    Union[UpdateProfileSuccess, MutationError],
    strawberry.union("UpdateProfileResult"),
]

@strawberry.type
class ChangePasswordSuccess:
    """Successful password change."""
    success: bool = True


ChangePasswordResult = Annotated[
    Union[ChangePasswordSuccess, MutationError],
    strawberry.union("ChangePasswordResult"),
]

@strawberry.type
class RevokeSessionSuccess:
    """Successful session revocation."""
    success: bool = True


RevokeSessionResult = Annotated[
    Union[RevokeSessionSuccess, MutationError],
    strawberry.union("RevokeSessionResult"),
]

@strawberry.type
class RevokeAllSessionsSuccess:
    """Successful revocation of all sessions."""
    success: bool = True
    revoked_count: int = 0


RevokeAllSessionsResult = Annotated[
    Union[RevokeAllSessionsSuccess, MutationError],
    strawberry.union("RevokeAllSessionsResult"),
]


@strawberry.type
class AdminUpdateUserSuccess:
    """Successful admin user update."""
    success: bool = True
    user: "AdminUserDetailType | None" = None


AdminUpdateUserResult = Annotated[
    Union[AdminUpdateUserSuccess, MutationError],
    strawberry.union("AdminUpdateUserResult"),
]
