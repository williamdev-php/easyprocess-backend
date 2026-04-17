"""Add billing address fields and settings audit log table

Revision ID: 003_billing_settings_audit
Revises: 002_add_email_and_reset
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa

revision = "003_billing_settings_audit"
down_revision = "002_add_email_and_reset"
branch_labels = None
depends_on = None

SCHEMA = "easyprocess"


def upgrade() -> None:
    # --- 1. Add new audit event types to existing enum ---
    op.execute(sa.text(
        "ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS 'BILLING_ADDRESS_CHANGE'"
    ))
    op.execute(sa.text(
        "ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS 'PROFILE_UPDATE'"
    ))
    op.execute(sa.text(
        "ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS 'DOMAIN_CHANGE'"
    ))

    # --- 2. Add billing address columns to users ---
    op.add_column("users", sa.Column("billing_street", sa.String(255), nullable=True), schema=SCHEMA)
    op.add_column("users", sa.Column("billing_city", sa.String(100), nullable=True), schema=SCHEMA)
    op.add_column("users", sa.Column("billing_zip", sa.String(20), nullable=True), schema=SCHEMA)
    op.add_column("users", sa.Column("billing_country", sa.String(100), nullable=True), schema=SCHEMA)

    # --- 3. Create settings_audit_logs table ---
    op.create_table(
        "settings_audit_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36),
                  sa.ForeignKey(f"{SCHEMA}.users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_type", sa.Enum("BILLING_ADDRESS_CHANGE", "PROFILE_UPDATE", "DOMAIN_CHANGE",
                                        "LOGIN", "LOGIN_FAILED", "LOGOUT", "REGISTER",
                                        "PASSWORD_CHANGE", "PASSWORD_RESET_REQUEST",
                                        "PASSWORD_RESET_COMPLETE", "EMAIL_CHANGE",
                                        "TWO_FACTOR_ENABLE", "TWO_FACTOR_DISABLE",
                                        "TWO_FACTOR_VERIFY", "TWO_FACTOR_FAILED",
                                        "ACCOUNT_LOCKED", "ACCOUNT_UNLOCKED",
                                        "ACCOUNT_DEACTIVATED", "ACCOUNT_REACTIVATED",
                                        "SESSION_REVOKED", "SOCIAL_ACCOUNT_LINKED",
                                        "SOCIAL_ACCOUNT_UNLINKED",
                                        "EMAIL_VERIFICATION_SENT", "EMAIL_VERIFIED",
                                        name="auditeventtype",
                                        create_type=False),
                  nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=True),
        sa.Column("field_name", sa.String(100), nullable=False),
        sa.Column("old_value", sa.Text, nullable=True),
        sa.Column("new_value", sa.Text, nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema=SCHEMA,
    )

    op.create_index("idx_settings_audit_user_id", "settings_audit_logs", ["user_id"], schema=SCHEMA)
    op.create_index("idx_settings_audit_event_type", "settings_audit_logs", ["event_type"], schema=SCHEMA)
    op.create_index("idx_settings_audit_entity", "settings_audit_logs", ["entity_type", "entity_id"], schema=SCHEMA)
    op.create_index("idx_settings_audit_created_at", "settings_audit_logs", ["created_at"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_table("settings_audit_logs", schema=SCHEMA)
    op.drop_column("users", "billing_country", schema=SCHEMA)
    op.drop_column("users", "billing_zip", schema=SCHEMA)
    op.drop_column("users", "billing_city", schema=SCHEMA)
    op.drop_column("users", "billing_street", schema=SCHEMA)
