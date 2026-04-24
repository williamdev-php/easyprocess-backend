"""Add bookings, payment methods, and Stripe Connect tables.

Revision ID: 027_add_bookings_and_payments
Revises: 026_add_crawl_report_column
Create Date: 2026-04-24
"""
import uuid

from alembic import op
import sqlalchemy as sa

revision = "027_add_bookings_and_payments"
down_revision = "026_add_crawl_report_column"
branch_labels = None
depends_on = None

SCHEMA = "easyprocess"

BOOKINGS_APP_ID = str(uuid.uuid4())


def _table_exists(conn, table: str) -> bool:
    result = conn.execute(sa.text(
        "SELECT table_name FROM information_schema.tables "
        f"WHERE table_schema='{SCHEMA}' AND table_name=:table"
    ), {"table": table})
    return result.fetchone() is not None


def upgrade() -> None:
    conn = op.get_bind()

    # ---------------------------------------------------------------
    # 1. booking_services
    # ---------------------------------------------------------------
    if not _table_exists(conn, "booking_services"):
        op.create_table(
            "booking_services",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("site_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.generated_sites.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="60"),
            sa.Column("price", sa.Numeric(10, 2), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(3), nullable=False, server_default="SEK"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            schema=SCHEMA,
        )
        op.create_index("idx_booking_services_site_id", "booking_services", ["site_id"], schema=SCHEMA)
        op.create_index("idx_booking_services_site_active", "booking_services", ["site_id", "is_active"], schema=SCHEMA)

    # ---------------------------------------------------------------
    # 2. booking_form_fields
    # ---------------------------------------------------------------
    if not _table_exists(conn, "booking_form_fields"):
        op.create_table(
            "booking_form_fields",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("site_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.generated_sites.id", ondelete="CASCADE"), nullable=False),
            sa.Column("label", sa.String(200), nullable=False),
            sa.Column("field_type", sa.String(50), nullable=False),
            sa.Column("placeholder", sa.String(200), nullable=True),
            sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("options", sa.JSON(), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            schema=SCHEMA,
        )
        op.create_index("idx_booking_form_fields_site_id", "booking_form_fields", ["site_id"], schema=SCHEMA)

    # ---------------------------------------------------------------
    # 3. booking_payment_methods
    # ---------------------------------------------------------------
    if not _table_exists(conn, "booking_payment_methods"):
        op.create_table(
            "booking_payment_methods",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("site_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.generated_sites.id", ondelete="CASCADE"), nullable=False),
            sa.Column("stripe_connect_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("on_site_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("klarna_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("swish_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("site_id", name="uq_booking_payment_methods_site_id"),
            schema=SCHEMA,
        )

    # ---------------------------------------------------------------
    # 4. bookings
    # ---------------------------------------------------------------
    if not _table_exists(conn, "bookings"):
        op.create_table(
            "bookings",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("site_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.generated_sites.id", ondelete="CASCADE"), nullable=False),
            sa.Column("service_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.booking_services.id", ondelete="SET NULL"), nullable=True),
            sa.Column("service_name", sa.String(200), nullable=True),
            sa.Column("customer_name", sa.String(200), nullable=False),
            sa.Column("customer_email", sa.String(320), nullable=False),
            sa.Column("customer_phone", sa.String(50), nullable=True),
            sa.Column("form_data", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
            sa.Column("payment_method", sa.String(50), nullable=True),
            sa.Column("payment_status", sa.String(20), nullable=False, server_default="UNPAID"),
            sa.Column("stripe_payment_intent_id", sa.String(255), nullable=True),
            sa.Column("amount", sa.Numeric(10, 2), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(3), nullable=False, server_default="SEK"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("booking_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            schema=SCHEMA,
        )
        op.create_index("idx_bookings_site_id", "bookings", ["site_id"], schema=SCHEMA)
        op.create_index("idx_bookings_status", "bookings", ["status"], schema=SCHEMA)
        op.create_index("idx_bookings_payment_status", "bookings", ["payment_status"], schema=SCHEMA)
        op.create_index("idx_bookings_customer_email", "bookings", ["customer_email"], schema=SCHEMA)
        op.create_index("idx_bookings_site_status", "bookings", ["site_id", "status"], schema=SCHEMA)
        op.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS idx_bookings_stripe_pi "
            f"ON {SCHEMA}.bookings (stripe_payment_intent_id) "
            f"WHERE stripe_payment_intent_id IS NOT NULL"
        )

    # ---------------------------------------------------------------
    # 5. connected_accounts
    # ---------------------------------------------------------------
    if not _table_exists(conn, "connected_accounts"):
        op.create_table(
            "connected_accounts",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("site_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.generated_sites.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("stripe_account_id", sa.String(255), nullable=False),
            sa.Column("onboarding_status", sa.String(50), nullable=False, server_default="pending"),
            sa.Column("charges_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("payouts_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("details_submitted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("country", sa.String(2), nullable=False, server_default="SE"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("site_id", name="uq_connected_accounts_site_id"),
            sa.UniqueConstraint("stripe_account_id", name="uq_connected_accounts_stripe_account_id"),
            schema=SCHEMA,
        )
        op.create_index("idx_connected_accounts_site_id", "connected_accounts", ["site_id"], schema=SCHEMA)
        op.create_index("idx_connected_accounts_stripe_account_id", "connected_accounts", ["stripe_account_id"], schema=SCHEMA)

    # ---------------------------------------------------------------
    # 6. platform_payments
    # ---------------------------------------------------------------
    if not _table_exists(conn, "platform_payments"):
        op.create_table(
            "platform_payments",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("booking_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.bookings.id", ondelete="CASCADE"), nullable=False),
            sa.Column("connected_account_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.connected_accounts.id", ondelete="SET NULL"), nullable=True),
            sa.Column("stripe_payment_intent_id", sa.String(255), nullable=True),
            sa.Column("stripe_charge_id", sa.String(255), nullable=True),
            sa.Column("amount", sa.Integer(), nullable=False),
            sa.Column("platform_fee", sa.Integer(), nullable=False),
            sa.Column("net_amount", sa.Integer(), nullable=False),
            sa.Column("currency", sa.String(3), nullable=False, server_default="SEK"),
            sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            schema=SCHEMA,
        )
        op.create_index("idx_platform_payments_booking_id", "platform_payments", ["booking_id"], schema=SCHEMA)
        op.create_index("idx_platform_payments_stripe_pi", "platform_payments", ["stripe_payment_intent_id"], schema=SCHEMA)
        op.create_index("idx_platform_payments_connected_account_id", "platform_payments", ["connected_account_id"], schema=SCHEMA)

    # ---------------------------------------------------------------
    # 7. Seed the "Bookings by Qvicko" app
    # ---------------------------------------------------------------
    conn.execute(sa.text(f"""
        INSERT INTO {SCHEMA}.apps (id, slug, name, description, icon_url, version, is_active, scopes, sidebar_links, category, pricing_type, developer_name, developer_url, created_at, updated_at)
        VALUES (
            :id, 'bookings', 'Bookings by Qvicko',
            :description,
            NULL, '1.0.0', true,
            :scopes,
            :sidebar_links,
            'business', 'FREE', 'Qvicko', 'https://qvicko.com',
            NOW(), NOW()
        )
        ON CONFLICT (slug) DO NOTHING
    """), {
        "id": BOOKINGS_APP_ID,
        "description": '{"sv": "Hantera bokningar, betalningar och kundformulär direkt på din hemsida. Inkluderar Stripe Connect-integration för kortbetalningar.", "en": "Manage bookings, payments and customer forms directly on your website. Includes Stripe Connect integration for card payments."}',
        "scopes": '["bookings:read", "bookings:write", "payments:read", "payments:write"]',
        "sidebar_links": '[{"key": "overview", "href_suffix": "/overview", "icon": "M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5"}, {"key": "bookings", "href_suffix": "/bookings", "icon": "M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 002.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 00-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 00.75-.75 2.25 2.25 0 00-.1-.664m-5.8 0A2.251 2.251 0 0113.5 2.25H15c1.012 0 1.867.668 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25zM6.75 12h.008v.008H6.75V12zm0 3h.008v.008H6.75V15zm0 3h.008v.008H6.75V18z"}, {"key": "form-builder", "href_suffix": "/form-builder", "icon": "M10.5 6h9.75M10.5 6a1.5 1.5 0 11-3 0m3 0a1.5 1.5 0 10-3 0M3.75 6H7.5m3 12h9.75m-9.75 0a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m-3.75 0H7.5m9-6h3.75m-3.75 0a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m-9.75 0h9.75"}, {"key": "payment-methods", "href_suffix": "/payment-methods", "icon": "M2.25 8.25h19.5M2.25 9h19.5m-16.5 5.25h6m-6 2.25h3m-3.75 3h15a2.25 2.25 0 002.25-2.25V6.75A2.25 2.25 0 0019.5 4.5h-15a2.25 2.25 0 00-2.25 2.25v10.5A2.25 2.25 0 004.5 19.5z"}]',
    })


def downgrade() -> None:
    op.drop_table("platform_payments", schema=SCHEMA)
    op.drop_table("connected_accounts", schema=SCHEMA)
    op.drop_table("bookings", schema=SCHEMA)
    op.drop_table("booking_payment_methods", schema=SCHEMA)
    op.drop_table("booking_form_fields", schema=SCHEMA)
    op.drop_table("booking_services", schema=SCHEMA)
