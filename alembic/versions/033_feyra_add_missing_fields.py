"""Add missing fields to Feyra schema tables.

Adds columns that services (campaign_service, warmup_service, crawl_service,
email_account_service) expect but the original migrations did not create.

Revision ID: 033_feyra_add_missing_fields
Revises: 032_autoblogger_auth_tables
Create Date: 2026-04-26
"""

from alembic import op
import sqlalchemy as sa

revision = "033_feyra_add_missing_fields"
down_revision = "032_autoblogger_auth_tables"
branch_labels = None
depends_on = None

SCHEMA = "feyra"


def upgrade() -> None:
    # ── email_accounts ─────────────────────────────────────────────────
    op.add_column(
        "email_accounts",
        sa.Column("password_encrypted", sa.Text(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "email_accounts",
        sa.Column("last_error", sa.Text(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "email_accounts",
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    # Re-use existing warmupstatus enum for the account-level warmup_status
    op.add_column(
        "email_accounts",
        sa.Column(
            "warmup_status",
            sa.Enum(
                "IDLE", "WARMING", "READY", "PAUSED",
                name="warmupstatus", schema=SCHEMA, create_type=False,
            ),
            nullable=True,
        ),
        schema=SCHEMA,
    )

    # ── warmup_settings ────────────────────────────────────────────────
    op.add_column(
        "warmup_settings",
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        schema=SCHEMA,
    )
    op.add_column(
        "warmup_settings",
        sa.Column("max_daily_volume", sa.Integer(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "warmup_settings",
        sa.Column("ramp_up_days", sa.Integer(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "warmup_settings",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )

    # ── warmup_emails ──────────────────────────────────────────────────
    op.add_column(
        "warmup_emails",
        sa.Column(
            "sender_account_id",
            sa.String(36),
            sa.ForeignKey(f"{SCHEMA}.email_accounts.id", ondelete="CASCADE"),
            nullable=True,
        ),
        schema=SCHEMA,
    )
    op.add_column(
        "warmup_emails",
        sa.Column(
            "receiver_account_id",
            sa.String(36),
            sa.ForeignKey(f"{SCHEMA}.email_accounts.id", ondelete="CASCADE"),
            nullable=True,
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_fwe_sender_account_id", "warmup_emails", ["sender_account_id"], schema=SCHEMA
    )

    # ── leads ──────────────────────────────────────────────────────────
    op.add_column(
        "leads",
        sa.Column("company", sa.String(255), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "leads",
        sa.Column("website", sa.String(1000), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "leads",
        sa.Column("city", sa.String(255), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "leads",
        sa.Column(
            "crawl_job_id",
            sa.String(36),
            sa.ForeignKey(f"{SCHEMA}.crawl_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        schema=SCHEMA,
    )

    # ── crawl_jobs ─────────────────────────────────────────────────────
    op.add_column(
        "crawl_jobs",
        sa.Column("target_url", sa.String(2000), nullable=True),
        schema=SCHEMA,
    )

    # ── crawl_results ──────────────────────────────────────────────────
    op.add_column(
        "crawl_results",
        sa.Column("contacts_found", sa.Integer(), nullable=True),
        schema=SCHEMA,
    )

    # ── campaigns ──────────────────────────────────────────────────────
    op.add_column(
        "campaigns",
        sa.Column("subject", sa.String(500), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "campaigns",
        sa.Column("tone", sa.String(50), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "campaigns",
        sa.Column("timezone", sa.String(50), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "campaigns",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )

    # ── campaign_steps ─────────────────────────────────────────────────
    op.add_column(
        "campaign_steps",
        sa.Column("subject", sa.String(500), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "campaign_steps",
        sa.Column("body_html", sa.Text(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "campaign_steps",
        sa.Column("body_text", sa.Text(), nullable=True),
        schema=SCHEMA,
    )

    # ── campaign_leads ─────────────────────────────────────────────────
    op.add_column(
        "campaign_leads",
        sa.Column("last_message_id", sa.String(500), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "campaign_leads",
        sa.Column("emails_sent", sa.Integer(), nullable=True, server_default="0"),
        schema=SCHEMA,
    )
    op.add_column(
        "campaign_leads",
        sa.Column("soft_bounce_count", sa.Integer(), nullable=True, server_default="0"),
        schema=SCHEMA,
    )

    # ── sent_emails ────────────────────────────────────────────────────
    op.add_column(
        "sent_emails",
        sa.Column(
            "campaign_step_id",
            sa.String(36),
            sa.ForeignKey(f"{SCHEMA}.campaign_steps.id", ondelete="SET NULL"),
            nullable=True,
        ),
        schema=SCHEMA,
    )
    op.add_column(
        "sent_emails",
        sa.Column(
            "lead_id",
            sa.String(36),
            sa.ForeignKey(f"{SCHEMA}.leads.id", ondelete="SET NULL"),
            nullable=True,
        ),
        schema=SCHEMA,
    )


def downgrade() -> None:
    # ── sent_emails ────────────────────────────────────────────────────
    op.drop_column("sent_emails", "lead_id", schema=SCHEMA)
    op.drop_column("sent_emails", "campaign_step_id", schema=SCHEMA)

    # ── campaign_leads ─────────────────────────────────────────────────
    op.drop_column("campaign_leads", "soft_bounce_count", schema=SCHEMA)
    op.drop_column("campaign_leads", "emails_sent", schema=SCHEMA)
    op.drop_column("campaign_leads", "last_message_id", schema=SCHEMA)

    # ── campaign_steps ─────────────────────────────────────────────────
    op.drop_column("campaign_steps", "body_text", schema=SCHEMA)
    op.drop_column("campaign_steps", "body_html", schema=SCHEMA)
    op.drop_column("campaign_steps", "subject", schema=SCHEMA)

    # ── campaigns ──────────────────────────────────────────────────────
    op.drop_column("campaigns", "started_at", schema=SCHEMA)
    op.drop_column("campaigns", "timezone", schema=SCHEMA)
    op.drop_column("campaigns", "tone", schema=SCHEMA)
    op.drop_column("campaigns", "subject", schema=SCHEMA)

    # ── crawl_results ──────────────────────────────────────────────────
    op.drop_column("crawl_results", "contacts_found", schema=SCHEMA)

    # ── crawl_jobs ─────────────────────────────────────────────────────
    op.drop_column("crawl_jobs", "target_url", schema=SCHEMA)

    # ── leads ──────────────────────────────────────────────────────────
    op.drop_column("leads", "crawl_job_id", schema=SCHEMA)
    op.drop_column("leads", "city", schema=SCHEMA)
    op.drop_column("leads", "website", schema=SCHEMA)
    op.drop_column("leads", "company", schema=SCHEMA)

    # ── warmup_emails ──────────────────────────────────────────────────
    op.drop_index("idx_fwe_sender_account_id", "warmup_emails", schema=SCHEMA)
    op.drop_column("warmup_emails", "receiver_account_id", schema=SCHEMA)
    op.drop_column("warmup_emails", "sender_account_id", schema=SCHEMA)

    # ── warmup_settings ────────────────────────────────────────────────
    op.drop_column("warmup_settings", "started_at", schema=SCHEMA)
    op.drop_column("warmup_settings", "ramp_up_days", schema=SCHEMA)
    op.drop_column("warmup_settings", "max_daily_volume", schema=SCHEMA)
    op.drop_column("warmup_settings", "enabled", schema=SCHEMA)

    # ── email_accounts ─────────────────────────────────────────────────
    op.drop_column("email_accounts", "warmup_status", schema=SCHEMA)
    op.drop_column("email_accounts", "last_checked_at", schema=SCHEMA)
    op.drop_column("email_accounts", "last_error", schema=SCHEMA)
    op.drop_column("email_accounts", "password_encrypted", schema=SCHEMA)
