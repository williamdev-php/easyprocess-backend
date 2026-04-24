"""Add crawl_report JSON column to scraped_data.

Stores multi-page crawl results (site map, generation notes, etc.)
for richer AI site generation.

Revision ID: 026_add_crawl_report_column
Revises: 025_add_platform_settings
Create Date: 2026-04-24
"""

from alembic import op
import sqlalchemy as sa

revision = "026_add_crawl_report_column"
down_revision = "025_add_platform_settings"
branch_labels = None
depends_on = None

SCHEMA = "easyprocess"


def upgrade() -> None:
    op.add_column(
        "scraped_data",
        sa.Column("crawl_report", sa.JSON(), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("scraped_data", "crawl_report", schema=SCHEMA)
