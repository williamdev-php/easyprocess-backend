"""Add password reset, email verification, and inbound email tables

Revision ID: 002_add_email_and_reset
Revises: 001_autosite
Create Date: 2026-04-16
"""
from alembic import op
import sqlalchemy as sa

revision = "002_add_email_and_reset"
down_revision = "001_autosite"
branch_labels = None
depends_on = None

SCHEMA = "easyprocess"


def upgrade() -> None:
    # Add new audit event types to existing enum (in public schema)
    # NOTE: ALTER TYPE ADD VALUE cannot run inside a transaction.
    # Run manually if migration fails:
    #   ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS 'EMAIL_VERIFICATION_SENT';
    #   ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS 'EMAIL_VERIFIED';
    op.execute(sa.text(
        "ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS 'EMAIL_VERIFICATION_SENT'"
    ))
    op.execute(sa.text(
        "ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS 'EMAIL_VERIFIED'"
    ))

    # Create EmailCategory enum if not exists (may already exist from create_all)
    op.execute(sa.text(
        "DO $$ BEGIN "
        "CREATE TYPE easyprocess.emailcategory AS ENUM ('spam', 'lead_reply', 'support', 'inquiry', 'other'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$;"
    ))

    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False, index=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema=SCHEMA,
    )

    op.create_table(
        "email_verification_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False, index=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema=SCHEMA,
    )

    op.create_table(
        "inbound_emails",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("from_email", sa.String(255), nullable=False, index=True),
        sa.Column("from_name", sa.String(255), nullable=True),
        sa.Column("to_email", sa.String(255), nullable=False, index=True),
        sa.Column("subject", sa.String(500), nullable=True),
        sa.Column("body_text", sa.Text, nullable=True),
        sa.Column("body_html", sa.Text, nullable=True),
        sa.Column("category", sa.String(20), server_default="other"),
        sa.Column("spam_score", sa.Float, nullable=True),
        sa.Column("ai_summary", sa.String(500), nullable=True),
        sa.Column("matched_lead_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.leads.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("is_read", sa.Boolean, server_default=sa.text("false")),
        sa.Column("is_archived", sa.Boolean, server_default=sa.text("false")),
        sa.Column("resend_email_id", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("inbound_emails", schema=SCHEMA)
    op.drop_table("email_verification_tokens", schema=SCHEMA)
    op.drop_table("password_reset_tokens", schema=SCHEMA)
    sa.Enum(name="emailcategory", schema=SCHEMA).drop(op.get_bind(), checkfirst=True)
