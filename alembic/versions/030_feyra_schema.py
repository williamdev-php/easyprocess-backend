"""Create Feyra schema tables.

Creates all tables for the Feyra email warmup, lead generation & cold outreach
platform in the 'feyra' schema. The schema itself is created at app startup in
main.py; this migration handles table creation via Alembic.

Revision ID: 030_feyra_schema
Revises: 029_autoblogger_schema
Create Date: 2026-04-25
"""

from alembic import op
import sqlalchemy as sa

revision = "030_feyra_schema"
down_revision = "029_autoblogger_schema"
branch_labels = None
depends_on = None

SCHEMA = "feyra"


def upgrade() -> None:
    # ── Create schema ───────────────────────────────────────────────────
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    # ── Enums ───────────────────────────────────────────────────────────
    emailprovider = sa.Enum(
        "GMAIL", "OUTLOOK", "YAHOO", "CUSTOM",
        name="emailprovider", schema=SCHEMA, create_type=True,
    )
    connectionstatus = sa.Enum(
        "PENDING", "CONNECTED", "ERROR", "DISCONNECTED",
        name="connectionstatus", schema=SCHEMA, create_type=True,
    )
    warmupstatus = sa.Enum(
        "IDLE", "WARMING", "READY", "PAUSED",
        name="warmupstatus", schema=SCHEMA, create_type=True,
    )
    warmupemaildirection = sa.Enum(
        "SENT", "RECEIVED",
        name="warmupemaildirection", schema=SCHEMA, create_type=True,
    )
    warmupemailstatus = sa.Enum(
        "SENT", "DELIVERED", "OPENED", "REPLIED", "BOUNCED", "SPAM",
        name="warmupemailstatus", schema=SCHEMA, create_type=True,
    )
    companysize = sa.Enum(
        "1-10", "11-50", "51-200", "201-500", "500+",
        name="companysize", schema=SCHEMA, create_type=True,
    )
    emailverificationstatus = sa.Enum(
        "PENDING", "VALID", "INVALID", "CATCH_ALL",
        name="emailverificationstatus", schema=SCHEMA, create_type=True,
    )
    leadsource = sa.Enum(
        "CRAWL", "CSV_IMPORT", "MANUAL", "API",
        name="leadsource", schema=SCHEMA, create_type=True,
    )
    leadstatus = sa.Enum(
        "NEW", "CONTACTED", "REPLIED", "INTERESTED", "NOT_INTERESTED", "BOUNCED", "UNSUBSCRIBED",
        name="leadstatus", schema=SCHEMA, create_type=True,
    )
    crawltype = sa.Enum(
        "WEBSITE", "GOOGLE_SEARCH", "LINKEDIN_SEARCH",
        name="crawltype", schema=SCHEMA, create_type=True,
    )
    crawljobstatus = sa.Enum(
        "PENDING", "RUNNING", "PAUSED", "COMPLETED", "FAILED",
        name="crawljobstatus", schema=SCHEMA, create_type=True,
    )
    crawlresultstatus = sa.Enum(
        "PENDING", "SCRAPED", "PROCESSED", "ERROR",
        name="crawlresultstatus", schema=SCHEMA, create_type=True,
    )
    campaignstatus = sa.Enum(
        "DRAFT", "SCHEDULED", "ACTIVE", "PAUSED", "COMPLETED",
        name="campaignstatus", schema=SCHEMA, create_type=True,
    )
    aitone = sa.Enum(
        "PROFESSIONAL", "CASUAL", "FRIENDLY", "DIRECT",
        name="aitone", schema=SCHEMA, create_type=True,
    )
    campaignleadstatus = sa.Enum(
        "PENDING", "ACTIVE", "REPLIED", "BOUNCED", "UNSUBSCRIBED", "COMPLETED",
        name="campaignleadstatus", schema=SCHEMA, create_type=True,
    )
    sentemailstatus = sa.Enum(
        "QUEUED", "SENT", "DELIVERED", "OPENED", "REPLIED", "BOUNCED", "SPAM_COMPLAINT",
        name="sentemailstatus", schema=SCHEMA, create_type=True,
    )
    aimodelpreference = sa.Enum(
        "QUALITY", "BALANCED", "FAST",
        name="aimodelpreference", schema=SCHEMA, create_type=True,
    )

    # ── 1. email_accounts ───────────────────────────────────────────────
    op.create_table(
        "email_accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("easyprocess.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email_address", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("imap_host", sa.String(255), nullable=True),
        sa.Column("imap_port", sa.Integer(), nullable=True),
        sa.Column("imap_username", sa.String(255), nullable=True),
        sa.Column("imap_password_encrypted", sa.Text(), nullable=True),
        sa.Column("imap_use_ssl", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("smtp_host", sa.String(255), nullable=True),
        sa.Column("smtp_port", sa.Integer(), nullable=True),
        sa.Column("smtp_username", sa.String(255), nullable=True),
        sa.Column("smtp_password_encrypted", sa.Text(), nullable=True),
        sa.Column("smtp_use_tls", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("provider", emailprovider, nullable=False, server_default="CUSTOM"),
        sa.Column("connection_status", connectionstatus, nullable=False, server_default="PENDING"),
        sa.Column("last_connection_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("connection_error_message", sa.Text(), nullable=True),
        sa.Column("daily_send_limit", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("warmup_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("warmup_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("warmup_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sender_reputation_score", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("idx_fea_user_id", "email_accounts", ["user_id"], schema=SCHEMA)
    op.create_index("idx_fea_email_address", "email_accounts", ["email_address"], schema=SCHEMA)
    op.create_index("idx_fea_connection_status", "email_accounts", ["connection_status"], schema=SCHEMA)
    op.create_index("idx_fea_created_at", "email_accounts", ["created_at"], schema=SCHEMA)

    # ── 2. warmup_settings ──────────────────────────────────────────────
    op.create_table(
        "warmup_settings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email_account_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.email_accounts.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("daily_warmup_emails_min", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("daily_warmup_emails_max", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("ramp_up_increment_per_day", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("reply_rate_percent", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("warmup_duration_days", sa.Integer(), nullable=False, server_default="14"),
        sa.Column("schedule_start_hour", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("schedule_end_hour", sa.Integer(), nullable=False, server_default="18"),
        sa.Column("schedule_timezone", sa.String(50), nullable=False, server_default="Europe/Stockholm"),
        sa.Column("days_active", sa.JSON(), nullable=True),
        sa.Column("current_day", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", warmupstatus, nullable=False, server_default="IDLE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("idx_fws_email_account_id", "warmup_settings", ["email_account_id"], schema=SCHEMA)
    op.create_index("idx_fws_status", "warmup_settings", ["status"], schema=SCHEMA)

    # ── 3. warmup_emails ────────────────────────────────────────────────
    op.create_table(
        "warmup_emails",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("from_account_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.email_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("to_account_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.email_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subject", sa.String(500), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("message_id", sa.String(500), nullable=True),
        sa.Column("in_reply_to", sa.String(500), nullable=True),
        sa.Column("direction", warmupemaildirection, nullable=False),
        sa.Column("status", warmupemailstatus, nullable=False, server_default="SENT"),
        sa.Column("landed_in_spam", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("rescued_from_spam", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("idx_fwe_from_account_id", "warmup_emails", ["from_account_id"], schema=SCHEMA)
    op.create_index("idx_fwe_to_account_id", "warmup_emails", ["to_account_id"], schema=SCHEMA)
    op.create_index("idx_fwe_status", "warmup_emails", ["status"], schema=SCHEMA)
    op.create_index("idx_fwe_created_at", "warmup_emails", ["created_at"], schema=SCHEMA)

    # ── 4. leads ────────────────────────────────────────────────────────
    op.create_table(
        "leads",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("easyprocess.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("first_name", sa.String(255), nullable=True),
        sa.Column("last_name", sa.String(255), nullable=True),
        sa.Column("full_name", sa.String(500), nullable=True),
        sa.Column("job_title", sa.String(255), nullable=True),
        sa.Column("company_name", sa.String(255), nullable=True),
        sa.Column("company_domain", sa.String(255), nullable=True),
        sa.Column("company_size", companysize, nullable=True),
        sa.Column("industry", sa.String(255), nullable=True),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("country", sa.String(100), nullable=True),
        sa.Column("linkedin_url", sa.String(1000), nullable=True),
        sa.Column("website_url", sa.String(1000), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("email_verification_status", emailverificationstatus, nullable=False, server_default="PENDING"),
        sa.Column("lead_score", sa.Integer(), nullable=True),
        sa.Column("source", leadsource, nullable=False, server_default="MANUAL"),
        sa.Column("source_url", sa.String(1000), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", leadstatus, nullable=False, server_default="NEW"),
        sa.Column("last_contacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("idx_fl_user_id", "leads", ["user_id"], schema=SCHEMA)
    op.create_index("idx_fl_email", "leads", ["email"], schema=SCHEMA)
    op.create_index("idx_fl_status", "leads", ["status"], schema=SCHEMA)
    op.create_index("idx_fl_company_domain", "leads", ["company_domain"], schema=SCHEMA)
    op.create_index("idx_fl_created_at", "leads", ["created_at"], schema=SCHEMA)

    # ── 5. crawl_jobs ───────────────────────────────────────────────────
    op.create_table(
        "crawl_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("easyprocess.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("seed_urls", sa.JSON(), nullable=True),
        sa.Column("target_domains", sa.JSON(), nullable=True),
        sa.Column("max_pages", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("max_depth", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("crawl_type", crawltype, nullable=False, server_default="WEBSITE"),
        sa.Column("search_query", sa.String(500), nullable=True),
        sa.Column("icp_description", sa.Text(), nullable=True),
        sa.Column("status", crawljobstatus, nullable=False, server_default="PENDING"),
        sa.Column("pages_crawled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("leads_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("emails_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("idx_fcj_user_id", "crawl_jobs", ["user_id"], schema=SCHEMA)
    op.create_index("idx_fcj_status", "crawl_jobs", ["status"], schema=SCHEMA)
    op.create_index("idx_fcj_created_at", "crawl_jobs", ["created_at"], schema=SCHEMA)

    # ── 6. crawl_results ────────────────────────────────────────────────
    op.create_table(
        "crawl_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("crawl_job_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.crawl_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.String(2000), nullable=False),
        sa.Column("page_title", sa.String(500), nullable=True),
        sa.Column("emails_found", sa.JSON(), nullable=True),
        sa.Column("contacts_extracted", sa.JSON(), nullable=True),
        sa.Column("status", crawlresultstatus, nullable=False, server_default="PENDING"),
        sa.Column("http_status_code", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("crawled_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.create_index("idx_fcr_crawl_job_id", "crawl_results", ["crawl_job_id"], schema=SCHEMA)
    op.create_index("idx_fcr_status", "crawl_results", ["status"], schema=SCHEMA)

    # ── 7. campaigns ────────────────────────────────────────────────────
    op.create_table(
        "campaigns",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("easyprocess.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("email_account_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.email_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", campaignstatus, nullable=False, server_default="DRAFT"),
        sa.Column("send_start_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("send_end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("daily_send_limit", sa.Integer(), nullable=True),
        sa.Column("schedule_start_hour", sa.Integer(), nullable=True),
        sa.Column("schedule_end_hour", sa.Integer(), nullable=True),
        sa.Column("schedule_timezone", sa.String(50), nullable=True),
        sa.Column("days_active", sa.JSON(), nullable=True),
        sa.Column("delay_between_emails_min_seconds", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("delay_between_emails_max_seconds", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("stop_on_reply", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("track_opens", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("total_leads", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("emails_sent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("emails_opened", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("replies_received", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bounces", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("idx_fc_user_id", "campaigns", ["user_id"], schema=SCHEMA)
    op.create_index("idx_fc_email_account_id", "campaigns", ["email_account_id"], schema=SCHEMA)
    op.create_index("idx_fc_status", "campaigns", ["status"], schema=SCHEMA)
    op.create_index("idx_fc_created_at", "campaigns", ["created_at"], schema=SCHEMA)

    # ── 8. campaign_steps ───────────────────────────────────────────────
    op.create_table(
        "campaign_steps",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("campaign_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("delay_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("subject_template", sa.String(500), nullable=True),
        sa.Column("body_template", sa.Text(), nullable=True),
        sa.Column("ai_rewrite_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("ai_tone", aitone, nullable=True, server_default="PROFESSIONAL"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("idx_fcs_campaign_id", "campaign_steps", ["campaign_id"], schema=SCHEMA)

    # ── 9. campaign_leads ───────────────────────────────────────────────
    op.create_table(
        "campaign_leads",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("campaign_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lead_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("current_step", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", campaignleadstatus, nullable=False, server_default="PENDING"),
        sa.Column("next_send_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("idx_fcl_campaign_id", "campaign_leads", ["campaign_id"], schema=SCHEMA)
    op.create_index("idx_fcl_lead_id", "campaign_leads", ["lead_id"], schema=SCHEMA)
    op.create_index("idx_fcl_status", "campaign_leads", ["status"], schema=SCHEMA)

    # ── 10. sent_emails ─────────────────────────────────────────────────
    op.create_table(
        "sent_emails",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("campaign_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("campaign_lead_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.campaign_leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email_account_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.email_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("to_email", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("message_id", sa.String(500), nullable=True),
        sa.Column("status", sentemailstatus, nullable=False, server_default="QUEUED"),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bounced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("idx_fse_campaign_id", "sent_emails", ["campaign_id"], schema=SCHEMA)
    op.create_index("idx_fse_campaign_lead_id", "sent_emails", ["campaign_lead_id"], schema=SCHEMA)
    op.create_index("idx_fse_email_account_id", "sent_emails", ["email_account_id"], schema=SCHEMA)
    op.create_index("idx_fse_status", "sent_emails", ["status"], schema=SCHEMA)
    op.create_index("idx_fse_to_email", "sent_emails", ["to_email"], schema=SCHEMA)
    op.create_index("idx_fse_created_at", "sent_emails", ["created_at"], schema=SCHEMA)

    # ── 11. global_settings ─────────────────────────────────────────────
    op.create_table(
        "global_settings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("easyprocess.users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("default_timezone", sa.String(50), nullable=False, server_default="Europe/Stockholm"),
        sa.Column("default_sending_hours_start", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("default_sending_hours_end", sa.Integer(), nullable=False, server_default="18"),
        sa.Column("unsubscribe_text", sa.Text(), nullable=True),
        sa.Column("company_signature", sa.Text(), nullable=True),
        sa.Column("ai_model_preference", aimodelpreference, nullable=False, server_default="BALANCED"),
        sa.Column("ai_default_tone", aitone, nullable=False, server_default="PROFESSIONAL"),
        sa.Column("ai_default_language", sa.String(10), nullable=False, server_default="en"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("idx_fgs_user_id", "global_settings", ["user_id"], schema=SCHEMA)


def downgrade() -> None:
    # Drop tables in reverse order (respect FK dependencies)
    op.drop_table("global_settings", schema=SCHEMA)
    op.drop_table("sent_emails", schema=SCHEMA)
    op.drop_table("campaign_leads", schema=SCHEMA)
    op.drop_table("campaign_steps", schema=SCHEMA)
    op.drop_table("campaigns", schema=SCHEMA)
    op.drop_table("crawl_results", schema=SCHEMA)
    op.drop_table("crawl_jobs", schema=SCHEMA)
    op.drop_table("leads", schema=SCHEMA)
    op.drop_table("warmup_emails", schema=SCHEMA)
    op.drop_table("warmup_settings", schema=SCHEMA)
    op.drop_table("email_accounts", schema=SCHEMA)

    # Drop enums
    for enum_name in [
        "aimodelpreference", "sentemailstatus", "campaignleadstatus", "aitone",
        "campaignstatus", "crawlresultstatus", "crawljobstatus", "crawltype",
        "leadstatus", "leadsource", "emailverificationstatus", "companysize",
        "warmupemailstatus", "warmupemaildirection", "warmupstatus",
        "connectionstatus", "emailprovider",
    ]:
        sa.Enum(name=enum_name, schema=SCHEMA).drop(op.get_bind(), checkfirst=True)

    # Drop schema
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA}")
