"""Add custom_domains table for user domain management

Revision ID: 004_custom_domains
Revises: 003_billing_settings_audit
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa

revision = "004_custom_domains"
down_revision = "003_billing_settings_audit"
branch_labels = None
depends_on = None

SCHEMA = "easyprocess"


def upgrade() -> None:
    # Create domain status enum
    domain_status = sa.Enum("PENDING", "ACTIVE", "FAILED", name="domainstatus", schema=SCHEMA)
    domain_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "custom_domains",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("domain", sa.String(255), unique=True, nullable=False),
        sa.Column("site_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.generated_sites.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", domain_status, nullable=False, server_default="PENDING"),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema=SCHEMA,
    )

    op.create_index("idx_custom_domains_user_id", "custom_domains", ["user_id"], schema=SCHEMA)
    op.create_index("idx_custom_domains_domain", "custom_domains", ["domain"], schema=SCHEMA)
    op.create_index("idx_custom_domains_site_id", "custom_domains", ["site_id"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_index("idx_custom_domains_site_id", table_name="custom_domains", schema=SCHEMA)
    op.drop_index("idx_custom_domains_domain", table_name="custom_domains", schema=SCHEMA)
    op.drop_index("idx_custom_domains_user_id", table_name="custom_domains", schema=SCHEMA)
    op.drop_table("custom_domains", schema=SCHEMA)

    domain_status = sa.Enum("PENDING", "ACTIVE", "FAILED", name="domainstatus", schema=SCHEMA)
    domain_status.drop(op.get_bind(), checkfirst=True)
