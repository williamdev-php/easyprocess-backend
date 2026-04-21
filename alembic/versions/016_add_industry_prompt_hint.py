"""Add prompt_hint and default_sections columns to industries table.

Revision ID: 016_add_industry_prompt_hint
Revises: 015_add_viewer_version
Create Date: 2026-04-21
"""
from alembic import op
import sqlalchemy as sa

revision = "016_add_industry_prompt_hint"
down_revision = "015_add_viewer_version"
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

    if not _column_exists(conn, "industries", "prompt_hint"):
        op.add_column(
            "industries",
            sa.Column("prompt_hint", sa.Text(), nullable=True),
            schema=SCHEMA,
        )

    if not _column_exists(conn, "industries", "default_sections"):
        op.add_column(
            "industries",
            sa.Column("default_sections", sa.JSON(), nullable=True),
            schema=SCHEMA,
        )


def downgrade() -> None:
    op.drop_column("industries", "default_sections", schema=SCHEMA)
    op.drop_column("industries", "prompt_hint", schema=SCHEMA)
