"""Email account service — IMAP/SMTP connection management, sending, and reading."""

import asyncio
import email as email_lib
import email.utils
import imaplib
import logging
import smtplib
import uuid
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.feyra.encryption import decrypt_password
from app.feyra.models import (
    ConnectionStatus,
    EmailAccount,
    EmailProvider,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider auto-detection
# ---------------------------------------------------------------------------

_PROVIDER_SETTINGS: dict[str, dict[str, Any]] = {
    "gmail.com": {
        "provider": EmailProvider.GMAIL,
        "imap_host": "imap.gmail.com",
        "imap_port": 993,
        "imap_use_ssl": True,
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "smtp_use_tls": True,
    },
    "googlemail.com": {
        "provider": EmailProvider.GMAIL,
        "imap_host": "imap.gmail.com",
        "imap_port": 993,
        "imap_use_ssl": True,
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "smtp_use_tls": True,
    },
    "outlook.com": {
        "provider": EmailProvider.OUTLOOK,
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
        "imap_use_ssl": True,
        "smtp_host": "smtp.office365.com",
        "smtp_port": 587,
        "smtp_use_tls": True,
    },
    "hotmail.com": {
        "provider": EmailProvider.OUTLOOK,
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
        "imap_use_ssl": True,
        "smtp_host": "smtp.office365.com",
        "smtp_port": 587,
        "smtp_use_tls": True,
    },
    "live.com": {
        "provider": EmailProvider.OUTLOOK,
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
        "imap_use_ssl": True,
        "smtp_host": "smtp.office365.com",
        "smtp_port": 587,
        "smtp_use_tls": True,
    },
    "yahoo.com": {
        "provider": EmailProvider.YAHOO,
        "imap_host": "imap.mail.yahoo.com",
        "imap_port": 993,
        "imap_use_ssl": True,
        "smtp_host": "smtp.mail.yahoo.com",
        "smtp_port": 587,
        "smtp_use_tls": True,
    },
}


def auto_detect_provider(email_address: str) -> dict:
    """Return provider enum and default IMAP/SMTP settings based on email domain.

    Falls back to CUSTOM provider with empty settings if the domain is not recognized.
    """
    domain = email_address.rsplit("@", 1)[-1].lower()
    if domain in _PROVIDER_SETTINGS:
        return dict(_PROVIDER_SETTINGS[domain])
    return {
        "provider": EmailProvider.CUSTOM,
        "imap_host": "",
        "imap_port": 993,
        "imap_use_ssl": True,
        "smtp_host": "",
        "smtp_port": 587,
        "smtp_use_tls": True,
    }


# ---------------------------------------------------------------------------
# Connection testing helpers (blocking I/O, run in executor)
# ---------------------------------------------------------------------------


def _test_imap_sync(
    host: str, port: int, username: str, password: str, use_ssl: bool
) -> tuple[bool, str]:
    """Synchronous IMAP connection test."""
    try:
        if use_ssl:
            conn = imaplib.IMAP4_SSL(host, port, timeout=15)
        else:
            conn = imaplib.IMAP4(host, port, timeout=15)
        conn.login(username, password)
        status, folders = conn.list()
        if status != "OK":
            conn.logout()
            return False, "IMAP login succeeded but failed to list folders"
        conn.logout()
        return True, f"IMAP connection successful — {len(folders)} folders found"
    except imaplib.IMAP4.error as exc:
        return False, f"IMAP authentication error: {exc}"
    except Exception as exc:
        return False, f"IMAP connection error: {exc}"


def _test_smtp_sync(
    host: str, port: int, username: str, password: str, use_tls: bool
) -> tuple[bool, str]:
    """Synchronous SMTP connection test."""
    try:
        if use_tls:
            server = smtplib.SMTP(host, port, timeout=15)
            server.ehlo()
            server.starttls()
            server.ehlo()
        else:
            server = smtplib.SMTP_SSL(host, port, timeout=15)
        server.login(username, password)
        server.quit()
        return True, "SMTP connection successful"
    except smtplib.SMTPAuthenticationError as exc:
        return False, f"SMTP authentication error: {exc}"
    except Exception as exc:
        return False, f"SMTP connection error: {exc}"


async def test_imap_connection(
    host: str, port: int, username: str, password: str, use_ssl: bool = True
) -> tuple[bool, str]:
    """Connect to IMAP, authenticate, list folders, and return (success, message)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, _test_imap_sync, host, port, username, password, use_ssl
    )


async def test_smtp_connection(
    host: str, port: int, username: str, password: str, use_tls: bool = True
) -> tuple[bool, str]:
    """Connect to SMTP, authenticate, and return (success, message)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, _test_smtp_sync, host, port, username, password, use_tls
    )


# ---------------------------------------------------------------------------
# Send email via SMTP
# ---------------------------------------------------------------------------


def _send_email_sync(
    smtp_host: str,
    smtp_port: int,
    username: str,
    password: str,
    use_tls: bool,
    from_email: str,
    to_email: str,
    subject: str,
    body_html: str,
    body_text: str,
    message_id: str | None,
    in_reply_to: str | None,
    reply_to: str | None,
) -> str:
    """Synchronous SMTP send. Returns the Message-ID."""
    msg = MIMEMultipart("alternative")
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Date"] = email.utils.formatdate(localtime=True)

    generated_message_id = message_id or f"<{uuid.uuid4()}@{from_email.split('@')[-1]}>"
    msg["Message-ID"] = generated_message_id

    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to

    if reply_to:
        msg["Reply-To"] = reply_to

    # Attach text and HTML parts
    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    if use_tls:
        server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
        server.ehlo()
        server.starttls()
        server.ehlo()
    else:
        server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30)

    server.login(username, password)
    server.sendmail(from_email, [to_email], msg.as_string())
    server.quit()
    return generated_message_id


async def send_email_smtp(
    account: EmailAccount,
    to_email: str,
    subject: str,
    body_html: str,
    body_text: str,
    message_id: str | None = None,
    in_reply_to: str | None = None,
    reply_to: str | None = None,
) -> str:
    """Send an email via the account's SMTP settings. Returns Message-ID."""
    password = decrypt_password(account.smtp_password_encrypted)
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        _send_email_sync,
        account.smtp_host,
        account.smtp_port,
        account.smtp_username or account.email_address,
        password,
        account.smtp_use_tls,
        account.email_address,
        to_email,
        subject,
        body_html,
        body_text,
        message_id,
        in_reply_to,
        reply_to,
    )


# ---------------------------------------------------------------------------
# Read emails via IMAP
# ---------------------------------------------------------------------------


def _parse_email_message(raw_data: bytes) -> dict:
    """Parse a raw email message into a dictionary."""
    msg = email_lib.message_from_bytes(raw_data)

    body_text = ""
    body_html = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    body_text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
            elif content_type == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    body_html = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            decoded = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
            if msg.get_content_type() == "text/html":
                body_html = decoded
            else:
                body_text = decoded

    return {
        "message_id": msg.get("Message-ID", ""),
        "from": msg.get("From", ""),
        "to": msg.get("To", ""),
        "subject": msg.get("Subject", ""),
        "date": msg.get("Date", ""),
        "in_reply_to": msg.get("In-Reply-To", ""),
        "references": msg.get("References", ""),
        "body_text": body_text,
        "body_html": body_html,
    }


def _read_inbox_sync(
    imap_host: str,
    imap_port: int,
    username: str,
    password: str,
    use_ssl: bool,
    folder: str,
    since_date: datetime | None,
    limit: int,
) -> list[dict]:
    """Synchronous IMAP inbox read."""
    if use_ssl:
        conn = imaplib.IMAP4_SSL(imap_host, imap_port, timeout=30)
    else:
        conn = imaplib.IMAP4(imap_host, imap_port, timeout=30)

    conn.login(username, password)
    conn.select(folder, readonly=True)

    if since_date:
        date_str = since_date.strftime("%d-%b-%Y")
        _, msg_nums = conn.search(None, f'(SINCE "{date_str}")')
    else:
        _, msg_nums = conn.search(None, "ALL")

    message_ids = msg_nums[0].split()
    if not message_ids:
        conn.logout()
        return []

    # Take the most recent messages up to limit
    message_ids = message_ids[-limit:]

    emails = []
    for msg_id in message_ids:
        _, data = conn.fetch(msg_id, "(RFC822)")
        if data and data[0] and isinstance(data[0], tuple):
            parsed = _parse_email_message(data[0][1])
            parsed["uid"] = msg_id.decode()
            emails.append(parsed)

    conn.logout()
    return emails


async def read_inbox_imap(
    account: EmailAccount,
    folder: str = "INBOX",
    since_date: datetime | None = None,
    limit: int = 50,
) -> list[dict]:
    """Read emails from an IMAP folder. Returns a list of parsed email dicts."""
    password = decrypt_password(account.imap_password_encrypted)
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        _read_inbox_sync,
        account.imap_host,
        account.imap_port,
        account.imap_username or account.email_address,
        password,
        account.imap_use_ssl,
        folder,
        since_date,
        limit,
    )


# ---------------------------------------------------------------------------
# Spam folder operations
# ---------------------------------------------------------------------------

_SPAM_FOLDER_NAMES = ["[Gmail]/Spam", "Junk", "Spam", "Bulk Mail", "INBOX.Junk", "INBOX.Spam"]


def _find_spam_folder(conn: imaplib.IMAP4 | imaplib.IMAP4_SSL) -> str | None:
    """Detect the spam/junk folder name on the server."""
    _, folders = conn.list()
    if not folders:
        return None
    folder_names = []
    for f in folders:
        if isinstance(f, bytes):
            # Parse IMAP folder list entry, e.g. b'(\\HasNoChildren) "/" "Junk"'
            decoded = f.decode("utf-8", errors="replace")
            parts = decoded.rsplit('" "', 1)
            if len(parts) == 2:
                folder_names.append(parts[1].strip('"'))
            else:
                # Try without quotes
                parts = decoded.rsplit(" ", 1)
                folder_names.append(parts[-1].strip('"'))

    for candidate in _SPAM_FOLDER_NAMES:
        if candidate in folder_names:
            return candidate
    # Try case-insensitive partial match
    for name in folder_names:
        if "spam" in name.lower() or "junk" in name.lower():
            return name
    return None


def _check_spam_sync(
    imap_host: str, imap_port: int, username: str, password: str, use_ssl: bool
) -> list[dict]:
    """Synchronously check the spam folder."""
    if use_ssl:
        conn = imaplib.IMAP4_SSL(imap_host, imap_port, timeout=30)
    else:
        conn = imaplib.IMAP4(imap_host, imap_port, timeout=30)

    conn.login(username, password)
    spam_folder = _find_spam_folder(conn)
    if not spam_folder:
        conn.logout()
        return []

    status, _ = conn.select(spam_folder, readonly=True)
    if status != "OK":
        conn.logout()
        return []

    _, msg_nums = conn.search(None, "ALL")
    message_ids = msg_nums[0].split()
    if not message_ids:
        conn.logout()
        return []

    # Only look at the last 50 messages
    message_ids = message_ids[-50:]
    emails = []
    for msg_id in message_ids:
        _, data = conn.fetch(msg_id, "(RFC822)")
        if data and data[0] and isinstance(data[0], tuple):
            parsed = _parse_email_message(data[0][1])
            parsed["uid"] = msg_id.decode()
            emails.append(parsed)

    conn.logout()
    return emails


async def check_spam_folder(account: EmailAccount) -> list[dict]:
    """Check the spam/junk folder of the given email account."""
    password = decrypt_password(account.imap_password_encrypted)
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        _check_spam_sync,
        account.imap_host,
        account.imap_port,
        account.imap_username or account.email_address,
        password,
        account.imap_use_ssl,
    )


def _move_from_spam_sync(
    imap_host: str,
    imap_port: int,
    username: str,
    password: str,
    use_ssl: bool,
    target_message_id: str,
) -> bool:
    """Move a specific email from spam to INBOX by Message-ID header."""
    if use_ssl:
        conn = imaplib.IMAP4_SSL(imap_host, imap_port, timeout=30)
    else:
        conn = imaplib.IMAP4(imap_host, imap_port, timeout=30)

    conn.login(username, password)
    spam_folder = _find_spam_folder(conn)
    if not spam_folder:
        conn.logout()
        return False

    conn.select(spam_folder)
    # Search for the message by Message-ID header
    _, msg_nums = conn.search(None, f'(HEADER Message-ID "{target_message_id}")')
    message_ids = msg_nums[0].split()
    if not message_ids:
        conn.logout()
        return False

    for msg_id in message_ids:
        conn.copy(msg_id, "INBOX")
        conn.store(msg_id, "+FLAGS", "\\Deleted")

    conn.expunge()
    conn.logout()
    return True


async def move_email_from_spam(account: EmailAccount, message_id: str) -> bool:
    """Move an email from spam to inbox, identified by Message-ID header."""
    password = decrypt_password(account.imap_password_encrypted)
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        _move_from_spam_sync,
        account.imap_host,
        account.imap_port,
        account.imap_username or account.email_address,
        password,
        account.imap_use_ssl,
        message_id,
    )


# ---------------------------------------------------------------------------
# Connection health check
# ---------------------------------------------------------------------------


async def check_connection_health(db: AsyncSession, account_id: str) -> bool:
    """Test both IMAP and SMTP connections for an account and update its status.

    Returns True if both connections are healthy.
    """
    from sqlalchemy import select as sa_select

    result = await db.execute(
        sa_select(EmailAccount).where(EmailAccount.id == account_id)
    )
    account = result.scalar_one_or_none()
    if not account:
        logger.warning("check_connection_health: account %s not found", account_id)
        return False

    imap_password = decrypt_password(account.imap_password_encrypted)
    smtp_password = decrypt_password(account.smtp_password_encrypted)

    imap_ok, imap_msg = await test_imap_connection(
        account.imap_host, account.imap_port,
        account.imap_username or account.email_address,
        imap_password, account.imap_use_ssl,
    )
    smtp_ok, smtp_msg = await test_smtp_connection(
        account.smtp_host, account.smtp_port,
        account.smtp_username or account.email_address,
        smtp_password, account.smtp_use_tls,
    )

    both_ok = imap_ok and smtp_ok
    new_status = ConnectionStatus.CONNECTED if both_ok else ConnectionStatus.ERROR
    error_message = None
    if not both_ok:
        parts = []
        if not imap_ok:
            parts.append(f"IMAP: {imap_msg}")
        if not smtp_ok:
            parts.append(f"SMTP: {smtp_msg}")
        error_message = "; ".join(parts)

    await db.execute(
        update(EmailAccount)
        .where(EmailAccount.id == account_id)
        .values(
            connection_status=new_status,
            connection_error_message=error_message,
            last_connection_check_at=datetime.now(timezone.utc),
        )
    )
    await db.flush()

    logger.info(
        "Connection health for %s: %s (IMAP: %s, SMTP: %s)",
        account.email_address, new_status.value, imap_msg, smtp_msg,
    )
    return both_ok
