"""Fernet encryption for sensitive platform_config fields (Shopify tokens, WordPress passwords).

Encrypts credentials before storing in the database and decrypts them when needed.
Uses the same Fernet pattern as Feyra (app/feyra/encryption.py) but with a separate key.

Key is read from the AUTOBLOGGER_ENCRYPTION_KEY environment variable (via config).
The key must be a valid Fernet key (32 url-safe base64-encoded bytes).
Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
import base64
import copy
import logging
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = logging.getLogger(__name__)

_fernet: Fernet | None = None

# Keys within platform_config that contain sensitive credentials
_SENSITIVE_KEYS = frozenset({"access_token", "app_password"})


def _get_fernet() -> Fernet:
    """Lazily initialize the Fernet cipher from the configured key."""
    global _fernet
    if _fernet is not None:
        return _fernet

    key = settings.AUTOBLOGGER_ENCRYPTION_KEY
    if not key:
        raise RuntimeError(
            "AUTOBLOGGER_ENCRYPTION_KEY is not configured. "
            'Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )

    try:
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as exc:
        raise RuntimeError(
            "Invalid AUTOBLOGGER_ENCRYPTION_KEY. Must be a valid Fernet key (32 url-safe base64-encoded bytes)."
        ) from exc

    return _fernet


def encrypt_value(plain: str) -> str:
    """Encrypt a plaintext string and return a base64-encoded string for DB storage."""
    f = _get_fernet()
    encrypted_bytes = f.encrypt(plain.encode("utf-8"))
    return base64.urlsafe_b64encode(encrypted_bytes).decode("ascii")


def decrypt_value(encrypted: str) -> str:
    """Decrypt a base64-encoded encrypted string back to plaintext."""
    f = _get_fernet()
    try:
        encrypted_bytes = base64.urlsafe_b64decode(encrypted.encode("ascii"))
        return f.decrypt(encrypted_bytes).decode("utf-8")
    except InvalidToken:
        raise ValueError("Failed to decrypt value -- invalid key or corrupted data")
    except Exception as exc:
        raise ValueError(f"Failed to decrypt value: {exc}") from exc


def encrypt_platform_config(config: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a copy of platform_config with sensitive fields encrypted.

    Non-sensitive fields (shop_domain, blog_id, blogs, site_name, api_url, username)
    are left in plaintext so they remain queryable / displayable.
    """
    if not config:
        return config

    result = copy.deepcopy(config)
    for key in _SENSITIVE_KEYS:
        if key in result and result[key] and isinstance(result[key], str):
            # Skip if already encrypted (Fernet prefix or our ENC: prefix)
            if not result[key].startswith("gAAAAA") and not result[key].startswith("ENC:"):
                result[key] = "ENC:" + encrypt_value(result[key])
    return result


def decrypt_platform_config(config: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a copy of platform_config with sensitive fields decrypted.

    Supports both legacy (gAAAAA prefix) and new (ENC: prefix) encrypted values.
    Gracefully handles plaintext values (not yet encrypted) by returning them as-is.
    """
    if not config:
        return config

    result = copy.deepcopy(config)
    for key in _SENSITIVE_KEYS:
        if key in result and result[key] and isinstance(result[key], str):
            try:
                if result[key].startswith("ENC:"):
                    result[key] = decrypt_value(result[key][4:])
                elif result[key].startswith("gAAAAA"):
                    result[key] = decrypt_value(result[key])
            except ValueError:
                logger.warning(
                    "Failed to decrypt platform_config.%s -- returning as-is", key
                )
    return result
