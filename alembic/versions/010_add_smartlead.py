"""Add Smartlead integration: campaigns, email accounts, and outreach tracking fields.

Revision ID: 010_add_smartlead
Revises: 009_soft_delete_pause
Create Date: 2026-04-19
"""
from alembic import op
import sqlalchemy as sa

revision = "010_add_smartlead"
down_revision = "009_soft_delete_pause"
branch_labels = None
depends_on = None

SCHEMA = "easyprocess"


def _column_exists(conn, table: str, column: str) -> bool:
    result = conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns "
        f"WHERE table_schema='{SCHEMA}' AND table_name=:table "
        "AND column_name=:column"
    ), {"table": table, "column": column})
    return result.fetchone() is not None


def _table_exists(conn, table: str) -> bool:
    result = conn.execute(sa.text(
        "SELECT table_name FROM information_schema.tables "
        f"WHERE table_schema='{SCHEMA}' AND table_name=:table"
    ), {"table": table})
    return result.fetchone() is not None


def upgrade() -> None:
    conn = op.get_bind()

    # ---------------------------------------------------------------
    # 1. Create smartlead_campaigns table
    # ---------------------------------------------------------------
    if not _table_exists(conn, "smartlead_campaigns"):
        op.create_table(
            "smartlead_campaigns",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("smartlead_campaign_id", sa.Integer, unique=True, nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="DRAFTED"),
            sa.Column("sending_account_email", sa.String(255), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True),
                server_default=sa.func.now(), nullable=False,
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True),
                server_default=sa.func.now(), nullable=False,
            ),
            schema=SCHEMA,
        )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sl_campaigns_sl_id "
        f"ON {SCHEMA}.smartlead_campaigns (smartlead_campaign_id)"
    )

    # ---------------------------------------------------------------
    # 2. Create smartlead_email_accounts table
    # ---------------------------------------------------------------
    if not _table_exists(conn, "smartlead_email_accounts"):
        op.create_table(
            "smartlead_email_accounts",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("smartlead_account_id", sa.Integer, unique=True, nullable=False),
            sa.Column("email", sa.String(255), nullable=False),
            sa.Column("domain", sa.String(255), nullable=False),
            sa.Column("warmup_enabled", sa.Boolean, server_default="true", nullable=False),
            sa.Column("max_daily_sends", sa.Integer, server_default="20", nullable=False),
            sa.Column("warmup_per_day", sa.Integer, server_default="5", nullable=False),
            sa.Column("daily_rampup", sa.Integer, server_default="2", nullable=False),
            sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
            sa.Column(
                "created_at", sa.DateTime(timezone=True),
                server_default=sa.func.now(), nullable=False,
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True),
                server_default=sa.func.now(), nullable=False,
            ),
            schema=SCHEMA,
        )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sl_accounts_email "
        f"ON {SCHEMA}.smartlead_email_accounts (email)"
    )

    # ---------------------------------------------------------------
    # 3. Add Smartlead columns to outreach_emails
    # ---------------------------------------------------------------
    if not _column_exists(conn, "outreach_emails", "smartlead_campaign_id"):
        op.add_column(
            "outreach_emails",
            sa.Column("smartlead_campaign_id", sa.Integer, nullable=True),
            schema=SCHEMA,
        )

    if not _column_exists(conn, "outreach_emails", "smartlead_lead_id"):
        op.add_column(
            "outreach_emails",
            sa.Column("smartlead_lead_id", sa.Integer, nullable=True),
            schema=SCHEMA,
        )

    if not _column_exists(conn, "outreach_emails", "sent_via"):
        op.add_column(
            "outreach_emails",
            sa.Column("sent_via", sa.String(20), server_default="resend", nullable=False),
            schema=SCHEMA,
        )

    if not _column_exists(conn, "outreach_emails", "replied_at"):
        op.add_column(
            "outreach_emails",
            sa.Column("replied_at", sa.DateTime(timezone=True), nullable=True),
            schema=SCHEMA,
        )

    # ---------------------------------------------------------------
    # 4. Add REPLIED to EmailStatus and LeadStatus enums
    # ---------------------------------------------------------------
    op.execute("ALTER TYPE emailstatus ADD VALUE IF NOT EXISTS 'REPLIED'")
    op.execute("ALTER TYPE leadstatus ADD VALUE IF NOT EXISTS 'REPLIED'")

    # ---------------------------------------------------------------
    # 5. Indexes on new columns
    # ---------------------------------------------------------------
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_outreach_emails_sent_via "
        f"ON {SCHEMA}.outreach_emails (sent_via)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_outreach_emails_sl_campaign "
        f"ON {SCHEMA}.outreach_emails (smartlead_campaign_id)"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.idx_outreach_emails_sl_campaign")
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.idx_outreach_emails_sent_via")
    op.drop_column("outreach_emails", "replied_at", schema=SCHEMA)
    op.drop_column("outreach_emails", "sent_via", schema=SCHEMA)
    op.drop_column("outreach_emails", "smartlead_lead_id", schema=SCHEMA)
    op.drop_column("outreach_emails", "smartlead_campaign_id", schema=SCHEMA)
    op.drop_table("smartlead_email_accounts", schema=SCHEMA)
    op.drop_table("smartlead_campaigns", schema=SCHEMA)
