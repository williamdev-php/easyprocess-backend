"""Add requires_payments column to apps table.

Apps that require payment processing (e.g. Bookings, E-commerce) set this to True.
The dashboard uses this flag to show the "Ta betalt" (Payments) section.

Revision ID: 028_requires_payments
Revises: 027_add_bookings_and_payments
Create Date: 2026-04-24
"""

from alembic import op
import sqlalchemy as sa

revision = "028_requires_payments"
down_revision = "027_add_bookings_and_payments"
branch_labels = None
depends_on = None

SCHEMA = "easyprocess"


def upgrade() -> None:
    # Add requires_payments column with default False
    op.add_column(
        "apps",
        sa.Column("requires_payments", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema=SCHEMA,
    )

    # Set requires_payments=True for the bookings app
    op.execute(
        f"UPDATE {SCHEMA}.apps SET requires_payments = true WHERE slug = 'bookings'"
    )


def downgrade() -> None:
    op.drop_column("apps", "requires_payments", schema=SCHEMA)
