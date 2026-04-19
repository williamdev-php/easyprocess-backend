"""Add soft-delete (deleted_at), previous_status to generated_sites, PAUSED status, and site_deletion_tokens table.

Revision ID: 009_soft_delete_pause
Revises: 008_claim_token
Create Date: 2026-04-19
"""
from alembic import op
import sqlalchemy as sa

revision = "009_soft_delete_pause"
down_revision = "008_claim_token"
branch_labels = None
depends_on = None

SCHEMA = "easyprocess"


def upgrade() -> None:
    # Add deleted_at and previous_status to generated_sites (idempotent)
    conn = op.get_bind()

    # Check if columns already exist before adding
    result = conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='easyprocess' AND table_name='generated_sites' "
        "AND column_name='deleted_at'"
    ))
    if not result.fetchone():
        op.add_column(
            "generated_sites",
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            schema=SCHEMA,
        )

    result = conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='easyprocess' AND table_name='generated_sites' "
        "AND column_name='previous_status'"
    ))
    if not result.fetchone():
        op.add_column(
            "generated_sites",
            sa.Column("previous_status", sa.String(20), nullable=True),
            schema=SCHEMA,
        )

    # Create index (idempotent via IF NOT EXISTS)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_generated_sites_deleted_at "
        f"ON {SCHEMA}.generated_sites (deleted_at)"
    )

    # Add PAUSED to SiteStatus enum (idempotent)
    op.execute("ALTER TYPE sitestatus ADD VALUE IF NOT EXISTS 'PAUSED'")

    # Create site_deletion_tokens table (idempotent)
    result = conn.execute(sa.text(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='easyprocess' AND table_name='site_deletion_tokens'"
    ))
    if not result.fetchone():
        op.create_table(
            "site_deletion_tokens",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "site_id",
                sa.String(36),
                sa.ForeignKey(f"{SCHEMA}.generated_sites.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                sa.String(36),
                sa.ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("token_hash", sa.String(128), unique=True, nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            schema=SCHEMA,
        )

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_site_deletion_tokens_site_id "
        f"ON {SCHEMA}.site_deletion_tokens (site_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_site_deletion_tokens_token_hash "
        f"ON {SCHEMA}.site_deletion_tokens (token_hash)"
    )


def downgrade() -> None:
    op.drop_table("site_deletion_tokens", schema=SCHEMA)
    op.execute(
        f"DROP INDEX IF EXISTS {SCHEMA}.idx_generated_sites_deleted_at"
    )
    op.drop_column("generated_sites", "previous_status", schema=SCHEMA)
    op.drop_column("generated_sites", "deleted_at", schema=SCHEMA)
