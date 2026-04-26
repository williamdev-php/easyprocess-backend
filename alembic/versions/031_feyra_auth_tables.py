"""Add Feyra auth tables and update FK references.

Creates authentication tables (users, sessions, audit logs, social accounts,
password reset tokens, email verification tokens) in the 'feyra' schema, and
updates existing FK references from easyprocess.users to feyra.feyra_users.

Revision ID: 031_feyra_auth_tables
Revises: 030_feyra_schema
Create Date: 2026-04-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM

revision = "031_feyra_auth_tables"
down_revision = "030_feyra_schema"
branch_labels = None
depends_on = None

SCHEMA = "feyra"

# Tables whose user_id FK needs to be re-pointed
# (table_name, auto-generated constraint name from migration 030)
FK_TABLES = [
    ("email_accounts", "email_accounts_user_id_fkey"),
    ("leads", "leads_user_id_fkey"),
    ("crawl_jobs", "crawl_jobs_user_id_fkey"),
    ("campaigns", "campaigns_user_id_fkey"),
    ("global_settings", "global_settings_user_id_fkey"),
]


def upgrade() -> None:
    # ── 1. Create enum types via raw SQL (IF NOT EXISTS) ────────────────
    op.execute("DO $$ BEGIN CREATE TYPE feyra.feyra_user_role AS ENUM ('USER', 'ADMIN'); EXCEPTION WHEN duplicate_object THEN NULL; END $$")
    op.execute("DO $$ BEGIN CREATE TYPE feyra.feyra_audit_event_type AS ENUM ('LOGIN', 'LOGIN_FAILED', 'LOGOUT', 'REGISTER', 'PASSWORD_CHANGE', 'PASSWORD_RESET_REQUEST', 'PASSWORD_RESET_COMPLETE', 'EMAIL_CHANGE', 'ACCOUNT_LOCKED', 'ACCOUNT_UNLOCKED', 'SESSION_REVOKED', 'SOCIAL_ACCOUNT_LINKED', 'EMAIL_VERIFICATION_SENT', 'EMAIL_VERIFIED', 'PROFILE_UPDATE'); EXCEPTION WHEN duplicate_object THEN NULL; END $$")
    op.execute("DO $$ BEGIN CREATE TYPE feyra.feyra_social_provider AS ENUM ('GOOGLE', 'APPLE', 'FACEBOOK', 'GITHUB'); EXCEPTION WHEN duplicate_object THEN NULL; END $$")

    # Reference enums with PG_ENUM + create_type=False to prevent duplicate creation
    feyra_userrole = PG_ENUM("USER", "ADMIN", name="feyra_user_role", schema=SCHEMA, create_type=False)
    feyra_auditeventtype = PG_ENUM(
        "LOGIN", "LOGIN_FAILED", "LOGOUT", "REGISTER",
        "PASSWORD_CHANGE", "PASSWORD_RESET_REQUEST", "PASSWORD_RESET_COMPLETE",
        "EMAIL_CHANGE", "ACCOUNT_LOCKED", "ACCOUNT_UNLOCKED",
        "SESSION_REVOKED", "SOCIAL_ACCOUNT_LINKED",
        "EMAIL_VERIFICATION_SENT", "EMAIL_VERIFIED",
        "PROFILE_UPDATE",
        name="feyra_audit_event_type", schema=SCHEMA, create_type=False,
    )
    feyra_socialprovider = PG_ENUM("GOOGLE", "APPLE", "FACEBOOK", "GITHUB", name="feyra_social_provider", schema=SCHEMA, create_type=False)

    # ── 2. Create auth tables ──────────────────────────────────────────

    # 2a. feyra_users
    op.create_table(
        "feyra_users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("company_name", sa.String(255), nullable=True),
        sa.Column("org_number", sa.String(50), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("avatar_url", sa.String(500), nullable=True),
        sa.Column("locale", sa.String(10), nullable=False, server_default="sv"),
        sa.Column("role", feyra_userrole, nullable=False, server_default="USER"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("two_factor_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("two_factor_secret", sa.String(255), nullable=True),
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("idx_fu_email", "feyra_users", ["email"], schema=SCHEMA)

    # 2b. feyra_sessions
    op.create_table(
        "feyra_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.feyra_users.id", ondelete="CASCADE"), nullable=False),
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
    op.create_index("idx_fss_user_id", "feyra_sessions", ["user_id"], schema=SCHEMA)
    op.create_index("idx_fss_token_hash", "feyra_sessions", ["token_hash"], schema=SCHEMA)
    op.create_index("idx_fss_device_fingerprint", "feyra_sessions", ["device_fingerprint"], schema=SCHEMA)
    op.create_index("idx_fss_expires_at", "feyra_sessions", ["expires_at"], schema=SCHEMA)

    # 2c. feyra_audit_logs
    op.create_table(
        "feyra_audit_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.feyra_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_type", feyra_auditeventtype, nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("idx_fal_user_id", "feyra_audit_logs", ["user_id"], schema=SCHEMA)
    op.create_index("idx_fal_event_type", "feyra_audit_logs", ["event_type"], schema=SCHEMA)
    op.create_index("idx_fal_created_at", "feyra_audit_logs", ["created_at"], schema=SCHEMA)

    # 2d. feyra_social_accounts
    op.create_table(
        "feyra_social_accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.feyra_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", feyra_socialprovider, nullable=False),
        sa.Column("provider_user_id", sa.String(255), nullable=False),
        sa.Column("provider_email", sa.String(255), nullable=True),
        sa.Column("provider_data", sa.JSON(), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider", "provider_user_id", name="uq_fsa_provider_provider_user_id"),
        schema=SCHEMA,
    )
    op.create_index("idx_fsa_user_id", "feyra_social_accounts", ["user_id"], schema=SCHEMA)

    # 2e. feyra_password_reset_tokens
    op.create_table(
        "feyra_password_reset_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.feyra_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )

    # 2f. feyra_email_verification_tokens
    op.create_table(
        "feyra_email_verification_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.feyra_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )

    # ── 3. Update FK references on existing feyra tables ───────────────
    # Drop old FKs pointing to easyprocess.users.id, create new ones
    # pointing to feyra.feyra_users.id.
    for table_name, old_fk_name in FK_TABLES:
        op.drop_constraint(old_fk_name, table_name, schema=SCHEMA, type_="foreignkey")
        op.create_foreign_key(
            f"{table_name}_user_id_feyra_users_fkey",
            table_name,
            "feyra_users",
            ["user_id"],
            ["id"],
            source_schema=SCHEMA,
            referent_schema=SCHEMA,
            ondelete="CASCADE",
        )


def downgrade() -> None:
    # ── 1. Restore old FK references to easyprocess.users.id ──────────
    for table_name, old_fk_name in FK_TABLES:
        op.drop_constraint(
            f"{table_name}_user_id_feyra_users_fkey",
            table_name,
            schema=SCHEMA,
            type_="foreignkey",
        )
        op.create_foreign_key(
            old_fk_name,
            table_name,
            "users",
            ["user_id"],
            ["id"],
            source_schema=SCHEMA,
            referent_schema="easyprocess",
            ondelete="CASCADE",
        )

    # ── 2. Drop auth tables (reverse order of creation) ───────────────
    op.drop_table("feyra_email_verification_tokens", schema=SCHEMA)
    op.drop_table("feyra_password_reset_tokens", schema=SCHEMA)
    op.drop_table("feyra_social_accounts", schema=SCHEMA)
    op.drop_table("feyra_audit_logs", schema=SCHEMA)
    op.drop_table("feyra_sessions", schema=SCHEMA)
    op.drop_table("feyra_users", schema=SCHEMA)

    # ── 3. Drop enum types ────────────────────────────────────────────
    for enum_name in ["feyra_social_provider", "feyra_audit_event_type", "feyra_user_role"]:
        sa.Enum(name=enum_name, schema=SCHEMA).drop(op.get_bind(), checkfirst=True)
