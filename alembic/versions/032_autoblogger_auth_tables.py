"""Add AutoBlogger auth tables.

Creates authentication tables (users, sessions, audit logs, social accounts,
password reset tokens, email verification tokens) in the 'autoblogger' schema.

Revision ID: 032_autoblogger_auth_tables
Revises: 031_feyra_auth_tables
Create Date: 2026-04-26
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM

revision = "032_autoblogger_auth_tables"
down_revision = "031_feyra_auth_tables"
branch_labels = None
depends_on = None

SCHEMA = "autoblogger"


def upgrade() -> None:
    # ── 1. Create enum types via raw SQL (IF NOT EXISTS) ────────────────
    op.execute(
        "DO $$ BEGIN CREATE TYPE autoblogger.ab_user_role "
        "AS ENUM ('USER', 'ADMIN'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
    )
    op.execute(
        "DO $$ BEGIN CREATE TYPE autoblogger.ab_audit_event_type AS ENUM ("
        "'LOGIN', 'LOGIN_FAILED', 'LOGOUT', 'REGISTER', "
        "'PASSWORD_CHANGE', 'PASSWORD_RESET_REQUEST', 'PASSWORD_RESET_COMPLETE', "
        "'EMAIL_CHANGE', 'TWO_FACTOR_ENABLE', 'TWO_FACTOR_DISABLE', "
        "'TWO_FACTOR_VERIFY', 'TWO_FACTOR_FAILED', "
        "'ACCOUNT_LOCKED', 'ACCOUNT_UNLOCKED', "
        "'ACCOUNT_DEACTIVATED', 'ACCOUNT_REACTIVATED', "
        "'SESSION_REVOKED', 'SOCIAL_ACCOUNT_LINKED', 'SOCIAL_ACCOUNT_UNLINKED', "
        "'EMAIL_VERIFICATION_SENT', 'EMAIL_VERIFIED', 'PROFILE_UPDATE'"
        "); EXCEPTION WHEN duplicate_object THEN NULL; END $$"
    )
    op.execute(
        "DO $$ BEGIN CREATE TYPE autoblogger.ab_social_provider "
        "AS ENUM ('GOOGLE', 'APPLE', 'FACEBOOK', 'GITHUB'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
    )

    # Reference enums with PG_ENUM + create_type=False to prevent duplicate creation
    ab_userrole = PG_ENUM(
        "USER", "ADMIN",
        name="ab_user_role", schema=SCHEMA, create_type=False,
    )
    ab_auditeventtype = PG_ENUM(
        "LOGIN", "LOGIN_FAILED", "LOGOUT", "REGISTER",
        "PASSWORD_CHANGE", "PASSWORD_RESET_REQUEST", "PASSWORD_RESET_COMPLETE",
        "EMAIL_CHANGE", "TWO_FACTOR_ENABLE", "TWO_FACTOR_DISABLE",
        "TWO_FACTOR_VERIFY", "TWO_FACTOR_FAILED",
        "ACCOUNT_LOCKED", "ACCOUNT_UNLOCKED",
        "ACCOUNT_DEACTIVATED", "ACCOUNT_REACTIVATED",
        "SESSION_REVOKED", "SOCIAL_ACCOUNT_LINKED", "SOCIAL_ACCOUNT_UNLINKED",
        "EMAIL_VERIFICATION_SENT", "EMAIL_VERIFIED", "PROFILE_UPDATE",
        name="ab_audit_event_type", schema=SCHEMA, create_type=False,
    )
    ab_socialprovider = PG_ENUM(
        "GOOGLE", "APPLE", "FACEBOOK", "GITHUB",
        name="ab_social_provider", schema=SCHEMA, create_type=False,
    )

    # ── 2. Create auth tables ──────────────────────────────────────────

    # 2a. ab_users
    op.create_table(
        "ab_users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("company_name", sa.String(255), nullable=True),
        sa.Column("org_number", sa.String(50), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("avatar_url", sa.String(500), nullable=True),
        sa.Column("locale", sa.String(10), nullable=False, server_default="sv"),
        sa.Column("role", ab_userrole, nullable=False, server_default="USER"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("two_factor_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("two_factor_secret", sa.String(255), nullable=True),
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stripe_customer_id", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("idx_abu_email", "ab_users", ["email"], schema=SCHEMA)

    # 2b. ab_sessions
    op.create_table(
        "ab_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.ab_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("device_info", sa.JSON(), nullable=True),
        sa.Column("device_fingerprint", sa.String(64), nullable=True),
        sa.Column("is_trusted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("master_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("idx_abs_user_id", "ab_sessions", ["user_id"], schema=SCHEMA)
    op.create_index("idx_abs_token_hash", "ab_sessions", ["token_hash"], schema=SCHEMA)
    op.create_index("idx_abs_device_fingerprint", "ab_sessions", ["device_fingerprint"], schema=SCHEMA)
    op.create_index("idx_abs_expires_at", "ab_sessions", ["expires_at"], schema=SCHEMA)

    # 2c. ab_audit_logs
    op.create_table(
        "ab_audit_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.ab_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_type", ab_auditeventtype, nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("idx_abal_user_id", "ab_audit_logs", ["user_id"], schema=SCHEMA)
    op.create_index("idx_abal_event_type", "ab_audit_logs", ["event_type"], schema=SCHEMA)
    op.create_index("idx_abal_created_at", "ab_audit_logs", ["created_at"], schema=SCHEMA)

    # 2d. ab_social_accounts
    op.create_table(
        "ab_social_accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.ab_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", ab_socialprovider, nullable=False),
        sa.Column("provider_user_id", sa.String(255), nullable=False),
        sa.Column("provider_email", sa.String(255), nullable=True),
        sa.Column("provider_data", sa.JSON(), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider", "provider_user_id", name="uq_absa_provider_provider_user_id"),
        schema=SCHEMA,
    )
    op.create_index("idx_absa_user_id", "ab_social_accounts", ["user_id"], schema=SCHEMA)

    # 2e. ab_password_reset_tokens
    op.create_table(
        "ab_password_reset_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.ab_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )

    # 2f. ab_email_verification_tokens
    op.create_table(
        "ab_email_verification_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.ab_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )


def downgrade() -> None:
    # ── 1. Drop auth tables (reverse order of creation) ───────────────
    op.drop_table("ab_email_verification_tokens", schema=SCHEMA)
    op.drop_table("ab_password_reset_tokens", schema=SCHEMA)
    op.drop_table("ab_social_accounts", schema=SCHEMA)
    op.drop_table("ab_audit_logs", schema=SCHEMA)
    op.drop_table("ab_sessions", schema=SCHEMA)
    op.drop_table("ab_users", schema=SCHEMA)

    # ── 2. Drop enum types ────────────────────────────────────────────
    for enum_name in ["ab_social_provider", "ab_audit_event_type", "ab_user_role"]:
        sa.Enum(name=enum_name, schema=SCHEMA).drop(op.get_bind(), checkfirst=True)
