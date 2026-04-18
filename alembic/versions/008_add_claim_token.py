"""Add claim_token and claimed_by to generated_sites

Revision ID: 008_claim_token
Revises: 007_domain_change_event
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa

revision = "008_claim_token"
down_revision = "007_domain_change_event"
branch_labels = None
depends_on = None

SCHEMA = "easyprocess"


def upgrade() -> None:
    op.add_column(
        "generated_sites",
        sa.Column("claim_token", sa.String(64), nullable=True, unique=True),
        schema=SCHEMA,
    )
    op.add_column(
        "generated_sites",
        sa.Column(
            "claimed_by",
            sa.String(36),
            sa.ForeignKey(f"{SCHEMA}.users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "idx_generated_sites_claim_token",
        "generated_sites",
        ["claim_token"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_generated_sites_claim_token",
        table_name="generated_sites",
        schema=SCHEMA,
    )
    op.drop_column("generated_sites", "claimed_by", schema=SCHEMA)
    op.drop_column("generated_sites", "claim_token", schema=SCHEMA)
