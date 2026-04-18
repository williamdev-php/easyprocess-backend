"""Add site_drafts table for editor auto-save

Revision ID: 006_site_drafts
Revises: 005_subscription_tables
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa

revision = "006_site_drafts"
down_revision = "005_subscription_tables"
branch_labels = None
depends_on = None

SCHEMA = "easyprocess"


def upgrade() -> None:
    op.create_table(
        "site_drafts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "site_id",
            sa.String(36),
            sa.ForeignKey(f"{SCHEMA}.generated_sites.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("draft_data", sa.JSON, nullable=False, server_default="{}"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_site_drafts_site_id",
        "site_drafts",
        ["site_id"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("idx_site_drafts_site_id", table_name="site_drafts", schema=SCHEMA)
    op.drop_table("site_drafts", schema=SCHEMA)
