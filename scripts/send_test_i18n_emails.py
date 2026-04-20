"""
Send test emails in both Swedish and English to verify translations.
Usage: python -m scripts.send_test_i18n_emails
"""

import asyncio
import sys

import httpx

from app.config import settings
from app.email.templates import (
    build_password_reset_email,
    build_verification_email,
    build_site_published_email,
    build_trial_ending_email,
    build_site_paused_email,
    build_site_deletion_warning_email,
    build_ticket_created_email,
    build_site_deletion_email,
)

RESEND_API_URL = "https://api.resend.com"
RECIPIENT = "william.soderstrom30@gmail.com"


async def send_email(to: str, subject: str, html: str, text: str) -> str:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{RESEND_API_URL}/emails",
            headers={
                "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": f"{settings.RESEND_FROM_NAME} <{settings.RESEND_FROM_EMAIL}>",
                "to": [to],
                "subject": subject,
                "html": html,
                "text": text,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["id"]


async def main():
    if not settings.RESEND_API_KEY:
        print("ERROR: RESEND_API_KEY is not set in .env")
        sys.exit(1)

    print(f"Sending i18n test emails to: {RECIPIENT}")
    print(f"From: {settings.RESEND_FROM_NAME} <{settings.RESEND_FROM_EMAIL}>")
    print()

    DASH = "https://qvicko.com/dashboard"
    n = 0

    # --- SWEDISH templates ---

    n += 1
    subject, html, text = build_verification_email(
        verify_url="https://qvicko.com/verify-email?token=test-sv",
        user_name="William",
        locale="sv",
    )
    msg_id = await send_email(RECIPIENT, f"[TEST SV] {subject}", html, text)
    print(f"{n}.  SV  Verification             sent (id={msg_id})")

    n += 1
    subject, html, text = build_trial_ending_email(
        user_name="William",
        business_name="Testforetaget AB",
        days_left=5,
        dashboard_url=DASH,
        locale="sv",
    )
    msg_id = await send_email(RECIPIENT, f"[TEST SV] {subject}", html, text)
    print(f"{n}.  SV  Trial ending              sent (id={msg_id})")

    n += 1
    subject, html, text = build_site_deletion_warning_email(
        user_name="William",
        business_name="Testforetaget AB",
        days_until_deletion=3,
        dashboard_url=DASH,
        locale="sv",
    )
    msg_id = await send_email(RECIPIENT, f"[TEST SV] {subject}", html, text)
    print(f"{n}.  SV  Deletion warning          sent (id={msg_id})")

    n += 1
    subject, html, text = build_ticket_created_email(
        user_name="William",
        ticket_subject="Problem med domankoppling",
        dashboard_url=DASH,
        locale="sv",
    )
    msg_id = await send_email(RECIPIENT, f"[TEST SV] {subject}", html, text)
    print(f"{n}.  SV  Ticket created            sent (id={msg_id})")

    # --- ENGLISH templates ---

    n += 1
    subject, html, text = build_verification_email(
        verify_url="https://qvicko.com/verify-email?token=test-en",
        user_name="William",
        locale="en",
    )
    msg_id = await send_email(RECIPIENT, f"[TEST EN] {subject}", html, text)
    print(f"{n}.  EN  Verification             sent (id={msg_id})")

    n += 1
    subject, html, text = build_trial_ending_email(
        user_name="William",
        business_name="Testforetaget AB",
        days_left=5,
        dashboard_url=DASH,
        locale="en",
    )
    msg_id = await send_email(RECIPIENT, f"[TEST EN] {subject}", html, text)
    print(f"{n}.  EN  Trial ending              sent (id={msg_id})")

    n += 1
    subject, html, text = build_site_deletion_warning_email(
        user_name="William",
        business_name="Testforetaget AB",
        days_until_deletion=3,
        dashboard_url=DASH,
        locale="en",
    )
    msg_id = await send_email(RECIPIENT, f"[TEST EN] {subject}", html, text)
    print(f"{n}.  EN  Deletion warning          sent (id={msg_id})")

    n += 1
    subject, html, text = build_ticket_created_email(
        user_name="William",
        ticket_subject="Problem with domain connection",
        dashboard_url=DASH,
        locale="en",
    )
    msg_id = await send_email(RECIPIENT, f"[TEST EN] {subject}", html, text)
    print(f"{n}.  EN  Ticket created            sent (id={msg_id})")

    print()
    print(f"Done! {n} emails sent (4 SV + 4 EN). Check your inbox.")


if __name__ == "__main__":
    asyncio.run(main())
