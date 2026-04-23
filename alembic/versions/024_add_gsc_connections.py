"""Add Google Search Console connections table.

Revision ID: 024_add_gsc_connections
Revises: 023_i18n_app_descriptions
Create Date: 2026-04-23
"""

from alembic import op
import sqlalchemy as sa

revision = "024_add_gsc_connections"
down_revision = "023_i18n_app_descriptions"
branch_labels = None
depends_on = None

SCHEMA = "easyprocess"


def upgrade() -> None:
    op.create_table(
        "gsc_connections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column("google_email", sa.String(320), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=False),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Enum("CONNECTED", "EXPIRED", "REVOKED", name="gscconnectionstatus", schema=SCHEMA),
            nullable=False,
            server_default="CONNECTED",
        ),
        sa.Column("indexed_domain", sa.String(255), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_index("idx_gsc_connections_user_id", "gsc_connections", ["user_id"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_index("idx_gsc_connections_user_id", table_name="gsc_connections", schema=SCHEMA)
    op.drop_table("gsc_connections", schema=SCHEMA)
    op.execute(f"DROP TYPE IF EXISTS {SCHEMA}.gscconnectionstatus")
