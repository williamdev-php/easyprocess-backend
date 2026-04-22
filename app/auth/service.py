import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.models import AuditEventType, AuditLog, Session, SettingsAuditLog, User
from app.cache import cache
from app.config import settings

logger = logging.getLogger(__name__)

# Cache TTLs (seconds)
_USER_CACHE_TTL = 300  # 5 minutes

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
# JWT tokens (short-lived access tokens)
# ---------------------------------------------------------------------------

def create_access_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": user_id, "exp": expire, "type": "access"}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != "access":
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
    """Compute a stable device fingerprint from user-agent and IP subnet.

    Uses the /24 subnet (IPv4) or /48 prefix (IPv6) so that minor IP changes
    (e.g. DHCP renewal within the same network) don't break trust.
    """
    ua_part = (user_agent or "unknown").strip()
    ip_part = ""
    if ip_address:
        if ":" in ip_address:
            # IPv6 — use first 3 groups (/48)
            groups = ip_address.split(":")
            ip_part = ":".join(groups[:3])
        else:
            # IPv4 — use first 3 octets (/24)
            octets = ip_address.split(".")
            ip_part = ".".join(octets[:3])
    raw = f"{ua_part}|{ip_part}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def _has_trusted_device(
    db: AsyncSession, user_id: str, fingerprint: str
) -> bool:
    """Check if user has a previous trusted session with the same device fingerprint."""
    result = await db.execute(
        select(Session.id).where(
            and_(
                Session.user_id == user_id,
                Session.device_fingerprint == fingerprint,
                Session.is_trusted.is_(True),
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
) -> tuple[Session, str]:
    """Create a new session and return (session, raw_token).

    If trust_device is True, or the device fingerprint matches a previously
    trusted session, the session becomes a master session with extended expiry.
    """
    raw_token = generate_session_token()
    now = datetime.now(timezone.utc)
    fingerprint = compute_device_fingerprint(user_agent, ip_address)

    # Auto-trust if this device was previously trusted by the user
    is_trusted = trust_device or await _has_trusted_device(db, user_id, fingerprint)

    if is_trusted:
        refresh_days = settings.TRUSTED_DEVICE_REFRESH_DAYS
        master_expires = now + timedelta(days=settings.MASTER_SESSION_EXPIRE_DAYS)
    else:
        refresh_days = settings.REFRESH_TOKEN_EXPIRE_DAYS
        master_expires = None

    session = Session(
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


async def validate_session(db: AsyncSession, raw_token: str) -> Session | None:
    """Validate a session token and return the session if valid.

    For trusted master sessions: the session is valid as long as the master
    expiry hasn't passed, even if the refresh token's expires_at has lapsed
    (the refresh endpoint will extend it).
    """
    token_hash = _hash_token(raw_token)
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(Session).where(
            and_(
                Session.token_hash == token_hash,
                Session.revoked_at.is_(None),
            )
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        return None

    # For trusted sessions with a master expiry, check master_expires_at
    if session.is_trusted and session.master_expires_at:
        if session.master_expires_at > now:
            return session
        # Master session expired
        return None

    # For untrusted sessions, check the normal expires_at
    if session.expires_at <= now:
        return None

    return session


async def revoke_session(db: AsyncSession, session_id: str) -> None:
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if session:
        session.revoked_at = datetime.now(timezone.utc)
        await db.flush()


async def revoke_all_user_sessions(db: AsyncSession, user_id: str) -> int:
    result = await db.execute(
        select(Session).where(
            and_(Session.user_id == user_id, Session.revoked_at.is_(None))
        )
    )
    sessions = result.scalars().all()
    now = datetime.now(timezone.utc)
    for s in sessions:
        s.revoked_at = now
    return len(sessions)


# ---------------------------------------------------------------------------
# User cache helpers
# ---------------------------------------------------------------------------

def _user_cache_key(user_id: str) -> str:
    return f"user:{user_id}"


def _email_cache_key(email: str) -> str:
    return f"user_email:{email.lower()}"


def _serialize_user(user: User) -> dict:
    """Serialize user to a dict for caching (only fields needed for auth checks)."""
    return {
        "id": user.id,
        "email": user.email,
        "password_hash": user.password_hash,
        "full_name": user.full_name,
        "company_name": user.company_name,
        "org_number": user.org_number,
        "phone": user.phone,
        "avatar_url": user.avatar_url,
        "locale": user.locale,
        "role": user.role.value if user.role else "USER",
        "is_superuser": user.is_superuser,
        "is_active": user.is_active,
        "is_verified": user.is_verified,
        "two_factor_enabled": user.two_factor_enabled,
        "failed_login_attempts": user.failed_login_attempts,
        "locked_until": user.locked_until.isoformat() if user.locked_until else None,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "password_changed_at": user.password_changed_at.isoformat() if user.password_changed_at else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
        "stripe_customer_id": user.stripe_customer_id,
        "subscription_id": user.subscription_id,
        "billing_street": user.billing_street,
        "billing_city": user.billing_city,
        "billing_zip": user.billing_zip,
        "billing_country": user.billing_country,
    }


async def invalidate_user_cache(user_id: str, email: str | None = None) -> None:
    """Invalidate all cached data for a user."""
    await cache.delete(_user_cache_key(user_id))
    if email:
        await cache.delete(_email_cache_key(email))


# ---------------------------------------------------------------------------
# User queries (with caching)
# ---------------------------------------------------------------------------

def _user_from_cache(data: dict) -> User:
    """Reconstruct a transient (detached) User instance from cached dict (read-only)."""
    from app.auth.models import UserRole

    return User(
        id=data["id"],
        email=data["email"],
        password_hash=data.get("password_hash"),
        full_name=data.get("full_name", ""),
        company_name=data.get("company_name"),
        org_number=data.get("org_number"),
        phone=data.get("phone"),
        avatar_url=data.get("avatar_url"),
        locale=data.get("locale", "sv"),
        role=UserRole(data.get("role", "USER")),
        is_superuser=data.get("is_superuser", False),
        is_active=data.get("is_active", True),
        is_verified=data.get("is_verified", False),
        two_factor_enabled=data.get("two_factor_enabled", False),
        failed_login_attempts=data.get("failed_login_attempts", 0),
        locked_until=(
            datetime.fromisoformat(data["locked_until"]) if data.get("locked_until") else None
        ),
        last_login_at=(
            datetime.fromisoformat(data["last_login_at"]) if data.get("last_login_at") else None
        ),
        password_changed_at=(
            datetime.fromisoformat(data["password_changed_at"]) if data.get("password_changed_at") else None
        ),
        created_at=(
            datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(timezone.utc)
        ),
        updated_at=(
            datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.now(timezone.utc)
        ),
        stripe_customer_id=data.get("stripe_customer_id"),
        subscription_id=data.get("subscription_id"),
        billing_street=data.get("billing_street"),
        billing_city=data.get("billing_city"),
        billing_zip=data.get("billing_zip"),
        billing_country=data.get("billing_country"),
    )


async def _cache_user(user: User) -> None:
    """Cache user data by both ID and email."""
    await cache.set(_user_cache_key(user.id), _serialize_user(user), ttl=_USER_CACHE_TTL)
    await cache.set(_email_cache_key(user.email), user.id, ttl=_USER_CACHE_TTL)


async def get_user_by_id_cached(user_id: str) -> User | None:
    """Return a cached (detached) User for read-only use (e.g. auth dependencies).
    Skips DB entirely on cache hit."""
    cached = await cache.get(_user_cache_key(user_id))
    if cached and isinstance(cached, dict):
        return _user_from_cache(cached)
    return None


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user:
        await _cache_user(user)
    return user


async def get_user_by_id(db: AsyncSession, user_id: str) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user:
        await _cache_user(user)
    return user


async def create_user(
    db: AsyncSession,
    email: str,
    password: str,
    full_name: str,
    company_name: str | None = None,
    org_number: str | None = None,
    phone: str | None = None,
    locale: str | None = None,
) -> User:
    user = User(
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

def is_account_locked(user: User) -> bool:
    if user.locked_until and user.locked_until > datetime.now(timezone.utc):
        return True
    return False


async def record_failed_login(db: AsyncSession, user: User) -> None:
    user.failed_login_attempts += 1
    if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
        user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_DURATION_MINUTES)


async def reset_failed_logins(db: AsyncSession, user: User) -> None:
    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = datetime.now(timezone.utc)


async def change_password(db: AsyncSession, user: User, new_password: str) -> None:
    user.password_hash = hash_password(new_password)
    user.password_changed_at = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------

async def log_audit_event(
    db: AsyncSession,
    event_type: AuditEventType,
    user_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    metadata: dict | None = None,
) -> AuditLog:
    entry = AuditLog(
        user_id=user_id,
        event_type=event_type,
        ip_address=ip_address,
        user_agent=user_agent,
        metadata_=metadata,
    )
    db.add(entry)
    await db.flush()
    return entry


async def log_settings_change(
    db: AsyncSession,
    user_id: str,
    event_type: AuditEventType,
    entity_type: str,
    entity_id: str | None,
    changes: dict[str, tuple[str | None, str | None]],
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> list[SettingsAuditLog]:
    """
    Log one row per changed field in settings_audit_logs.

    changes: dict mapping field_name -> (old_value, new_value)
    Only fields where old != new are logged.
    """
    entries = []
    for field_name, (old_val, new_val) in changes.items():
        old_str = str(old_val) if old_val is not None else None
        new_str = str(new_val) if new_val is not None else None
        if old_str == new_str:
            continue
        entry = SettingsAuditLog(
            user_id=user_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            field_name=field_name,
            old_value=old_str,
            new_value=new_str,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.add(entry)
        entries.append(entry)
    if entries:
        await db.flush()
    return entries


def get_client_ip(request) -> str | None:
    """Extract client IP, only trusting X-Forwarded-For behind a reverse proxy in production."""
    if settings.ENVIRONMENT == "production":
        # In production behind a trusted proxy (Railway, Vercel, etc.),
        # use the first IP in X-Forwarded-For (set by the proxy).
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    # In development or if no proxy header, use the direct connection IP.
    if request.client:
        return request.client.host
    return None


# ---------------------------------------------------------------------------
# Password reset tokens
# ---------------------------------------------------------------------------


async def create_password_reset_token(db: AsyncSession, user: User) -> str:
    """Create a password reset token. Returns the RAW token (not hash)."""
    from app.auth.models import PasswordResetToken

    raw_token = secrets.token_urlsafe(48)
    token = PasswordResetToken(
        user_id=user.id,
        token_hash=_hash_token(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES),
    )
    db.add(token)
    await db.flush()
    return raw_token


async def validate_password_reset_token(db: AsyncSession, raw_token: str):
    """Validate a password reset token. Returns token if valid."""
    from app.auth.models import PasswordResetToken

    token_hash = _hash_token(raw_token)
    result = await db.execute(
        select(PasswordResetToken)
        .where(PasswordResetToken.token_hash == token_hash)
        .options(selectinload(PasswordResetToken.user))
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


async def create_email_verification_token(db: AsyncSession, user: User) -> str:
    """Create an email verification token. Returns the RAW token."""
    from app.auth.models import EmailVerificationToken

    raw_token = secrets.token_urlsafe(48)
    token = EmailVerificationToken(
        user_id=user.id,
        email=user.email,
        token_hash=_hash_token(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS),
    )
    db.add(token)
    await db.flush()
    return raw_token


async def validate_email_verification_token(db: AsyncSession, raw_token: str):
    """Validate an email verification token. Returns token if valid."""
    from app.auth.models import EmailVerificationToken

    token_hash = _hash_token(raw_token)
    result = await db.execute(
        select(EmailVerificationToken)
        .where(EmailVerificationToken.token_hash == token_hash)
        .options(selectinload(EmailVerificationToken.user))
    )
    token = result.scalar_one_or_none()
    if not token:
        return None
    if token.used_at is not None:
        return None
    if token.expires_at < datetime.now(timezone.utc):
        return None
    return token
