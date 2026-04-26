"""
Database reset script:
1. Dump counts from all tables across all schemas (easyprocess, autoblogger, feyra)
2. Delete all user-generated data (users, sites, leads, etc.)
3. Keep system data (apps, industries, smartlead config, platform_settings)
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

from sqlalchemy import text
from app.database import get_db_session, SCHEMA

# ─── easyprocess schema ─────────────────────────────────────────────────────

# All user-data tables in dependency order (children first for safe deletion)
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
    # Bookings & payments (apps)
    "platform_payments",
    "bookings",
    "booking_form_fields",
    "booking_services",
    "booking_payment_methods",
    "connected_accounts",
    # Sites & leads
    "generated_sites",
    "leads",
    "domain_purchases",
    "custom_domains",
    # OAuth
    "oauth_access_tokens",
    "oauth_authorization_codes",
    # GSC
    "gsc_connections",
    # Tracking & analytics
    "tracking_events",
    # Support
    "support_tickets",
    # Media
    "media_files",
    # Audit & auth
    "settings_audit_logs",
    "superuser_promotions",
    "audit_logs",
    "password_reset_tokens",
    "email_verification_tokens",
    "social_accounts",
    "sessions",
    # Billing
    "payments",
    "subscriptions",
    "billing_details",
    # Users last (everything depends on them)
    "users",
]

# System tables to keep (catalog data, not user data)
SYSTEM_TABLES = [
    "apps",
    "industries",
    "smartlead_campaigns",
    "smartlead_email_accounts",
    "platform_settings",
]

ALL_EASYPROCESS_TABLES = USER_DATA_TABLES + SYSTEM_TABLES

# ─── autoblogger schema ─────────────────────────────────────────────────────

AUTOBLOGGER_SCHEMA = "autoblogger"
AUTOBLOGGER_TABLES = [
    # Leaf tables first
    "credit_transactions",
    "analytics_events",
    "notifications",
    "blog_posts",
    "content_schedules",
    "sources",
    "training_profiles",
    "user_settings",
    "payments",
    "subscriptions",
    "credit_balances",
    # Auth tables
    "ab_audit_logs",
    "ab_social_accounts",
    "ab_password_reset_tokens",
    "ab_email_verification_tokens",
    "ab_sessions",
    "ab_users",
]

# ─── feyra schema ───────────────────────────────────────────────────────────

FEYRA_SCHEMA = "feyra"
FEYRA_TABLES = [
    # Leaf tables first
    "sent_emails",
    "campaign_leads",
    "campaign_steps",
    "campaigns",
    "crawl_results",
    "crawl_jobs",
    "leads",
    "warmup_emails",
    "warmup_settings",
    "email_accounts",
    "global_settings",
    # Auth tables
    "feyra_audit_logs",
    "feyra_social_accounts",
    "feyra_password_reset_tokens",
    "feyra_email_verification_tokens",
    "feyra_sessions",
    "feyra_users",
]


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def dump_schema_counts(schema: str, tables: list[str], system_tables: list[str] | None = None) -> None:
    """Print row counts for all tables in a schema."""
    system_tables = system_tables or []
    print(f"\n{'=' * 60}")
    print(f"TABLE ROW COUNTS — {schema}")
    print(f"{'=' * 60}")
    for table in tables:
        try:
            async with get_db_session() as db:
                result = await db.execute(text(f"SELECT COUNT(*) FROM {schema}.{table}"))
                count = result.scalar()
                marker = " [KEEP]" if table in system_tables else " [will delete]"
                print(f"  {table:45s} {count:>6d}{marker}")
        except Exception:
            print(f"  {table:45s} MISSING")
    print()


async def delete_schema_data(schema: str, tables: list[str]) -> None:
    """Delete all data from the given tables in a schema."""
    print(f"{'=' * 60}")
    print(f"DELETING DATA — {schema}")
    print(f"{'=' * 60}")
    for table in tables:
        try:
            async with get_db_session() as db:
                result = await db.execute(text(f"DELETE FROM {schema}.{table}"))
                print(f"  Deleted {result.rowcount:>5d} rows from {schema}.{table}")
        except Exception as e:
            print(f"  SKIP {schema}.{table} (not found or error: {e})")
    print()


async def dump_user_data(db) -> None:
    """Print summary of key user data before deletion."""
    print("=" * 60)
    print("USER DATA SUMMARY (easyprocess)")
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

    # AutoBlogger users
    try:
        result = await db.execute(text(f"SELECT COUNT(*) FROM {AUTOBLOGGER_SCHEMA}.ab_users"))
        count = result.scalar()
        print(f"\n--- AutoBlogger Users: {count} ---")
    except Exception:
        print(f"\n--- AutoBlogger schema not present ---")

    # Feyra users
    try:
        result = await db.execute(text(f"SELECT COUNT(*) FROM {FEYRA_SCHEMA}.feyra_users"))
        count = result.scalar()
        print(f"\n--- Feyra Users: {count} ---")
    except Exception:
        print(f"\n--- Feyra schema not present ---")

    print()


# ─── Review seed data ───────────────────────────────────────────────────────

BLOG_REVIEWS = [
    {"rating": 5, "title": "Perfekt for min verksamhet", "body": "Bloggen var superenkel att satta upp. Har redan fatt fler kunder via Google tack vare artiklarna jag publicerat.", "locale": "sv", "name": "Anna Lindqvist"},
    {"rating": 5, "title": "Basta bloggverktyget", "body": "Jag testar olika plattformar hela tiden och det har ar det enklaste jag anvant. Kategorier, SEO, allt fungerar direkt.", "locale": "sv", "name": "Erik Johansson"},
    {"rating": 4, "title": "Riktigt bra, vill ha fler mallar", "body": "Allt funkar bra men jag hoppas pa fler designmallar for blogginlaggen i framtiden. Annars toppen!", "locale": "sv", "name": "Sofia Bergstrom"},
    {"rating": 5, "title": "Okade min synlighet online", "body": "Sedan jag borjade blogga har mina sidvisningar okat med 40%. Valdigt nojd.", "locale": "sv", "name": "Lars Nilsson"},
    {"rating": 4, "title": "Enkelt och smidigt", "body": "Fungerar precis som det ska. Publicerade mitt forsta inlagg pa under 5 minuter.", "locale": "sv", "name": "Maria Andersson"},
    {"rating": 5, "title": "Great for SEO", "body": "Started publishing weekly articles and my organic traffic has doubled. The category system keeps everything organized.", "locale": "en", "name": "James Mitchell"},
    {"rating": 5, "title": "Couldn't be easier", "body": "As someone who's not tech-savvy, this blog tool is a godsend. Write, click publish, done.", "locale": "en", "name": "Sarah Thompson"},
    {"rating": 4, "title": "Solid blogging platform", "body": "Does everything I need. Would love to see scheduled publishing in a future update.", "locale": "en", "name": "David Chen"},
    {"rating": 5, "title": "Fantastiskt verktyg", "body": "Mina kunder hittar mig nu via bloggen. Helt otroligt vad skillnad det gor att ha innehall pa sidan.", "locale": "sv", "name": "Karin Ek"},
    {"rating": 5, "title": "Mycket nojd", "body": "Har provat andra losningar men inget slar hur smidigt det ar har. Rekommenderar starkt.", "locale": "sv", "name": "Oscar Holm"},
    {"rating": 4, "title": "Good but could use image optimization", "body": "The blog works great overall. Images could load faster though - maybe add automatic compression?", "locale": "en", "name": "Emily Watson"},
    {"rating": 5, "title": "Suverant for hantverkare", "body": "Som elektriker kan jag nu dela tips och guider. Kunderna alskar det och jag far fler forfragningar.", "locale": "sv", "name": "Peter Svensson"},
]

CHAT_REVIEWS = [
    {"rating": 5, "title": "Fangar leads direkt", "body": "Har fatt 3 nya kunder den forsta veckan tack vare chatten. Besokare skriver direkt istallet for att ringa.", "locale": "sv", "name": "Johan Karlsson"},
    {"rating": 5, "title": "Otroligt smidigt", "body": "Far notiser direkt nar nagon skriver. Kan svara fran mobilen via dashboarden. Perfekt!", "locale": "sv", "name": "Lisa Eriksson"},
    {"rating": 4, "title": "Bra chatt men saknar autosvar", "body": "Fungerar jattebra men det hade varit toppen med automatiska svar utanfor arbetstid.", "locale": "sv", "name": "Henrik Gustafsson"},
    {"rating": 5, "title": "Game changer", "body": "My conversion rate went up significantly after adding the chat widget. Visitors feel more comfortable reaching out.", "locale": "en", "name": "Michael Brown"},
    {"rating": 5, "title": "Enkel att installera", "body": "Bara att klicka installera och chatten dok upp pa sidan. Inga krangliga installningar.", "locale": "sv", "name": "Emma Lund"},
    {"rating": 4, "title": "Works well for small business", "body": "Simple and effective. Would be nice to have typing indicators and read receipts.", "locale": "en", "name": "Rachel Green"},
    {"rating": 5, "title": "Mina kunder alskar det", "body": "Folk skriver i chatten istallet for att mejla. Snabbare svar = nojdare kunder.", "locale": "sv", "name": "Anders Olsson"},
    {"rating": 5, "title": "Best live chat for the price", "body": "Free and works perfectly. Getting email notifications for new conversations is a huge plus.", "locale": "en", "name": "Tom Wilson"},
    {"rating": 5, "title": "Perfekt for min frisorssalong", "body": "Kunderna bokar via chatten nu. Mycket smidigare an telefon.", "locale": "sv", "name": "Frida Nordin"},
    {"rating": 4, "title": "Bra start", "body": "Grundfunktionerna ar pa plats. Ser fram emot fildelning och chatthistorik for besokare.", "locale": "sv", "name": "Niklas Bjork"},
    {"rating": 5, "title": "Exactly what I needed", "body": "No bloat, no unnecessary features. Just a clean chat widget that works. Love it.", "locale": "en", "name": "Alex Turner"},
    {"rating": 5, "title": "Okat fortroendet hos besokare", "body": "En chattbubbla gor att sidan kanns mer professionell och tillganglig. Bra jobbat!", "locale": "sv", "name": "Maja Lindgren"},
]


async def seed_reviews(db) -> None:
    """Seed reviews for Blog and Chat apps using fake reviewer users/sites."""
    print("=" * 60)
    print("SEEDING REVIEWS")
    print("=" * 60)

    # Get app IDs
    result = await db.execute(text(f"SELECT id, slug FROM {SCHEMA}.apps WHERE slug IN ('blog', 'chat')"))
    apps = {row.slug: row.id for row in result.fetchall()}

    if "blog" not in apps or "chat" not in apps:
        print("  WARNING: Blog or Chat app not found. Skipping review seeding.")
        print("  (Run seed_app_i18n.py first if you need reviews.)")
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
    """Print final state of all schemas."""
    print("=" * 60)
    print("FINAL STATE")
    print("=" * 60)

    for schema, tables in [
        (SCHEMA, ALL_EASYPROCESS_TABLES),
        (AUTOBLOGGER_SCHEMA, AUTOBLOGGER_TABLES),
        (FEYRA_SCHEMA, FEYRA_TABLES),
    ]:
        has_data = False
        for table in tables:
            try:
                async with get_db_session() as db:
                    result = await db.execute(text(f"SELECT COUNT(*) FROM {schema}.{table}"))
                    count = result.scalar()
                    if count > 0:
                        if not has_data:
                            print(f"\n  [{schema}]")
                            has_data = True
                        print(f"    {table:45s} {count:>6d}")
            except Exception:
                pass
        if not has_data:
            print(f"\n  [{schema}] all tables empty")
    print()


async def main() -> None:
    print("\n" + "#" * 60)
    print("# DATABASE RESET & SEED SCRIPT")
    print("# Schemas: easyprocess, autoblogger, feyra")
    print("#" * 60)

    # Step 1: Dump current state
    await dump_schema_counts(SCHEMA, ALL_EASYPROCESS_TABLES, SYSTEM_TABLES)
    await dump_schema_counts(AUTOBLOGGER_SCHEMA, AUTOBLOGGER_TABLES)
    await dump_schema_counts(FEYRA_SCHEMA, FEYRA_TABLES)

    async with get_db_session() as db:
        await dump_user_data(db)

    # Step 2: Confirm
    print("=" * 60)
    print("WARNING: This will DELETE all user data across all 3 schemas!")
    print("System tables (apps, industries, smartlead, platform_settings) will be kept.")
    print("=" * 60)
    confirm = input("Type 'yes' to continue: ").strip().lower()
    if confirm != "yes":
        print("Aborted.")
        return

    # Step 3: Delete all user data (all schemas)
    await delete_schema_data(FEYRA_SCHEMA, FEYRA_TABLES)
    await delete_schema_data(AUTOBLOGGER_SCHEMA, AUTOBLOGGER_TABLES)
    await delete_schema_data(SCHEMA, USER_DATA_TABLES)

    # Step 4: Seed reviews
    async with get_db_session() as db:
        await seed_reviews(db)

    # Step 5: Verify
    await verify_final_state()

    print("Done! Database is clean with seeded reviews.")
    print("All 3 schemas (easyprocess, autoblogger, feyra) have been reset.")


if __name__ == "__main__":
    asyncio.run(main())
