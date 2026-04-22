"""Add input_tokens and output_tokens columns to generated_sites.

Splits token tracking into input/output for accurate cost calculation.

Revision ID: 019_add_token_breakdown
Revises: 018_add_master_sessions
Create Date: 2026-04-22
"""
from alembic import op
import sqlalchemy as sa

revision = "019_add_token_breakdown"
down_revision = "018_add_master_sessions"
branch_labels = None
depends_on = None

SCHEMA = "easyprocess"


def upgrade() -> None:
    op.add_column("generated_sites", sa.Column("input_tokens", sa.Integer(), nullable=True), schema=SCHEMA)
    op.add_column("generated_sites", sa.Column("output_tokens", sa.Integer(), nullable=True), schema=SCHEMA)


def downgrade() -> None:
    op.drop_column("generated_sites", "output_tokens", schema=SCHEMA)
    op.drop_column("generated_sites", "input_tokens", schema=SCHEMA)
