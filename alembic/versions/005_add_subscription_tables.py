"""Add subscription, payment, billing_details tables and extend user/site

Revision ID: 005_subscription_tables
Revises: 004_custom_domains
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa

revision = "005_subscription_tables"
down_revision = "004_custom_domains"
branch_labels = None
depends_on = None

SCHEMA = "easyprocess"


def upgrade() -> None:
    # -- Subscriptions table --
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stripe_subscription_id", sa.String(255), unique=True, nullable=False),
        sa.Column("stripe_customer_id", sa.String(255), nullable=False),
        sa.Column("status", sa.Enum("TRIALING", "ACTIVE", "PAST_DUE", "CANCELED", "INCOMPLETE", name="subscriptionstatus", schema=SCHEMA), nullable=False, server_default="INCOMPLETE"),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("trial_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trial_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_index("idx_subscriptions_user_id", "subscriptions", ["user_id"], schema=SCHEMA)
    op.create_index("idx_subscriptions_stripe_sub_id", "subscriptions", ["stripe_subscription_id"], schema=SCHEMA)
    op.create_index("idx_subscriptions_status", "subscriptions", ["status"], schema=SCHEMA)

    # -- Payments table --
    op.create_table(
        "payments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subscription_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.subscriptions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("stripe_payment_intent_id", sa.String(255), unique=True, nullable=True),
        sa.Column("stripe_invoice_id", sa.String(255), nullable=True),
        sa.Column("amount_sek", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="sek"),
        sa.Column("status", sa.Enum("SUCCEEDED", "FAILED", "REFUNDED", "PENDING", name="paymentstatus", schema=SCHEMA), nullable=False, server_default="PENDING"),
        sa.Column("invoice_url", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_index("idx_payments_user_id", "payments", ["user_id"], schema=SCHEMA)
    op.create_index("idx_payments_subscription_id", "payments", ["subscription_id"], schema=SCHEMA)
    op.create_index("idx_payments_stripe_pi", "payments", ["stripe_payment_intent_id"], schema=SCHEMA)

    # -- Billing details table --
    op.create_table(
        "billing_details",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), unique=True, nullable=False),
        sa.Column("billing_name", sa.String(255), nullable=True),
        sa.Column("billing_company", sa.String(255), nullable=True),
        sa.Column("billing_org_number", sa.String(50), nullable=True),
        sa.Column("billing_vat_number", sa.String(50), nullable=True),
        sa.Column("billing_email", sa.String(255), nullable=True),
        sa.Column("billing_phone", sa.String(50), nullable=True),
        sa.Column("address_line1", sa.String(255), nullable=True),
        sa.Column("address_line2", sa.String(255), nullable=True),
        sa.Column("zip", sa.String(20), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("country", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_index("idx_billing_details_user_id", "billing_details", ["user_id"], schema=SCHEMA)

    # -- Extend users table --
    op.add_column("users", sa.Column("stripe_customer_id", sa.String(255), unique=True, nullable=True), schema=SCHEMA)
    op.add_column("users", sa.Column("subscription_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.subscriptions.id", ondelete="SET NULL"), nullable=True), schema=SCHEMA)
    op.add_column("users", sa.Column("country", sa.String(100), nullable=True), schema=SCHEMA)

    # -- Extend generated_sites table --
    op.add_column("generated_sites", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True), schema=SCHEMA)


def downgrade() -> None:
    op.drop_column("generated_sites", "expires_at", schema=SCHEMA)
    op.drop_column("users", "country", schema=SCHEMA)
    op.drop_column("users", "subscription_id", schema=SCHEMA)
    op.drop_column("users", "stripe_customer_id", schema=SCHEMA)

    op.drop_table("billing_details", schema=SCHEMA)
    op.drop_table("payments", schema=SCHEMA)
    op.drop_table("subscriptions", schema=SCHEMA)

    op.execute(f"DROP TYPE IF EXISTS {SCHEMA}.subscriptionstatus")
    op.execute(f"DROP TYPE IF EXISTS {SCHEMA}.paymentstatus")
