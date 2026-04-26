"""AutoBlogger schemas — auth re-exports + AutoBloggerUserResponse."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

# ---- Auth re-exports (Pydantic-only schemas shared across products) --------
from app.auth.schemas import (
    ChangePasswordRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    SessionResponse,
    TokenResponse,
    UpdateProfileRequest,
    UserLogin,
    UserRegister,
)


class AutoBloggerUserResponse(BaseModel):
    """User response tailored to AutoBloggerUser fields (no Qvicko billing/stripe)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    full_name: str
    company_name: str | None = None
    org_number: str | None = None
    phone: str | None = None
    avatar_url: str | None = None
    locale: str = "sv"
    is_active: bool = True
    is_verified: bool = False
    last_login_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


__all__ = [
    "AutoBloggerUserResponse",
    "ChangePasswordRequest",
    "PasswordResetConfirm",
    "PasswordResetRequest",
    "SessionResponse",
    "TokenResponse",
    "UpdateProfileRequest",
    "UserLogin",
    "UserRegister",
]
