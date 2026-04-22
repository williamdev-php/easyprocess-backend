"""
Database reset script:
1. Dump counts from all tables
2. Delete all user-generated data (users, sites, leads, etc.)
3. Keep system data (apps, industries)
4. Seed reviews for Blog and Chat apps

Run: cd backend && python -m scripts.reset_and_seed
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text, select, func
from app.database import get_db_session, SCHEMA

# All tables in dependency order (children first for safe deletion)
USER_DATA_TABLES = [
    # Children / leaf tables first
    "chat_messages",
    "chat_conversations",
    "blog_posts",
    "blog_categories",
    "app_reviews",
    "app_installations",
    "notifications",
    "site_deletion_tokens",
    "site_drafts",
    "site_versions",
    "contact_messages",
    "page_views",
    "outreach_emails",
    "inbound_emails",
    "scraped_data",
    "generated_sites",
    "leads",
    "domain_purchases",
    "custom_domains",
    "tracking_events",
    "support_tickets",
    "media_files",
    "settings_audit_logs",
    "superuser_promotions",
    "audit_logs",
    "password_reset_tokens",
    "email_verification_tokens",
    "social_accounts",
    "sessions",
    "payments",
    "subscriptions",
    "billing_details",
    "users",
]

# System tables to keep
SYSTEM_TABLES = [
    "apps",
    "industries",
    "smartlead_campaigns",
    "smartlead_email_accounts",
]

ALL_TABLES = USER_DATA_TABLES + SYSTEM_TABLES

# --- Swedish review seed data ---

BLOG_REVIEWS = [
    {"rating": 5, "title": "Perfekt för min verksamhet", "body": "Bloggen var superenkel att sätta upp. Har redan fått fler kunder via Google tack vare artiklarna jag publicerat.", "locale": "sv", "name": "Anna Lindqvist"},
    {"rating": 5, "title": "Bästa bloggverktyget", "body": "Jag testar olika plattformar hela tiden och det här är det enklaste jag använt. Kategorier, SEO, allt fungerar direkt.", "locale": "sv", "name": "Erik Johansson"},
    {"rating": 4, "title": "Riktigt bra, vill ha fler mallar", "body": "Allt funkar bra men jag hoppas på fler designmallar för blogginläggen i framtiden. Annars toppen!", "locale": "sv", "name": "Sofia Bergström"},
    {"rating": 5, "title": "Ökade min synlighet online", "body": "Sedan jag började blogga har mina sidvisningar ökat med 40%. Väldigt nöjd.", "locale": "sv", "name": "Lars Nilsson"},
    {"rating": 4, "title": "Enkelt och smidigt", "body": "Fungerar precis som det ska. Publicerade mitt första inlägg på under 5 minuter.", "locale": "sv", "name": "Maria Andersson"},
    {"rating": 5, "title": "Great for SEO", "body": "Started publishing weekly articles and my organic traffic has doubled. The category system keeps everything organized.", "locale": "en", "name": "James Mitchell"},
    {"rating": 5, "title": "Couldn't be easier", "body": "As someone who's not tech-savvy, this blog tool is a godsend. Write, click publish, done.", "locale": "en", "name": "Sarah Thompson"},
    {"rating": 4, "title": "Solid blogging platform", "body": "Does everything I need. Would love to see scheduled publishing in a future update.", "locale": "en", "name": "David Chen"},
    {"rating": 5, "title": "Fantastiskt verktyg", "body": "Mina kunder hittar mig nu via bloggen. Helt otroligt vad skillnad det gör att ha innehåll på sidan.", "locale": "sv", "name": "Karin Ek"},
    {"rating": 5, "title": "Mycket nöjd", "body": "Har provat andra lösningar men inget slår hur smidigt det är här. Rekommenderar starkt.", "locale": "sv", "name": "Oscar Holm"},
    {"rating": 4, "title": "Good but could use image optimization", "body": "The blog works great overall. Images could load faster though - maybe add automatic compression?", "locale": "en", "name": "Emily Watson"},
    {"rating": 5, "title": "Suveränt för hantverkare", "body": "Som elektriker kan jag nu dela tips och guider. Kunderna älskar det och jag får fler förfrågningar.", "locale": "sv", "name": "Peter Svensson"},
]

CHAT_REVIEWS = [
    {"rating": 5, "title": "Fångar leads direkt", "body": "Har fått 3 nya kunder den första veckan tack vare chatten. Besökare skriver direkt istället för att ringa.", "locale": "sv", "name": "Johan Karlsson"},
    {"rating": 5, "title": "Otroligt smidigt", "body": "Får notiser direkt när någon skriver. Kan svara från mobilen via dashboarden. Perfekt!", "locale": "sv", "name": "Lisa Eriksson"},
    {"rating": 4, "title": "Bra chatt men saknar autosvar", "body": "Fungerar jättebra men det hade varit toppen med automatiska svar utanför arbetstid.", "locale": "sv", "name": "Henrik Gustafsson"},
    {"rating": 5, "title": "Game changer", "body": "My conversion rate went up significantly after adding the chat widget. Visitors feel more comfortable reaching out.", "locale": "en", "name": "Michael Brown"},
    {"rating": 5, "title": "Enkel att installera", "body": "Bara att klicka installera och chatten dök upp på sidan. Inga krångliga inställningar.", "locale": "sv", "name": "Emma Lund"},
    {"rating": 4, "title": "Works well for small business", "body": "Simple and effective. Would be nice to have typing indicators and read receipts.", "locale": "en", "name": "Rachel Green"},
    {"rating": 5, "title": "Mina kunder älskar det", "body": "Folk skriver i chatten istället för att mejla. Snabbare svar = nöjdare kunder.", "locale": "sv", "name": "Anders Olsson"},
    {"rating": 5, "title": "Best live chat for the price", "body": "Free and works perfectly. Getting email notifications for new conversations is a huge plus.", "locale": "en", "name": "Tom Wilson"},
    {"rating": 5, "title": "Perfekt för min frisörsalong", "body": "Kunderna bokar via chatten nu. Mycket smidigare än telefon.", "locale": "sv", "name": "Frida Nordin"},
    {"rating": 4, "title": "Bra start", "body": "Grundfunktionerna är på plats. Ser fram emot fildelning och chatthistorik för besökare.", "locale": "sv", "name": "Niklas Björk"},
    {"rating": 5, "title": "Exactly what I needed", "body": "No bloat, no unnecessary features. Just a clean chat widget that works. Love it.", "locale": "en", "name": "Alex Turner"},
    {"rating": 5, "title": "Ökat förtroendet hos besökare", "body": "En chattbubbla gör att sidan känns mer professionell och tillgänglig. Bra jobbat!", "locale": "sv", "name": "Maja Lindgren"},
]


async def dump_table_counts() -> None:
    """Print row counts for all tables (each in its own session)."""
    print("\n" + "=" * 60)
    print("TABLE ROW COUNTS (before reset)")
    print("=" * 60)
    for table in ALL_TABLES:
        try:
            async with get_db_session() as db:
                result = await db.execute(text(f"SELECT COUNT(*) FROM {SCHEMA}.{table}"))
                count = result.scalar()
                marker = "" if table in SYSTEM_TABLES else " [will delete]"
                print(f"  {table:40s} {count:>6d}{marker}")
        except Exception as e:
            print(f"  {table:40s} MISSING")
    print()


async def dump_user_data(db) -> None:
    """Print summary of key user data before deletion."""
    print("=" * 60)
    print("USER DATA SUMMARY")
    print("=" * 60)

    # Users
    try:
        result = await db.execute(text(f"SELECT id, email, full_name, role, created_at FROM {SCHEMA}.users ORDER BY created_at"))
        users = result.fetchall()
        print(f"\n--- Users ({len(users)}) ---")
        for u in users:
            print(f"  {u.email} | {u.full_name} | {u.role} | {u.created_at}")
    except Exception as e:
        print(f"  Users error: {e}")

    # Generated sites
    try:
        result = await db.execute(text(f"SELECT id, subdomain, status, views, created_at FROM {SCHEMA}.generated_sites ORDER BY created_at"))
        sites = result.fetchall()
        print(f"\n--- Generated Sites ({len(sites)}) ---")
        for s in sites:
            print(f"  {s.subdomain} | {s.status} | views: {s.views} | {s.created_at}")
    except Exception as e:
        print(f"  Generated sites error: {e}")

    # Audit logs
    try:
        result = await db.execute(text(f"SELECT event_type, COUNT(*) as cnt FROM {SCHEMA}.audit_logs GROUP BY event_type ORDER BY cnt DESC"))
        logs = result.fetchall()
        print(f"\n--- Audit Log Summary ---")
        for l in logs:
            print(f"  {l.event_type}: {l.cnt}")
    except Exception as e:
        print(f"  Audit log error: {e}")

    # Support tickets
    try:
        result = await db.execute(text(f"SELECT id, subject, status, created_at FROM {SCHEMA}.support_tickets ORDER BY created_at"))
        tickets = result.fetchall()
        print(f"\n--- Support Tickets ({len(tickets)}) ---")
        for t in tickets:
            print(f"  {t.subject} | {t.status} | {t.created_at}")
    except Exception as e:
        print(f"  Support tickets error: {e}")

    # Leads
    try:
        result = await db.execute(text(f"SELECT COUNT(*) as cnt, status FROM {SCHEMA}.leads GROUP BY status ORDER BY cnt DESC"))
        leads = result.fetchall()
        print(f"\n--- Leads by Status ---")
        for l in leads:
            print(f"  {l.status}: {l.cnt}")
    except Exception as e:
        print(f"  Leads error: {e}")

    print()


async def delete_user_data() -> None:
    """Delete all user-generated data, keeping system tables."""
    print("=" * 60)
    print("DELETING USER DATA")
    print("=" * 60)
    for table in USER_DATA_TABLES:
        try:
            async with get_db_session() as db:
                result = await db.execute(text(f"DELETE FROM {SCHEMA}.{table}"))
                print(f"  Deleted {result.rowcount:>5d} rows from {table}")
        except Exception as e:
            print(f"  SKIP {table} (not found or error)")
    print()


async def seed_reviews(db) -> None:
    """Seed reviews for Blog and Chat apps using fake reviewer users/sites."""
    print("=" * 60)
    print("SEEDING REVIEWS")
    print("=" * 60)

    # Get app IDs
    result = await db.execute(text(f"SELECT id, slug FROM {SCHEMA}.apps WHERE slug IN ('blog', 'chat')"))
    apps = {row.slug: row.id for row in result.fetchall()}

    if "blog" not in apps or "chat" not in apps:
        print("  ERROR: Blog or Chat app not found! Run seed_app_i18n.py first.")
        return

    print(f"  Blog app ID: {apps['blog']}")
    print(f"  Chat app ID: {apps['chat']}")

    # We need fake users and a fake site for FK constraints
    # Create seed reviewer users
    reviewer_ids = []
    all_reviews = BLOG_REVIEWS + CHAT_REVIEWS
    unique_names = list({r["name"] for r in all_reviews})

    for name in unique_names:
        uid = str(uuid.uuid4())
        reviewer_ids.append((uid, name))
        email = f"{name.lower().replace(' ', '.')}@review-seed.local"
        await db.execute(text(f"""
            INSERT INTO {SCHEMA}.users (id, email, password_hash, full_name, locale, role, is_active, is_verified, is_superuser, two_factor_enabled, failed_login_attempts, created_at, updated_at)
            VALUES (:id, :email, 'seed-no-login', :name, 'sv', 'USER', false, false, false, false, 0, :now, :now)
        """), {"id": uid, "email": email, "name": name, "now": datetime.now(timezone.utc)})

    # Create a dummy lead + site for FK
    lead_id = str(uuid.uuid4())
    site_id = str(uuid.uuid4())
    await db.execute(text(f"""
        INSERT INTO {SCHEMA}.leads (id, business_name, website_url, source, status, created_at, updated_at)
        VALUES (:id, 'Review Seed Lead', 'https://seed.local', 'seed', 'GENERATED', :now, :now)
    """), {"id": lead_id, "now": datetime.now(timezone.utc)})
    await db.execute(text(f"""
        INSERT INTO {SCHEMA}.generated_sites (id, lead_id, site_data, template, status, subdomain, views, viewer_version, created_at, updated_at)
        VALUES (:id, :lead_id, '{{}}'::jsonb, 'default', 'DRAFT', 'review-seed', 0, 'v1', :now, :now)
    """), {"id": site_id, "lead_id": lead_id, "now": datetime.now(timezone.utc)})

    name_to_uid = {name: uid for uid, name in reviewer_ids}

    # Insert blog reviews
    count = 0
    for i, review in enumerate(BLOG_REVIEWS):
        uid = name_to_uid[review["name"]]
        days_ago = random.randint(1, 90)
        created = datetime.now(timezone.utc) - timedelta(days=days_ago)
        await db.execute(text(f"""
            INSERT INTO {SCHEMA}.app_reviews (id, app_id, user_id, site_id, rating, title, body, locale, created_at, updated_at)
            VALUES (:id, :app_id, :user_id, :site_id, :rating, :title, :body, :locale, :created, :created)
        """), {
            "id": str(uuid.uuid4()),
            "app_id": apps["blog"],
            "user_id": uid,
            "site_id": site_id,
            "rating": review["rating"],
            "title": review["title"],
            "body": review["body"],
            "locale": review["locale"],
            "created": created,
        })
        count += 1

    print(f"  Seeded {count} reviews for Blog app")

    # Insert chat reviews
    count = 0
    for i, review in enumerate(CHAT_REVIEWS):
        uid = name_to_uid[review["name"]]
        days_ago = random.randint(1, 90)
        created = datetime.now(timezone.utc) - timedelta(days=days_ago)
        await db.execute(text(f"""
            INSERT INTO {SCHEMA}.app_reviews (id, app_id, user_id, site_id, rating, title, body, locale, created_at, updated_at)
            VALUES (:id, :app_id, :user_id, :site_id, :rating, :title, :body, :locale, :created, :created)
        """), {
            "id": str(uuid.uuid4()),
            "app_id": apps["chat"],
            "user_id": uid,
            "site_id": site_id,
            "rating": review["rating"],
            "title": review["title"],
            "body": review["body"],
            "locale": review["locale"],
            "created": created,
        })
        count += 1

    print(f"  Seeded {count} reviews for Chat app")

    # Deactivate seed users so they can't log in (password is already invalid)
    print(f"  Created {len(reviewer_ids)} seed reviewer users (inactive, no-login)")
    print()


async def verify_final_state() -> None:
    """Print final state of the database."""
    print("=" * 60)
    print("FINAL STATE")
    print("=" * 60)
    for table in ALL_TABLES:
        try:
            async with get_db_session() as db:
                result = await db.execute(text(f"SELECT COUNT(*) FROM {SCHEMA}.{table}"))
                count = result.scalar()
                if count > 0:
                    print(f"  {table:40s} {count:>6d}")
        except Exception:
            pass
    print()


async def main() -> None:
    print("\n" + "#" * 60)
    print("# DATABASE RESET & SEED SCRIPT")
    print("#" * 60)

    # Step 1: Dump current state
    await dump_table_counts()
    async with get_db_session() as db:
        await dump_user_data(db)

    # Step 2: Delete all user data
    await delete_user_data()

    # Step 3: Seed reviews
    async with get_db_session() as db:
        await seed_reviews(db)

    # Step 4: Verify
    await verify_final_state()

    print("Done! Database is clean with seeded reviews.")


if __name__ == "__main__":
    asyncio.run(main())
