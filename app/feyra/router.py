"""Feyra auth router — uses Feyra's own User model & auth service,
lives under /api/feyra/auth and uses FEYRA_FRONTEND_URL
for email links (password reset, verification).
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.feyra.auth_dependencies import get_current_feyra_user
from app.feyra.models import FeyraAuditEventType, FeyraSession, FeyraUser
from app.feyra.schemas import (
    ChangePasswordRequest,
    FeyraUserResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
    SessionResponse,
    TokenResponse,
    UpdateProfileRequest,
    UserLogin,
    UserRegister,
)
from app.feyra.auth_service import (
    _hash_token,
    change_password,
    create_access_token,
    create_email_verification_token,
    create_password_reset_token,
    create_session,
    create_user,
    exchange_google_code,
    fetch_google_userinfo,
    get_client_ip,
    get_or_create_google_user,
    get_user_by_email,
    get_user_by_id,
    invalidate_user_cache,
    is_account_locked,
    log_audit_event,
    record_failed_login,
    reset_failed_logins,
    revoke_all_user_sessions,
    revoke_session,
    validate_email_verification_token,
    validate_password_reset_token,
    validate_session,
    verify_password,
)
from app.config import settings
from app.database import get_db
from app.feyra.email_service import send_password_reset_email, send_verification_email
from app.rate_limit import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/feyra/auth", tags=["Feyra Auth"])

REFRESH_COOKIE_NAME = "feyra_refresh_token"


def _frontend_url() -> str:
    return settings.FEYRA_FRONTEND_URL


def _cookie_max_age(is_trusted: bool) -> int:
    if is_trusted:
        return settings.MASTER_SESSION_EXPIRE_DAYS * 24 * 60 * 60
    return settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60


def _set_refresh_cookie(response: Response, token: str, is_trusted: bool = False) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        max_age=_cookie_max_age(is_trusted),
        httponly=True,
        samesite="lax",
        secure=settings.ENVIRONMENT == "production",
        path="/api/feyra/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=REFRESH_COOKIE_NAME, path="/api/feyra/auth")


# ---------------------------------------------------------------------------
# Registration & Login
# ---------------------------------------------------------------------------


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
@limiter.limit("10/day")
async def register(
    body: UserRegister,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    existing = await get_user_by_email(db, body.email)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = await create_user(
        db,
        email=body.email,
        password=body.password,
        full_name=body.full_name,
        company_name=body.company_name,
        org_number=body.org_number,
        phone=body.phone,
        locale=body.locale,
    )

    ip = get_client_ip(request)
    ua = request.headers.get("user-agent")

    session, raw_token = await create_session(
        db, user.id, ip_address=ip, user_agent=ua, trust_device=True
    )
    await log_audit_event(
        db, FeyraAuditEventType.REGISTER, user.id, ip, ua,
        {"source": "feyra"},
    )

    # Send verification email (wrapped in savepoint so a failure here
    # does not roll back the user/session that was already flushed)
    try:
        async with db.begin_nested():
            verification_token = await create_email_verification_token(db, user)
        verify_url = f"{_frontend_url()}/verify-email?token={verification_token}"
        await send_verification_email(user.email, verify_url, user.full_name, locale=user.locale)
    except Exception:
        logger.exception("Failed to send verification email to %s (feyra)", user.email)

    access_token = create_access_token(user.id)
    _set_refresh_cookie(response, raw_token, is_trusted=session.is_trusted)
    return TokenResponse(access_token=access_token)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(
    body: UserLogin,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    ip = get_client_ip(request)
    ua = request.headers.get("user-agent")

    user = await get_user_by_email(db, body.email)
    if not user or not user.password_hash:
        await log_audit_event(db, FeyraAuditEventType.LOGIN_FAILED, None, ip, ua, {"email": body.email, "source": "feyra"})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account deactivated")

    if is_account_locked(user):
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="Account temporarily locked. Try again later.")

    if not verify_password(body.password, user.password_hash):
        await record_failed_login(db, user)
        await log_audit_event(db, FeyraAuditEventType.LOGIN_FAILED, user.id, ip, ua, {"source": "feyra"})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    await reset_failed_logins(db, user)
    await invalidate_user_cache(user.id, user.email)

    session, raw_token = await create_session(
        db, user.id, ip_address=ip, user_agent=ua, trust_device=True
    )
    await log_audit_event(db, FeyraAuditEventType.LOGIN, user.id, ip, ua, {"source": "feyra"})

    access_token = create_access_token(user.id)
    _set_refresh_cookie(response, raw_token, is_trusted=session.is_trusted)
    return TokenResponse(access_token=access_token)


# ---------------------------------------------------------------------------
# Google OAuth
# ---------------------------------------------------------------------------


@router.post("/google", response_model=TokenResponse)
@limiter.limit("10/minute")
async def google_auth(
    body: dict,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Authenticate with Google OAuth.

    Web flow: {code, redirect_uri, locale?}
    iOS flow: {access_token, locale?}
    """
    code = body.get("code")
    redirect_uri = body.get("redirect_uri")
    google_access_token = body.get("access_token")
    locale = body.get("locale", "sv")

    if not code and not google_access_token:
        raise HTTPException(status_code=400, detail="Missing code or access_token")

    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=501, detail="Google login is not configured")

    try:
        if google_access_token:
            google_user = await fetch_google_userinfo(google_access_token)
        else:
            if not redirect_uri:
                raise HTTPException(status_code=400, detail="Missing redirect_uri for code flow")
            google_user = await exchange_google_code(code, redirect_uri)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not google_user.get("email"):
        raise HTTPException(status_code=400, detail="Google account has no email")

    user = await get_or_create_google_user(db, google_user, locale=locale)

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account deactivated")

    ip = get_client_ip(request)
    ua = request.headers.get("user-agent")

    await reset_failed_logins(db, user)
    await invalidate_user_cache(user.id, user.email)

    session, raw_token = await create_session(
        db, user.id, ip_address=ip, user_agent=ua, trust_device=True
    )
    await log_audit_event(
        db, FeyraAuditEventType.LOGIN, user.id, ip, ua,
        {"provider": "google", "source": "feyra"},
    )

    access_token = create_access_token(user.id)
    _set_refresh_cookie(response, raw_token, is_trusted=session.is_trusted)
    return TokenResponse(access_token=access_token)


# ---------------------------------------------------------------------------
# Token refresh & Logout
# ---------------------------------------------------------------------------


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    raw_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not raw_token:
        try:
            body = await request.json()
            raw_token = body.get("refresh_token")
        except Exception:
            pass
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token")

    session = await validate_session(db, raw_token)
    if not session:
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")

    user = session.user
    if not user.is_active:
        await revoke_session(db, session.id)
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account deactivated")

    ip = get_client_ip(request)
    ua = request.headers.get("user-agent")

    was_trusted = session.is_trusted
    await revoke_session(db, session.id)
    new_session, new_token = await create_session(
        db, user.id, ip_address=ip, user_agent=ua,
        trust_device=was_trusted,
    )

    if was_trusted and session.master_expires_at and new_session.master_expires_at:
        new_session.master_expires_at = session.master_expires_at
        await db.flush()

    access_token = create_access_token(user.id)
    _set_refresh_cookie(response, new_token, is_trusted=new_session.is_trusted)
    return TokenResponse(access_token=access_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> None:
    raw_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not raw_token:
        try:
            body = await request.json()
            raw_token = body.get("refresh_token")
        except Exception:
            pass
    if raw_token:
        session = await validate_session(db, raw_token)
        if session:
            ip = get_client_ip(request)
            ua = request.headers.get("user-agent")
            await revoke_session(db, session.id)
            await log_audit_event(db, FeyraAuditEventType.LOGOUT, session.user_id, ip, ua, {"source": "feyra"})
    _clear_refresh_cookie(response)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(
    request: Request,
    response: Response,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    count = await revoke_all_user_sessions(db, current_user.id)
    ip = get_client_ip(request)
    ua = request.headers.get("user-agent")
    await log_audit_event(
        db, FeyraAuditEventType.SESSION_REVOKED, current_user.id, ip, ua,
        {"sessions_revoked": count, "source": "feyra"},
    )
    _clear_refresh_cookie(response)


# ---------------------------------------------------------------------------
# Password Reset
# ---------------------------------------------------------------------------


@router.post("/forgot-password", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("3/minute")
async def forgot_password(
    body: PasswordResetRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Request password reset. Always returns 204 (no user enumeration)."""
    user = await get_user_by_email(db, body.email)
    if user and user.is_active:
        raw_token = await create_password_reset_token(db, user)
        reset_url = f"{_frontend_url()}/reset-password?token={raw_token}"
        try:
            await send_password_reset_email(user.email, reset_url, user.full_name, locale=user.locale)
        except Exception:
            logger.exception("Failed to send password reset email (feyra)")
        await log_audit_event(
            db, FeyraAuditEventType.PASSWORD_RESET_REQUEST, user.id,
            get_client_ip(request), request.headers.get("user-agent"),
            {"source": "feyra"},
        )


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("5/minute")
async def reset_password(
    body: PasswordResetConfirm,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Reset password using token."""
    token = await validate_password_reset_token(db, body.token)
    if not token:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    token.used_at = datetime.now(timezone.utc)
    await db.flush()

    user = token.user
    await change_password(db, user, body.new_password)
    await invalidate_user_cache(user.id, user.email)
    await revoke_all_user_sessions(db, user.id)

    await log_audit_event(
        db, FeyraAuditEventType.PASSWORD_RESET_COMPLETE, user.id,
        get_client_ip(request), request.headers.get("user-agent"),
        {"source": "feyra"},
    )
    await db.flush()


# ---------------------------------------------------------------------------
# Email Verification
# ---------------------------------------------------------------------------


@router.post("/send-verification", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("3/minute")
async def send_verification(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: FeyraUser = Depends(get_current_feyra_user),
) -> None:
    """Send email verification to current user."""
    if current_user.is_verified:
        raise HTTPException(status_code=400, detail="Email already verified")

    raw_token = await create_email_verification_token(db, current_user)
    verify_url = f"{_frontend_url()}/verify-email?token={raw_token}"
    await send_verification_email(current_user.email, verify_url, current_user.full_name, locale=current_user.locale)
    await log_audit_event(
        db, FeyraAuditEventType.EMAIL_VERIFICATION_SENT, current_user.id,
        get_client_ip(request), request.headers.get("user-agent"),
        {"source": "feyra"},
    )


@router.post("/verify-email", status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
async def verify_email(
    body: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Verify email with token. No auth required."""
    raw_token = body.get("token", "")
    token = await validate_email_verification_token(db, raw_token)
    if not token:
        raise HTTPException(status_code=400, detail="Invalid or expired verification token")

    user = token.user
    user.is_verified = True
    token.used_at = datetime.now(timezone.utc)

    await invalidate_user_cache(user.id, user.email)
    await log_audit_event(
        db, FeyraAuditEventType.EMAIL_VERIFIED, user.id,
        get_client_ip(request), request.headers.get("user-agent"),
        {"source": "feyra"},
    )
    await db.flush()
    return {"message": "Email verified successfully"}


# ---------------------------------------------------------------------------
# Profile (authenticated)
# ---------------------------------------------------------------------------


@router.get("/me", response_model=FeyraUserResponse)
async def me(current_user: FeyraUser = Depends(get_current_feyra_user)) -> FeyraUserResponse:
    return FeyraUserResponse.model_validate(current_user)


@router.patch("/me", response_model=FeyraUserResponse)
async def update_profile(
    body: UpdateProfileRequest,
    request: Request,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
) -> FeyraUserResponse:
    ALLOWED_PROFILE_FIELDS = {"full_name", "company_name", "phone", "avatar_url", "org_number"}

    db_user = await get_user_by_id(db, current_user.id)
    if not db_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    ip = get_client_ip(request)
    ua = request.headers.get("user-agent")

    updates = body.model_dump(exclude_unset=True)

    profile_changes: dict[str, tuple[str | None, str | None]] = {}
    for field, value in updates.items():
        if field in ALLOWED_PROFILE_FIELDS:
            old_val = getattr(db_user, field, None)
            if old_val != value:
                profile_changes[field] = (old_val, value)
            setattr(db_user, field, value)

    await db.flush()

    if profile_changes:
        await log_audit_event(
            db, FeyraAuditEventType.PROFILE_UPDATE, db_user.id, ip, ua,
            {"changes": {k: {"old": v[0], "new": v[1]} for k, v in profile_changes.items()}, "source": "feyra"},
        )

    await invalidate_user_cache(db_user.id, db_user.email)
    await db.refresh(db_user)
    return FeyraUserResponse.model_validate(db_user)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password_endpoint(
    body: ChangePasswordRequest,
    request: Request,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    db_user = await get_user_by_id(db, current_user.id)
    if not db_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if not db_user.password_hash or not verify_password(body.current_password, db_user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")

    await change_password(db, db_user, body.new_password)
    await invalidate_user_cache(db_user.id, db_user.email)

    ip = get_client_ip(request)
    ua = request.headers.get("user-agent")
    await log_audit_event(db, FeyraAuditEventType.PASSWORD_CHANGE, db_user.id, ip, ua, {"source": "feyra"})


# ---------------------------------------------------------------------------
# Sessions (authenticated)
# ---------------------------------------------------------------------------


@router.get("/sessions", response_model=list[SessionResponse])
async def list_sessions(
    request: Request,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
) -> list[SessionResponse]:
    result = await db.execute(
        select(FeyraSession)
        .where(and_(FeyraSession.user_id == current_user.id, FeyraSession.revoked_at.is_(None)))
        .order_by(FeyraSession.created_at.desc())
    )
    sessions = result.scalars().all()

    current_token = request.cookies.get(REFRESH_COOKIE_NAME)
    current_hash = _hash_token(current_token) if current_token else None

    return [
        SessionResponse(
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


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session_endpoint(
    session_id: str,
    request: Request,
    current_user: FeyraUser = Depends(get_current_feyra_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(FeyraSession).where(
            and_(FeyraSession.id == session_id, FeyraSession.user_id == current_user.id)
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    await revoke_session(db, session.id)
    ip = get_client_ip(request)
    ua = request.headers.get("user-agent")
    await log_audit_event(
        db, FeyraAuditEventType.SESSION_REVOKED, current_user.id, ip, ua,
        {"source": "feyra"},
    )
