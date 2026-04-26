"""Add qvicko_newsletter table for newsletter subscriptions.

Revision ID: 034_add_qvicko_newsletter
Revises: 033_feyra_add_missing_fields
Create Date: 2026-04-26
"""

from alembic import op
from sqlalchemy import inspect
import sqlalchemy as sa

revision = "034_add_qvicko_newsletter"
down_revision = "033_feyra_add_missing_fields"
branch_labels = None
depends_on = None

SCHEMA = "easyprocess"


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    if not insp.has_table("qvicko_newsletter", schema=SCHEMA):
        op.create_table(
            "qvicko_newsletter",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("email", sa.String(320), nullable=False),
            sa.Column("locale", sa.String(10), nullable=False, server_default="sv"),
            sa.Column("source", sa.String(50), nullable=False, server_default="password_gate"),
            sa.Column("ip_address", sa.String(45), nullable=True),
            sa.Column("user_agent", sa.Text(), nullable=True),
            sa.Column(
                "subscribed_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            schema=SCHEMA,
        )

    existing_indexes = {idx["name"] for idx in insp.get_indexes("qvicko_newsletter", schema=SCHEMA)}
    if "idx_newsletter_email" not in existing_indexes:
        op.create_index(
            "idx_newsletter_email",
            "qvicko_newsletter",
            ["email"],
            unique=True,
            schema=SCHEMA,
        )
    if "idx_newsletter_locale" not in existing_indexes:
        op.create_index(
            "idx_newsletter_locale",
            "qvicko_newsletter",
            ["locale"],
            schema=SCHEMA,
        )


def downgrade() -> None:
    op.drop_index("idx_newsletter_locale", "qvicko_newsletter", schema=SCHEMA)
    op.drop_index("idx_newsletter_email", "qvicko_newsletter", schema=SCHEMA)
    op.drop_table("qvicko_newsletter", schema=SCHEMA)
