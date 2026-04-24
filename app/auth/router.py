import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, Request, status
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.models import AuditEventType, AuditLog, Session, SettingsAuditLog, User
from app.auth.schemas import (
    ChangePasswordRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    ResendVerificationRequest,
    SessionResponse,
    AuditLogResponse,
    SettingsAuditLogResponse,
    TokenResponse,
    UpdateProfileRequest,
    UserLogin,
    UserRegister,
    UserResponse,
)
from app.auth.service import (
    change_password,
    create_access_token,
    create_email_verification_token,
    create_password_reset_token,
    create_session,
    create_user,
    exchange_google_code,
    fetch_google_userinfo,
    get_client_ip,
    get_or_create_apple_user,
    get_or_create_google_user,
    get_user_by_email,
    get_user_by_id,
    invalidate_user_cache,
    is_account_locked,
    log_audit_event,
    log_settings_change,
    record_failed_login,
    reset_failed_logins,
    revoke_all_user_sessions,
    revoke_session,
    validate_email_verification_token,
    validate_password_reset_token,
    validate_session,
    verify_apple_identity_token,
    verify_password,
)
from app.config import settings
from app.database import get_db
from app.email.service import _send_via_resend
from app.email.templates import build_password_reset_email, build_verification_email
from app.rate_limit import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

REFRESH_COOKIE_NAME = "refresh_token"


def _cookie_max_age(is_trusted: bool) -> int:
    """Return cookie max-age in seconds based on device trust."""
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
        path="/api/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=REFRESH_COOKIE_NAME, path="/api/auth")


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

    # Trust the device on first registration
    session, raw_token = await create_session(
        db, user.id, ip_address=ip, user_agent=ua, trust_device=True
    )
    await log_audit_event(db, AuditEventType.REGISTER, user.id, ip, ua)

    # Send verification email (non-blocking — user is created even if email fails,
    # but we log a warning so ops can investigate delivery issues).
    email_sent = False
    try:
        verification_token = await create_email_verification_token(db, user)
        verify_url = f"{settings.FRONTEND_URL}/verify-email?token={verification_token}"
        subject, html, text = build_verification_email(verify_url, user.full_name, locale=user.locale)
        await _send_via_resend(user.email, subject, html, text)
        email_sent = True
    except Exception:
        logger.exception("Failed to send verification email to %s on registration", user.email)
    if not email_sent:
        logger.warning("User %s registered but verification email was NOT delivered", user.id)

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
        await log_audit_event(db, AuditEventType.LOGIN_FAILED, None, ip, ua, {"email": body.email})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account deactivated")

    if is_account_locked(user):
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="Account temporarily locked. Try again later.")

    if not verify_password(body.password, user.password_hash):
        await record_failed_login(db, user)
        await log_audit_event(db, AuditEventType.LOGIN_FAILED, user.id, ip, ua)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    await reset_failed_logins(db, user)
    await invalidate_user_cache(user.id, user.email)

    # Trust device on successful login (auto-trusts if fingerprint was previously trusted)
    session, raw_token = await create_session(
        db, user.id, ip_address=ip, user_agent=ua, trust_device=True
    )
    await log_audit_event(db, AuditEventType.LOGIN, user.id, ip, ua)

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
            # iOS flow: SDK already exchanged the code, we just need user info
            google_user = await fetch_google_userinfo(google_access_token)
        else:
            # Web flow: exchange authorization code for tokens
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
        db, AuditEventType.LOGIN, user.id, ip, ua,
        {"provider": "google"},
    )

    access_token = create_access_token(user.id)
    _set_refresh_cookie(response, raw_token, is_trusted=session.is_trusted)
    return TokenResponse(access_token=access_token)


# ---------------------------------------------------------------------------
# Apple Sign-In
# ---------------------------------------------------------------------------


@router.post("/apple", response_model=TokenResponse)
@limiter.limit("10/minute")
async def apple_auth(
    body: dict,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Authenticate with Apple Sign-In. Accepts {identity_token, full_name?, email?, locale?}."""
    identity_token = body.get("identity_token")
    full_name = body.get("full_name")
    email_hint = body.get("email")
    locale = body.get("locale", "sv")

    if not identity_token:
        raise HTTPException(status_code=400, detail="Missing identity_token")

    if not settings.APPLE_CLIENT_ID:
        raise HTTPException(status_code=501, detail="Apple Sign-In is not configured")

    try:
        apple_claims = await verify_apple_identity_token(identity_token)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not apple_claims.get("sub"):
        raise HTTPException(status_code=400, detail="Invalid Apple token — no subject")

    user = await get_or_create_apple_user(
        db, apple_claims,
        full_name=full_name,
        email_hint=email_hint,
        locale=locale,
    )

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
        db, AuditEventType.LOGIN, user.id, ip, ua,
        {"provider": "apple"},
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
    # Support both cookie (web) and body (iOS) refresh tokens
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

    # Rotate session token, carrying over device trust
    ip = get_client_ip(request)
    ua = request.headers.get("user-agent")

    was_trusted = session.is_trusted
    await revoke_session(db, session.id)
    new_session, new_token = await create_session(
        db, user.id, ip_address=ip, user_agent=ua,
        trust_device=was_trusted,
    )

    # Carry over the original master expiry so it doesn't reset on each refresh
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
            await log_audit_event(db, AuditEventType.LOGOUT, session.user_id, ip, ua)
    _clear_refresh_cookie(response)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    count = await revoke_all_user_sessions(db, current_user.id)
    ip = get_client_ip(request)
    ua = request.headers.get("user-agent")
    await log_audit_event(
        db, AuditEventType.SESSION_REVOKED, current_user.id, ip, ua,
        {"sessions_revoked": count},
    )
    _clear_refresh_cookie(response)


# ---------------------------------------------------------------------------
# Profile & Password
# ---------------------------------------------------------------------------


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.patch("/me", response_model=UserResponse)
async def update_profile(
    body: UpdateProfileRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    ALLOWED_PROFILE_FIELDS = {"full_name", "company_name", "phone", "avatar_url", "org_number"}
    BILLING_FIELDS = {"billing_street", "billing_city", "billing_zip", "billing_country"}

    # Re-fetch from DB for a session-bound instance (current_user may be cached)
    db_user = await get_user_by_id(db, current_user.id)
    if not db_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    ip = get_client_ip(request)
    ua = request.headers.get("user-agent")

    updates = body.model_dump(exclude_unset=True)

    # Track profile changes for audit
    profile_changes: dict[str, tuple[str | None, str | None]] = {}
    for field, value in updates.items():
        if field in ALLOWED_PROFILE_FIELDS:
            old_val = getattr(db_user, field, None)
            if old_val != value:
                profile_changes[field] = (old_val, value)
            setattr(db_user, field, value)

    # Track billing changes for audit
    billing_changes: dict[str, tuple[str | None, str | None]] = {}
    for field, value in updates.items():
        if field in BILLING_FIELDS:
            old_val = getattr(db_user, field, None)
            if old_val != value:
                billing_changes[field] = (old_val, value)
            setattr(db_user, field, value)

    await db.flush()

    # Log audit events for changed fields
    if profile_changes:
        await log_settings_change(
            db, db_user.id, AuditEventType.PROFILE_UPDATE,
            "user", db_user.id, profile_changes, ip, ua,
        )

    if billing_changes:
        await log_settings_change(
            db, db_user.id, AuditEventType.BILLING_ADDRESS_CHANGE,
            "user", db_user.id, billing_changes, ip, ua,
        )

    # Invalidate cache so subsequent requests see updated data
    await invalidate_user_cache(db_user.id, db_user.email)

    await db.refresh(db_user)
    return UserResponse.model_validate(db_user)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password_endpoint(
    body: ChangePasswordRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    # Re-fetch from DB for a session-bound instance (current_user may be cached)
    db_user = await get_user_by_id(db, current_user.id)
    if not db_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if not db_user.password_hash or not verify_password(body.current_password, db_user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")

    await change_password(db, db_user, body.new_password)
    await invalidate_user_cache(db_user.id, db_user.email)

    ip = get_client_ip(request)
    ua = request.headers.get("user-agent")
    await log_audit_event(db, AuditEventType.PASSWORD_CHANGE, db_user.id, ip, ua)


# ---------------------------------------------------------------------------
# Sessions & Audit (authenticated)
# ---------------------------------------------------------------------------


@router.get("/sessions", response_model=list[SessionResponse])
async def list_sessions(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SessionResponse]:
    from app.auth.service import _hash_token

    result = await db.execute(
        select(Session)
        .where(and_(Session.user_id == current_user.id, Session.revoked_at.is_(None)))
        .order_by(Session.created_at.desc())
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(Session).where(
            and_(Session.id == session_id, Session.user_id == current_user.id)
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    await revoke_session(db, session.id)
    ip = get_client_ip(request)
    ua = request.headers.get("user-agent")
    await log_audit_event(db, AuditEventType.SESSION_REVOKED, current_user.id, ip, ua)


@router.get("/audit-log", response_model=list[AuditLogResponse])
async def get_audit_log(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
) -> list[AuditLogResponse]:
    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.user_id == current_user.id)
        .order_by(AuditLog.created_at.desc())
        .limit(min(limit, 100))
        .offset(offset)
    )
    logs = result.scalars().all()
    return [AuditLogResponse.model_validate(log) for log in logs]


@router.get("/settings-audit-log", response_model=list[SettingsAuditLogResponse])
async def get_settings_audit_log(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
) -> list[SettingsAuditLogResponse]:
    """Return the settings change audit trail for the current user."""
    result = await db.execute(
        select(SettingsAuditLog)
        .where(SettingsAuditLog.user_id == current_user.id)
        .order_by(SettingsAuditLog.created_at.desc())
        .limit(min(limit, 100))
        .offset(offset)
    )
    logs = result.scalars().all()
    return [SettingsAuditLogResponse.model_validate(log) for log in logs]


# ---------------------------------------------------------------------------
# Password Reset & Email Verification
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
        reset_url = f"{settings.FRONTEND_URL}/reset-password?token={raw_token}"
        subject, html, text = build_password_reset_email(reset_url, user.full_name, locale=user.locale)
        try:
            await _send_via_resend(user.email, subject, html, text)
        except Exception:
            logger.exception("Failed to send password reset email")
        await log_audit_event(
            db, AuditEventType.PASSWORD_RESET_REQUEST, user.id,
            get_client_ip(request), request.headers.get("user-agent"),
        )
    # Always return 204 to prevent user enumeration


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

    # Mark token as used BEFORE changing password to prevent race conditions
    # (concurrent requests with same token).
    token.used_at = datetime.now(timezone.utc)
    await db.flush()

    user = token.user
    await change_password(db, user, body.new_password)
    await invalidate_user_cache(user.id, user.email)

    # Revoke all sessions for security
    await revoke_all_user_sessions(db, user.id)

    await log_audit_event(
        db, AuditEventType.PASSWORD_RESET_COMPLETE, user.id,
        get_client_ip(request), request.headers.get("user-agent"),
    )
    await db.flush()


@router.post("/send-verification", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("3/minute")
async def send_verification(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Send email verification to current user."""
    if current_user.is_verified:
        raise HTTPException(status_code=400, detail="Email already verified")

    raw_token = await create_email_verification_token(db, current_user)
    verify_url = f"{settings.FRONTEND_URL}/verify-email?token={raw_token}"
    subject, html, text = build_verification_email(verify_url, current_user.full_name, locale=current_user.locale)
    await _send_via_resend(current_user.email, subject, html, text)
    await log_audit_event(
        db, AuditEventType.EMAIL_VERIFICATION_SENT, current_user.id,
        get_client_ip(request), request.headers.get("user-agent"),
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
        db, AuditEventType.EMAIL_VERIFIED, user.id,
        get_client_ip(request), request.headers.get("user-agent"),
    )
    await db.flush()
    return {"message": "Email verified successfully"}
