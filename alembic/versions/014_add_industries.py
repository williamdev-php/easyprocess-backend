"""Add industries table and industry_id FK on leads.

Revision ID: 014_add_industries
Revises: 013_add_video_url
Create Date: 2026-04-20
"""
from alembic import op
import sqlalchemy as sa

revision = "014_add_industries"
down_revision = "013_add_video_url"
branch_labels = None
depends_on = None

SCHEMA = "easyprocess"


def _table_exists(conn, table: str) -> bool:
    result = conn.execute(sa.text(
        "SELECT table_name FROM information_schema.tables "
        f"WHERE table_schema='{SCHEMA}' AND table_name=:table"
    ), {"table": table})
    return result.fetchone() is not None


def upgrade() -> None:
    conn = op.get_bind()

    if not _table_exists(conn, "industries"):
        op.create_table(
            "industries",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(100), nullable=False, unique=True),
            sa.Column("slug", sa.String(100), nullable=False, unique=True),
            sa.Column("description", sa.String(500), nullable=True),
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
        "CREATE INDEX IF NOT EXISTS idx_industries_slug "
        f"ON {SCHEMA}.industries (slug)"
    )

    # Add industry_id column to leads if it doesn't exist
    result = conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns "
        f"WHERE table_schema='{SCHEMA}' AND table_name='leads' AND column_name='industry_id'"
    ))
    if result.fetchone() is None:
        op.add_column(
            "leads",
            sa.Column(
                "industry_id", sa.String(36),
                sa.ForeignKey(f"{SCHEMA}.industries.id", ondelete="SET NULL"),
                nullable=True,
            ),
            schema=SCHEMA,
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_leads_industry_id "
            f"ON {SCHEMA}.leads (industry_id)"
        )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.idx_leads_industry_id")
    op.drop_column("leads", "industry_id", schema=SCHEMA)
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.idx_industries_slug")
    op.drop_table("industries", schema=SCHEMA)
