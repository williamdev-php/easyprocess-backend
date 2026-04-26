"""AES-256-GCM encryption utility for IMAP/SMTP passwords.

Encrypts passwords before storing in the database and decrypts them when needed.
Uses the cryptography library's Fernet symmetric encryption (AES-128-CBC under the hood,
with HMAC-SHA256 for authentication). Simple, safe, and battle-tested.

Key is read from the FEYRA_ENCRYPTION_KEY environment variable (via config).
The key must be a valid Fernet key (32 url-safe base64-encoded bytes).
Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
import base64
import logging

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = logging.getLogger(__name__)

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    """Lazily initialize the Fernet cipher from the configured key."""
    global _fernet
    if _fernet is not None:
        return _fernet

    key = settings.FEYRA_ENCRYPTION_KEY
    if not key:
        raise RuntimeError(
            "FEYRA_ENCRYPTION_KEY is not configured. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )

    try:
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as exc:
        raise RuntimeError(
            "Invalid FEYRA_ENCRYPTION_KEY. Must be a valid Fernet key (32 url-safe base64-encoded bytes)."
        ) from exc

    return _fernet


def encrypt_password(plain: str) -> str:
    """Encrypt a plaintext password and return a base64-encoded string for DB storage."""
    f = _get_fernet()
    encrypted_bytes = f.encrypt(plain.encode("utf-8"))
    return base64.urlsafe_b64encode(encrypted_bytes).decode("ascii")


def decrypt_password(encrypted: str) -> str:
    """Decrypt a base64-encoded encrypted password back to plaintext."""
    f = _get_fernet()
    try:
        encrypted_bytes = base64.urlsafe_b64decode(encrypted.encode("ascii"))
        return f.decrypt(encrypted_bytes).decode("utf-8")
    except InvalidToken:
        raise ValueError("Failed to decrypt password — invalid key or corrupted data")
    except Exception as exc:
        raise ValueError(f"Failed to decrypt password: {exc}") from exc
