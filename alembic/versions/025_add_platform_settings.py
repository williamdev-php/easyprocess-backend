"""Add platform_settings key-value table.

Revision ID: 025_add_platform_settings
Revises: 024_add_gsc_connections
Create Date: 2026-04-24
"""

from alembic import op
import sqlalchemy as sa

revision = "025_add_platform_settings"
down_revision = "024_add_gsc_connections"
branch_labels = None
depends_on = None

SCHEMA = "easyprocess"


def upgrade() -> None:
    op.create_table(
        "platform_settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema=SCHEMA,
    )
    # Seed defaults
    op.execute(
        f"INSERT INTO {SCHEMA}.platform_settings (key, value) VALUES "
        f"('ai_model', 'claude-haiku-4-5-20251001'), "
        f"('image_model', 'nano-banana-2')"
    )


def downgrade() -> None:
    op.drop_table("platform_settings", schema=SCHEMA)
