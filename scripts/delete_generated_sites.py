"""
Delete all generated sites (and cascaded children: drafts, versions, page_views, etc.)
Also resets lead status back to SCRAPED so sites can be re-generated.

Run: cd backend && python -m scripts.delete_generated_sites
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import get_db_session, SCHEMA

# Tables with FK → generated_sites.id (CASCADE), deleted explicitly for visibility
CHILD_TABLES = [
    "ai_chat_messages",   # FK → ai_chat_sessions (cascade from sessions)
    "ai_chat_sessions",   # FK → generated_sites
    "site_deletion_tokens",
    "site_drafts",
    "site_versions",
    "contact_messages",
    "page_views",
    "outreach_emails",
]


async def main() -> None:
    # 1. Show current counts
    print("\n--- Current generated_sites ---")
    async with get_db_session() as db:
        result = await db.execute(text(
            f"SELECT id, subdomain, status, views, created_at "
            f"FROM {SCHEMA}.generated_sites ORDER BY created_at"
        ))
        rows = result.fetchall()
        if not rows:
            print("  No generated sites found. Nothing to delete.")
            return
        for r in rows:
            print(f"  {r.subdomain or '(no subdomain)':30s} | {r.status:12s} | views: {r.views} | {r.created_at}")
        print(f"\n  Total: {len(rows)} sites")

    # 2. Confirm (pass --yes to skip)
    if "--yes" not in sys.argv:
        confirm = input("\nDelete ALL generated sites? Type 'yes': ").strip().lower()
        if confirm != "yes":
            print("Aborted.")
            return

    # 3. Delete children first (for logging), then generated_sites
    async with get_db_session() as db:
        for table in CHILD_TABLES:
            try:
                result = await db.execute(text(f"DELETE FROM {SCHEMA}.{table}"))
                if result.rowcount:
                    print(f"  Deleted {result.rowcount:>5d} rows from {table}")
            except Exception as e:
                print(f"  Skip {table}: {e}")

        # Delete generated_sites (CASCADE handles anything we missed)
        result = await db.execute(text(f"DELETE FROM {SCHEMA}.generated_sites"))
        print(f"  Deleted {result.rowcount:>5d} rows from generated_sites")

        # Reset lead status so they can be re-generated
        result = await db.execute(text(
            f"UPDATE {SCHEMA}.leads SET status = 'SCRAPED' "
            f"WHERE status IN ('GENERATING', 'GENERATED', 'EMAIL_SENT')"
        ))
        print(f"  Reset {result.rowcount:>5d} leads back to SCRAPED")

        # Also clear custom_domains.site_id (SET NULL via FK, but be explicit)
        result = await db.execute(text(
            f"UPDATE {SCHEMA}.custom_domains SET site_id = NULL WHERE site_id IS NOT NULL"
        ))
        if result.rowcount:
            print(f"  Cleared site_id on {result.rowcount} custom_domains")

    print("\nDone! All generated sites deleted. Leads reset to SCRAPED.")


if __name__ == "__main__":
    asyncio.run(main())
