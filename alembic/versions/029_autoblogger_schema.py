"""Create AutoBlogger schema tables.

Creates all tables for the AutoBlogger feature in the 'autoblogger' schema.
The schema itself is created at app startup in main.py; this migration
handles table creation via Alembic.

Revision ID: 029_autoblogger_schema
Revises: 028_requires_payments
Create Date: 2026-04-25
"""

from alembic import op
import sqlalchemy as sa

revision = "029_autoblogger_schema"
down_revision = "028_requires_payments"
branch_labels = None
depends_on = None

SCHEMA = "autoblogger"


def upgrade() -> None:
    # ── Schema ──���──────────────────────────────────��────────────────────
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    # ── Enums ───────────���───────────────���────────────────────────────────
    platformtype = sa.Enum(
        "SHOPIFY", "QVICKO", "CUSTOM",
        name="platformtype", schema=SCHEMA, create_type=True,
    )
    poststatus = sa.Enum(
        "DRAFT", "SCHEDULED", "GENERATING", "REVIEW", "PUBLISHED", "FAILED",
        name="poststatus", schema=SCHEMA, create_type=True,
    )
    taskfrequency = sa.Enum(
        "DAILY", "WEEKLY", "BIWEEKLY", "MONTHLY",
        name="taskfrequency", schema=SCHEMA, create_type=True,
    )

    # ── 1. sources ───────────────────────────────────────────────────────
    op.create_table(
        "sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("platform", platformtype, nullable=False),
        sa.Column("platform_url", sa.String(1000), nullable=True),
        sa.Column("platform_config", sa.JSON(), nullable=True),
        sa.Column("brand_voice", sa.Text(), nullable=True),
        sa.Column("brand_images", sa.JSON(), nullable=True),
        sa.Column("default_language", sa.String(10), nullable=False, server_default="en"),
        sa.Column("target_keywords", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )

    # ── 2. blog_posts ────────────────────────────────────────────────────
    op.create_table(
        "blog_posts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "source_id", sa.String(36),
            sa.ForeignKey(f"{SCHEMA}.sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("slug", sa.String(500), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("meta_title", sa.String(500), nullable=True),
        sa.Column("meta_description", sa.String(500), nullable=True),
        sa.Column("featured_image_url", sa.String(1000), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("language", sa.String(10), nullable=False, server_default="en"),
        sa.Column("status", poststatus, nullable=False, server_default="DRAFT"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("platform_post_id", sa.String(255), nullable=True),
        sa.Column("target_keyword", sa.String(255), nullable=True),
        sa.Column("schema_markup", sa.JSON(), nullable=True),
        sa.Column("internal_links", sa.JSON(), nullable=True),
        sa.Column("ai_model", sa.String(100), nullable=True),
        sa.Column("generation_prompt", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("word_count", sa.Integer(), nullable=True),
        sa.Column("reading_time_minutes", sa.Integer(), nullable=True),
        sa.Column("credits_used", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("idx_abp_source_id", "blog_posts", ["source_id"], schema=SCHEMA)
    op.create_index("idx_abp_user_id", "blog_posts", ["user_id"], schema=SCHEMA)
    op.create_index("idx_abp_status", "blog_posts", ["status"], schema=SCHEMA)
    op.create_index("idx_abp_scheduled_at", "blog_posts", ["scheduled_at"], schema=SCHEMA)

    # ── 3. content_schedules ─────────────────────────────────────────────
    op.create_table(
        "content_schedules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "source_id", sa.String(36),
            sa.ForeignKey(f"{SCHEMA}.sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("frequency", taskfrequency, nullable=False),
        sa.Column("days_of_week", sa.JSON(), nullable=True),
        sa.Column("posts_per_day", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("preferred_time", sa.String(10), nullable=True),
        sa.Column("timezone", sa.String(50), nullable=False, server_default="Europe/Stockholm"),
        sa.Column("topics", sa.JSON(), nullable=True),
        sa.Column("keywords", sa.JSON(), nullable=True),
        sa.Column("language", sa.String(10), nullable=False, server_default="en"),
        sa.Column("auto_publish", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("posts_generated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("idx_cs_source_id", "content_schedules", ["source_id"], schema=SCHEMA)
    op.create_index("idx_cs_next_run", "content_schedules", ["next_run_at"], schema=SCHEMA)

    # ── 4. user_settings ─────────────────────────────────────────────────
    op.create_table(
        "user_settings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False, unique=True, index=True),
        sa.Column("auto_publish", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("ai_model", sa.String(100), nullable=False, server_default="claude-sonnet-4-20250514"),
        sa.Column("image_generation", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("default_language", sa.String(10), nullable=False, server_default="en"),
        sa.Column("brand_voice_global", sa.Text(), nullable=True),
        sa.Column("posts_per_month_limit", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("notification_email", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )

    # ── 5. subscriptions ─────────────────────────────────────────────────
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False, unique=True),
        sa.Column("stripe_subscription_id", sa.String(255), nullable=False, unique=True),
        sa.Column("stripe_customer_id", sa.String(255), nullable=False),
        sa.Column("plan", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="trialing"),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trial_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trial_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("idx_absub_user_id", "subscriptions", ["user_id"], schema=SCHEMA)
    op.create_index("idx_absub_stripe_id", "subscriptions", ["stripe_subscription_id"], schema=SCHEMA)

    # ── 6. payments ──────────────────────────────────────────────────────
    op.create_table(
        "payments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column(
            "subscription_id", sa.String(36),
            sa.ForeignKey(f"{SCHEMA}.subscriptions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("stripe_payment_intent_id", sa.String(255), unique=True, nullable=True),
        sa.Column("stripe_invoice_id", sa.String(255), nullable=True),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(10), nullable=False, server_default="sek"),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("invoice_url", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("idx_abpay_user_id", "payments", ["user_id"], schema=SCHEMA)

    # ── 7. credit_balances ───────────────────────────────────────────────
    op.create_table(
        "credit_balances",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False, unique=True, index=True),
        sa.Column("credits_remaining", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("credits_used_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("plan_credits_monthly", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("last_reset_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )

    # ── 8. credit_transactions ───────────────────────────────────────────
    op.create_table(
        "credit_transactions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column(
            "post_id", sa.String(36),
            sa.ForeignKey(f"{SCHEMA}.blog_posts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("idx_ct_user_id", "credit_transactions", ["user_id"], schema=SCHEMA)
    op.create_index("idx_ct_created_at", "credit_transactions", ["created_at"], schema=SCHEMA)


def downgrade() -> None:
    # Drop tables in reverse order (respect FK dependencies)
    op.drop_table("credit_transactions", schema=SCHEMA)
    op.drop_table("credit_balances", schema=SCHEMA)
    op.drop_table("payments", schema=SCHEMA)
    op.drop_table("subscriptions", schema=SCHEMA)
    op.drop_table("user_settings", schema=SCHEMA)
    op.drop_table("content_schedules", schema=SCHEMA)
    op.drop_table("blog_posts", schema=SCHEMA)
    op.drop_table("sources", schema=SCHEMA)

    # Drop enums
    sa.Enum(name="taskfrequency", schema=SCHEMA).drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="poststatus", schema=SCHEMA).drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="platformtype", schema=SCHEMA).drop(op.get_bind(), checkfirst=True)
