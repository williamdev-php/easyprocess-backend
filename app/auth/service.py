import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.models import AuditEventType, AuditLog, Session, SettingsAuditLog, User
from app.config import settings

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


async def create_session(
    db: AsyncSession,
    user_id: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[Session, str]:
    """Create a new session and return (session, raw_token)."""
    raw_token = generate_session_token()
    session = Session(
        user_id=user_id,
        token_hash=_hash_token(raw_token),
        ip_address=ip_address,
        user_agent=user_agent,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(session)
    await db.flush()
    return session, raw_token


async def validate_session(db: AsyncSession, raw_token: str) -> Session | None:
    """Validate a session token and return the session if valid."""
    token_hash = _hash_token(raw_token)
    result = await db.execute(
        select(Session).where(
            and_(
                Session.token_hash == token_hash,
                Session.revoked_at.is_(None),
                Session.expires_at > datetime.now(timezone.utc),
            )
        )
    )
    return result.scalar_one_or_none()


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
# User queries
# ---------------------------------------------------------------------------

async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: str) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def create_user(
    db: AsyncSession,
    email: str,
    password: str,
    full_name: str,
    company_name: str | None = None,
    org_number: str | None = None,
    phone: str | None = None,
) -> User:
    user = User(
        email=email,
        password_hash=hash_password(password),
        full_name=full_name,
        company_name=company_name,
        org_number=org_number,
        phone=phone,
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
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
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
