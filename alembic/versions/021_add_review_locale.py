"""Add locale column to app_reviews.

Revision ID: 021_add_review_locale
Revises: 020_add_app_showcase_and_reviews
Create Date: 2026-04-22
"""
from alembic import op
import sqlalchemy as sa

revision = "021_add_review_locale"
down_revision = "020_add_app_showcase_and_reviews"
branch_labels = None
depends_on = None

SCHEMA = "easyprocess"


def _col_exists(conn, table: str, column: str) -> bool:
    result = conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns "
        f"WHERE table_schema='{SCHEMA}' AND table_name=:table AND column_name=:column"
    ), {"table": table, "column": column})
    return result.fetchone() is not None


def upgrade() -> None:
    conn = op.get_bind()
    if not _col_exists(conn, "app_reviews", "locale"):
        op.add_column(
            "app_reviews",
            sa.Column("locale", sa.String(10), nullable=True),
            schema=SCHEMA,
        )


def downgrade() -> None:
    op.drop_column("app_reviews", "locale", schema=SCHEMA)
