"""Add viewer_version column to generated_sites.

Revision ID: 015_add_viewer_version
Revises: 014_add_industries
Create Date: 2026-04-20
"""
from alembic import op
import sqlalchemy as sa

revision = "015_add_viewer_version"
down_revision = "014_add_industries"
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

    if not _column_exists(conn, "generated_sites", "viewer_version"):
        op.add_column(
            "generated_sites",
            sa.Column("viewer_version", sa.String(10), nullable=False, server_default="v1"),
            schema=SCHEMA,
        )


def downgrade() -> None:
    op.drop_column("generated_sites", "viewer_version", schema=SCHEMA)
