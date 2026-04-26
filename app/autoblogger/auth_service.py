"""AutoBlogger-specific auth service — standalone, does not share users with Qvicko.

Mirrors app.feyra.auth_service but operates on AutoBlogger models in the 'autoblogger' schema.
Tokens include a "product": "autoblogger" claim to prevent cross-product token reuse.
"""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

import httpx
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.autoblogger.models import (
    AutoBloggerAuditEventType,
    AutoBloggerAuditLog,
    AutoBloggerEmailVerificationToken,
    AutoBloggerPasswordResetToken,
    AutoBloggerSession,
    AutoBloggerSocialAccount,
    AutoBloggerSocialProvider,
    AutoBloggerUser,
)
from app.config import settings

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 15


# ---------------------------------------------------------------------------
# Password utilities
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ---------------------------------------------------------------------------
# JWT tokens (short-lived access tokens with "product": "autoblogger" claim)
# ---------------------------------------------------------------------------


def create_access_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": user_id,
        "exp": expire,
        "type": "access",
        "product": "autoblogger",
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> str | None:
    """Decode and validate an AutoBlogger access token. Returns user_id or None."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != "access":
            return None
        if payload.get("product") != "autoblogger":
            return None
        return payload.get("sub")
    except JWTError:
        return None


# ---------------------------------------------------------------------------
# Session tokens (long-lived, DB-backed refresh tokens)
# ---------------------------------------------------------------------------


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_session_token() -> str:
    return secrets.token_urlsafe(48)


def compute_device_fingerprint(user_agent: str | None, ip_address: str | None) -> str:
    """Compute a stable device fingerprint from user-agent and IP subnet."""
    ua_part = (user_agent or "unknown").strip()
    ip_part = ""
    if ip_address:
        if ":" in ip_address:
            groups = ip_address.split(":")
            ip_part = ":".join(groups[:3])
        else:
            octets = ip_address.split(".")
            ip_part = ".".join(octets[:3])
    raw = f"{ua_part}|{ip_part}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def _has_trusted_device(
    db: AsyncSession, user_id: str, fingerprint: str
) -> bool:
    """Check if user has a previous trusted session with the same device fingerprint."""
    result = await db.execute(
        select(AutoBloggerSession.id).where(
            and_(
                AutoBloggerSession.user_id == user_id,
                AutoBloggerSession.device_fingerprint == fingerprint,
                AutoBloggerSession.is_trusted.is_(True),
            )
        ).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def create_session(
    db: AsyncSession,
    user_id: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
    trust_device: bool = False,
) -> tuple[AutoBloggerSession, str]:
    """Create a new AutoBlogger session and return (session, raw_token)."""
    raw_token = generate_session_token()
    now = datetime.now(timezone.utc)
    fingerprint = compute_device_fingerprint(user_agent, ip_address)

    is_trusted = trust_device or await _has_trusted_device(db, user_id, fingerprint)

    if is_trusted:
        refresh_days = settings.TRUSTED_DEVICE_REFRESH_DAYS
        master_expires = now + timedelta(days=settings.MASTER_SESSION_EXPIRE_DAYS)
    else:
        refresh_days = settings.REFRESH_TOKEN_EXPIRE_DAYS
        master_expires = None

    session = AutoBloggerSession(
        user_id=user_id,
        token_hash=_hash_token(raw_token),
        ip_address=ip_address,
        user_agent=user_agent,
        device_fingerprint=fingerprint,
        is_trusted=is_trusted,
        master_expires_at=master_expires,
        expires_at=now + timedelta(days=refresh_days),
        last_active_at=now,
    )
    db.add(session)
    await db.flush()
    return session, raw_token


async def validate_session(db: AsyncSession, raw_token: str) -> AutoBloggerSession | None:
    """Validate a session token and return the session if valid."""
    token_hash = _hash_token(raw_token)
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(AutoBloggerSession).where(
            and_(
                AutoBloggerSession.token_hash == token_hash,
                AutoBloggerSession.revoked_at.is_(None),
            )
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        return None

    if session.is_trusted and session.master_expires_at:
        if session.master_expires_at > now:
            return session
        return None

    if session.expires_at <= now:
        return None

    return session


async def revoke_session(db: AsyncSession, session_id: str) -> None:
    result = await db.execute(select(AutoBloggerSession).where(AutoBloggerSession.id == session_id))
    session = result.scalar_one_or_none()
    if session:
        session.revoked_at = datetime.now(timezone.utc)
        await db.flush()


async def revoke_all_user_sessions(db: AsyncSession, user_id: str) -> int:
    result = await db.execute(
        select(AutoBloggerSession).where(
            and_(AutoBloggerSession.user_id == user_id, AutoBloggerSession.revoked_at.is_(None))
        )
    )
    sessions = result.scalars().all()
    now = datetime.now(timezone.utc)
    for s in sessions:
        s.revoked_at = now
    return len(sessions)


# ---------------------------------------------------------------------------
# User cache helpers (autoblogger: prefix — no-op stubs for now)
# ---------------------------------------------------------------------------


async def invalidate_user_cache(user_id: str, email: str | None = None) -> None:
    """Placeholder for future cache invalidation with autoblogger: prefix."""
    pass


# ---------------------------------------------------------------------------
# User queries (direct DB — no caching)
# ---------------------------------------------------------------------------


async def get_user_by_email(db: AsyncSession, email: str) -> AutoBloggerUser | None:
    result = await db.execute(select(AutoBloggerUser).where(AutoBloggerUser.email == email))
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: str) -> AutoBloggerUser | None:
    result = await db.execute(select(AutoBloggerUser).where(AutoBloggerUser.id == user_id))
    return result.scalar_one_or_none()


async def create_user(
    db: AsyncSession,
    email: str,
    password: str,
    full_name: str,
    company_name: str | None = None,
    org_number: str | None = None,
    phone: str | None = None,
    locale: str | None = None,
) -> AutoBloggerUser:
    user = AutoBloggerUser(
        email=email,
        password_hash=hash_password(password),
        full_name=full_name,
        company_name=company_name,
        org_number=org_number,
        phone=phone,
        locale=locale or "sv",
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Account security
# ---------------------------------------------------------------------------


def is_account_locked(user: AutoBloggerUser) -> bool:
    if user.locked_until and user.locked_until > datetime.now(timezone.utc):
        return True
    return False


async def record_failed_login(db: AsyncSession, user: AutoBloggerUser) -> None:
    user.failed_login_attempts += 1
    if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
        user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_DURATION_MINUTES)


async def reset_failed_logins(db: AsyncSession, user: AutoBloggerUser) -> None:
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = datetime.now(timezone.utc)


async def change_password(db: AsyncSession, user: AutoBloggerUser, new_password: str) -> None:
    user.password_hash = hash_password(new_password)
    user.password_changed_at = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------


async def log_audit_event(
    db: AsyncSession,
    event_type: AutoBloggerAuditEventType,
    user_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    metadata: dict | None = None,
) -> AutoBloggerAuditLog:
    entry = AutoBloggerAuditLog(
        user_id=user_id,
        event_type=event_type,
        ip_address=ip_address,
        user_agent=user_agent,
        metadata_=metadata,
    )
    db.add(entry)
    await db.flush()
    return entry


def get_client_ip(request) -> str | None:
    """Extract client IP, only trusting X-Forwarded-For behind a reverse proxy in production."""
    if settings.ENVIRONMENT == "production":
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


# ---------------------------------------------------------------------------
# Password reset tokens
# ---------------------------------------------------------------------------


async def create_password_reset_token(db: AsyncSession, user: AutoBloggerUser) -> str:
    """Create a password reset token. Returns the RAW token (not hash)."""
    raw_token = secrets.token_urlsafe(48)
    token = AutoBloggerPasswordResetToken(
        user_id=user.id,
        token_hash=_hash_token(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES),
    )
    db.add(token)
    await db.flush()
    return raw_token


async def validate_password_reset_token(db: AsyncSession, raw_token: str) -> AutoBloggerPasswordResetToken | None:
    """Validate a password reset token. Returns token if valid."""
    token_hash = _hash_token(raw_token)
    result = await db.execute(
        select(AutoBloggerPasswordResetToken)
        .where(AutoBloggerPasswordResetToken.token_hash == token_hash)
        .options(selectinload(AutoBloggerPasswordResetToken.user))
    )
    token = result.scalar_one_or_none()
    if not token:
        return None
    if token.used_at is not None:
        return None
    if token.expires_at < datetime.now(timezone.utc):
        return None
    return token


# ---------------------------------------------------------------------------
# Email verification tokens
# ---------------------------------------------------------------------------


async def create_email_verification_token(db: AsyncSession, user: AutoBloggerUser) -> str:
    """Create an email verification token. Returns the RAW token."""
    raw_token = secrets.token_urlsafe(48)
    token = AutoBloggerEmailVerificationToken(
        user_id=user.id,
        email=user.email,
        token_hash=_hash_token(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS),
    )
    db.add(token)
    await db.flush()
    return raw_token


async def validate_email_verification_token(db: AsyncSession, raw_token: str) -> AutoBloggerEmailVerificationToken | None:
    """Validate an email verification token. Returns token if valid."""
    token_hash = _hash_token(raw_token)
    result = await db.execute(
        select(AutoBloggerEmailVerificationToken)
        .where(AutoBloggerEmailVerificationToken.token_hash == token_hash)
        .options(selectinload(AutoBloggerEmailVerificationToken.user))
    )
    token = result.scalar_one_or_none()
    if not token:
        return None
    if token.used_at is not None:
        return None
    if token.expires_at < datetime.now(timezone.utc):
        return None
    return token


# ---------------------------------------------------------------------------
# Google OAuth
# ---------------------------------------------------------------------------

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


async def fetch_google_userinfo(access_token: str) -> dict:
    """Fetch Google user info using an access token (used by iOS flow).

    Returns dict with keys: id, email, name, picture.
    Raises ValueError on failure.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if resp.status_code != 200:
            logger.warning("Google userinfo fetch failed: %s", resp.text)
            raise ValueError("Failed to fetch Google user info")
        return resp.json()


async def exchange_google_code(code: str, redirect_uri: str) -> dict:
    """Exchange a Google authorization code for user info.

    Returns dict with keys: id, email, name, picture.
    Raises ValueError on failure.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if token_resp.status_code != 200:
            logger.warning("Google token exchange failed: %s", token_resp.text)
            raise ValueError("Failed to exchange Google authorization code")

        token_data = token_resp.json()
        google_access_token = token_data.get("access_token")
        if not google_access_token:
            raise ValueError("No access token in Google response")

        userinfo_resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {google_access_token}"},
        )
        if userinfo_resp.status_code != 200:
            raise ValueError("Failed to fetch Google user info")

        return userinfo_resp.json()


async def get_or_create_google_user(
    db: AsyncSession, google_user: dict, locale: str = "sv"
) -> AutoBloggerUser:
    """Find existing AutoBlogger user by Google social account or email, or create a new one.

    Links the Google account if not already linked.
    Returns the AutoBloggerUser.
    """
    google_id = str(google_user["id"])
    google_email = google_user.get("email", "").lower()
    google_name = google_user.get("name", google_email.split("@")[0])
    google_picture = google_user.get("picture")

    # 1. Check if there's already an AutoBloggerSocialAccount for this Google ID
    result = await db.execute(
        select(AutoBloggerSocialAccount)
        .where(
            and_(
                AutoBloggerSocialAccount.provider == AutoBloggerSocialProvider.GOOGLE,
                AutoBloggerSocialAccount.provider_user_id == google_id,
            )
        )
        .options(selectinload(AutoBloggerSocialAccount.user))
    )
    social = result.scalar_one_or_none()

    if social and social.user:
        social.provider_data = google_user
        social.provider_email = google_email
        await db.flush()
        return social.user

    # 2. Check if an AutoBlogger user with this email already exists
    user = await get_user_by_email(db, google_email)

    if not user:
        # 3. Create new AutoBlogger user (no password — social-only account)
        hosted_domain = google_user.get("hd")
        company_name = None
        if hosted_domain:
            domain_parts = hosted_domain.split(".")
            company_name = domain_parts[0].capitalize() if domain_parts else None

        user = AutoBloggerUser(
            email=google_email,
            password_hash=None,
            full_name=google_name,
            avatar_url=google_picture,
            company_name=company_name,
            locale=locale,
            is_verified=True,
        )
        db.add(user)
        await db.flush()
        await db.refresh(user)

    # 4. Link Google account to AutoBlogger user
    social_account = AutoBloggerSocialAccount(
        user_id=user.id,
        provider=AutoBloggerSocialProvider.GOOGLE,
        provider_user_id=google_id,
        provider_email=google_email,
        provider_data=google_user,
    )
    db.add(social_account)

    if not user.is_verified:
        user.is_verified = True

    if not user.avatar_url and google_picture:
        user.avatar_url = google_picture

    await db.flush()
    return user


# ---------------------------------------------------------------------------
# Apple Sign-In
# ---------------------------------------------------------------------------

APPLE_TOKEN_URL = "https://appleid.apple.com/auth/token"
APPLE_KEYS_URL = "https://appleid.apple.com/auth/keys"


async def verify_apple_identity_token(identity_token: str) -> dict:
    """Verify an Apple identity token and return claims.

    Returns dict with keys: sub, email, email_verified.
    Raises ValueError on failure.
    """
    try:
        # Fetch Apple's public keys
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(APPLE_KEYS_URL)
            if resp.status_code != 200:
                raise ValueError("Failed to fetch Apple public keys")
            apple_keys = resp.json()

        # Decode header to find the right key
        headers = jwt.get_unverified_headers(identity_token)
        kid = headers.get("kid")

        # Find matching key
        matching_key = None
        for key in apple_keys.get("keys", []):
            if key.get("kid") == kid:
                matching_key = key
                break

        if not matching_key:
            raise ValueError("No matching Apple public key found")

        # Verify and decode the token
        from jose import jwk
        public_key = jwk.construct(matching_key)

        claims = jwt.decode(
            identity_token,
            public_key,
            algorithms=["RS256"],
            audience=settings.APPLE_CLIENT_ID,
            issuer="https://appleid.apple.com",
        )

        return claims
    except JWTError as e:
        raise ValueError(f"Invalid Apple identity token: {e}")


async def get_or_create_apple_user(
    db: AsyncSession,
    apple_claims: dict,
    full_name: str | None = None,
    email_hint: str | None = None,
    locale: str = "sv",
) -> AutoBloggerUser:
    """Find existing AutoBlogger user by Apple social account or email, or create a new one."""
    apple_id = apple_claims["sub"]
    apple_email = (apple_claims.get("email") or email_hint or "").lower()

    # 1. Check for existing social account
    result = await db.execute(
        select(AutoBloggerSocialAccount)
        .where(
            and_(
                AutoBloggerSocialAccount.provider == AutoBloggerSocialProvider.APPLE,
                AutoBloggerSocialAccount.provider_user_id == apple_id,
            )
        )
        .options(selectinload(AutoBloggerSocialAccount.user))
    )
    social = result.scalar_one_or_none()

    if social and social.user:
        return social.user

    # 2. Check if user with this email exists
    user = None
    if apple_email:
        user = await get_user_by_email(db, apple_email)

    if not user:
        display_name = full_name or apple_email.split("@")[0] if apple_email else "Apple User"
        user = AutoBloggerUser(
            email=apple_email,
            password_hash=None,
            full_name=display_name,
            locale=locale,
            is_verified=True,
        )
        db.add(user)
        await db.flush()
        await db.refresh(user)

    # 3. Link Apple account
    social_account = AutoBloggerSocialAccount(
        user_id=user.id,
        provider=AutoBloggerSocialProvider.APPLE,
        provider_user_id=apple_id,
        provider_email=apple_email,
        provider_data=apple_claims,
    )
    db.add(social_account)

    if not user.is_verified:
        user.is_verified = True

    await db.flush()
    return user
