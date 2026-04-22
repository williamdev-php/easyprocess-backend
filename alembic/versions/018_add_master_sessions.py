"""Add master session fields for device trust.

Adds device_fingerprint, is_trusted, master_expires_at, and last_active_at
to the sessions table to support long-lived master sessions on trusted devices.

Revision ID: 018_add_master_sessions
Revises: 017_add_apps_and_blog
Create Date: 2026-04-21
"""
from alembic import op
import sqlalchemy as sa

revision = "018_add_master_sessions"
down_revision = "017_add_apps_and_blog"
branch_labels = None
depends_on = None

SCHEMA = "easyprocess"


def _column_exists(conn, table: str, column: str) -> bool:
    result = conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns "
        f"WHERE table_schema='{SCHEMA}' AND table_name=:table AND column_name=:column"
    ), {"table": table, "column": column})
    return result.fetchone() is not None


def upgrade() -> None:
    conn = op.get_bind()

    if not _column_exists(conn, "sessions", "device_fingerprint"):
        op.add_column(
            "sessions",
            sa.Column("device_fingerprint", sa.String(64), nullable=True),
            schema=SCHEMA,
        )

    if not _column_exists(conn, "sessions", "is_trusted"):
        op.add_column(
            "sessions",
            sa.Column("is_trusted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            schema=SCHEMA,
        )

    if not _column_exists(conn, "sessions", "master_expires_at"):
        op.add_column(
            "sessions",
            sa.Column("master_expires_at", sa.DateTime(timezone=True), nullable=True),
            schema=SCHEMA,
        )

    if not _column_exists(conn, "sessions", "last_active_at"):
        op.add_column(
            "sessions",
            sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
            schema=SCHEMA,
        )

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sessions_device_fp "
        f"ON {SCHEMA}.sessions (device_fingerprint)"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.idx_sessions_device_fp")
    op.drop_column("sessions", "last_active_at", schema=SCHEMA)
    op.drop_column("sessions", "master_expires_at", schema=SCHEMA)
    op.drop_column("sessions", "is_trusted", schema=SCHEMA)
    op.drop_column("sessions", "device_fingerprint", schema=SCHEMA)
