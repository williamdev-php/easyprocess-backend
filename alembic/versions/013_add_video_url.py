"""Add video_url column to generated_sites.

Revision ID: 013_add_video_url
Revises: 012_add_support_tickets
Create Date: 2026-04-20
"""
from alembic import op
import sqlalchemy as sa

revision = "013_add_video_url"
down_revision = "012_add_support_tickets"
branch_labels = None
depends_on = None

SCHEMA = "easyprocess"


def upgrade() -> None:
    op.add_column(
        "generated_sites",
        sa.Column("video_url", sa.String(500), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("generated_sites", "video_url", schema=SCHEMA)
