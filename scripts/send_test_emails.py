"""
Send test emails for all templates to verify they render correctly.
Usage: python -m scripts.send_test_emails <recipient_email>
"""

import asyncio
import sys

import httpx

from app.config import settings
from app.email.templates import (
    build_outreach_email,
    build_password_reset_email,
    build_verification_email,
    build_site_published_email,
    build_trial_ending_email,
    build_site_paused_email,
    build_site_deletion_warning_email,
    build_site_deleted_email,
    build_payment_method_added_email,
)

RESEND_API_URL = "https://api.resend.com"


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
    recipient = sys.argv[1] if len(sys.argv) > 1 else "william.soderstrom30@gmail.com"

    if not settings.RESEND_API_KEY:
        print("ERROR: RESEND_API_KEY is not set in .env")
        sys.exit(1)

    print(f"Sending test emails to: {recipient}")
    print(f"From: {settings.RESEND_FROM_NAME} <{settings.RESEND_FROM_EMAIL}>")
    print()

    DASH = "https://qvicko.com/dashboard"

    # 1. Outreach email (plain text style)
    subject, html, text = build_outreach_email(
        business_name="Testföretaget AB",
        demo_url="https://qvicko.com/sites/demo-123",
        from_name="William på Qvicko",
    )
    subject = f"[TEST] {subject}"
    msg_id = await send_email(recipient, subject, html, text)
    print(f"1/9  Outreach (plain text)       sent (id={msg_id})")

    # 2. Password reset
    subject, html, text = build_password_reset_email(
        reset_url="https://qvicko.com/reset-password?token=test-abc123",
        user_name="William",
    )
    subject = f"[TEST] {subject}"
    msg_id = await send_email(recipient, subject, html, text)
    print(f"2/9  Password reset              sent (id={msg_id})")

    # 3. Email verification
    subject, html, text = build_verification_email(
        verify_url="https://qvicko.com/verify-email?token=test-xyz789",
        user_name="William",
    )
    subject = f"[TEST] {subject}"
    msg_id = await send_email(recipient, subject, html, text)
    print(f"3/9  Email verification          sent (id={msg_id})")

    # 4. Site published
    subject, html, text = build_site_published_email(
        user_name="William",
        business_name="Testföretaget AB",
        site_url="https://testforetaget.qvicko.com",
        dashboard_url=DASH,
    )
    subject = f"[TEST] {subject}"
    msg_id = await send_email(recipient, subject, html, text)
    print(f"4/9  Site published              sent (id={msg_id})")

    # 5. Trial ending soon
    subject, html, text = build_trial_ending_email(
        user_name="William",
        business_name="Testföretaget AB",
        days_left=5,
        dashboard_url=DASH,
    )
    subject = f"[TEST] {subject}"
    msg_id = await send_email(recipient, subject, html, text)
    print(f"5/9  Trial ending (5 days)       sent (id={msg_id})")

    # 6. Site paused
    subject, html, text = build_site_paused_email(
        user_name="William",
        business_name="Testföretaget AB",
        days_until_deletion=15,
        dashboard_url=DASH,
    )
    subject = f"[TEST] {subject}"
    msg_id = await send_email(recipient, subject, html, text)
    print(f"6/9  Site paused                 sent (id={msg_id})")

    # 7. Deletion warning
    subject, html, text = build_site_deletion_warning_email(
        user_name="William",
        business_name="Testföretaget AB",
        days_until_deletion=3,
        dashboard_url=DASH,
    )
    subject = f"[TEST] {subject}"
    msg_id = await send_email(recipient, subject, html, text)
    print(f"7/9  Deletion warning (3 days)   sent (id={msg_id})")

    # 8. Site deleted
    subject, html, text = build_site_deleted_email(
        user_name="William",
        business_name="Testföretaget AB",
    )
    subject = f"[TEST] {subject}"
    msg_id = await send_email(recipient, subject, html, text)
    print(f"8/9  Site deleted                sent (id={msg_id})")

    # 9. Payment method added
    subject, html, text = build_payment_method_added_email(
        user_name="William",
        business_name="Testföretaget AB",
        dashboard_url=DASH,
    )
    subject = f"[TEST] {subject}"
    msg_id = await send_email(recipient, subject, html, text)
    print(f"9/9  Payment method added        sent (id={msg_id})")

    print()
    print("All 9 test emails sent! Check your inbox.")


if __name__ == "__main__":
    asyncio.run(main())
