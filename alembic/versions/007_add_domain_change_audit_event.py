"""Add DOMAIN_CHANGE value to auditeventtype enum

Revision ID: 007_domain_change_event
Revises: 006_site_drafts
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa

revision = "007_domain_change_event"
down_revision = "006_site_drafts"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute(sa.text("ALTER TYPE auditeventtype ADD VALUE IF NOT EXISTS 'DOMAIN_CHANGE'"))


def downgrade() -> None:
    # PostgreSQL does not support removing values from enums.
    # A full enum recreation would be needed for a real downgrade.
    pass
