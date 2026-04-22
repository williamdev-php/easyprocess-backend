"""Add showcase fields, pricing to apps and app_reviews table.

Revision ID: 020_add_app_showcase_and_reviews
Revises: 019_add_token_breakdown
Create Date: 2026-04-22
"""
from alembic import op
import sqlalchemy as sa

revision = "020_add_app_showcase_and_reviews"
down_revision = "019_add_token_breakdown"
branch_labels = None
depends_on = None

SCHEMA = "easyprocess"


def _col_exists(conn, table: str, column: str) -> bool:
    result = conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns "
        f"WHERE table_schema='{SCHEMA}' AND table_name=:table AND column_name=:column"
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

    # -- Add new columns to apps table --
    new_cols = [
        ("long_description", sa.Text(), None),
        ("screenshots", sa.JSON(), None),
        ("features", sa.JSON(), None),
        ("developer_name", sa.String(200), None),
        ("developer_url", sa.String(500), None),
        ("category", sa.String(100), None),
        ("pricing_type", sa.String(20), "FREE"),
        ("price", sa.Numeric(10, 2), 0),
        ("price_description", sa.String(500), None),
        ("install_count", sa.Integer(), 0),
    ]

    for col_name, col_type, default in new_cols:
        if not _col_exists(conn, "apps", col_name):
            op.add_column(
                "apps",
                sa.Column(col_name, col_type, nullable=True, server_default=str(default) if default is not None else None),
                schema=SCHEMA,
            )

    # -- Create app_reviews table --
    if not _table_exists(conn, "app_reviews"):
        op.create_table(
            "app_reviews",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("app_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.apps.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("site_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.generated_sites.id", ondelete="CASCADE"), nullable=False),
            sa.Column("rating", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(200), nullable=True),
            sa.Column("body", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            schema=SCHEMA,
        )
        op.create_unique_constraint(
            "uq_app_reviews_app_user_site",
            "app_reviews",
            ["app_id", "user_id", "site_id"],
            schema=SCHEMA,
        )
        op.create_index("idx_app_reviews_app_id", "app_reviews", ["app_id"], schema=SCHEMA)
        op.create_index("idx_app_reviews_user_id", "app_reviews", ["user_id"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_table("app_reviews", schema=SCHEMA)

    cols_to_drop = [
        "long_description", "screenshots", "features", "developer_name",
        "developer_url", "category", "pricing_type", "price",
        "price_description", "install_count",
    ]
    for col in cols_to_drop:
        op.drop_column("apps", col, schema=SCHEMA)
