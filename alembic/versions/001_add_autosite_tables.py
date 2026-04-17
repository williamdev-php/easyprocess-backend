"""add leads, scraped_data, generated_sites, outreach_emails tables

Revision ID: 001_autosite
Revises: None
Create Date: 2026-04-16
"""

from alembic import op
import sqlalchemy as sa

revision = "001_autosite"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA = "easyprocess"


def upgrade() -> None:
    # --- Leads ---
    op.create_table(
        "leads",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("business_name", sa.String(255), nullable=True),
        sa.Column("website_url", sa.String(500), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("address", sa.String(500), nullable=True),
        sa.Column("industry", sa.String(100), nullable=True),
        sa.Column("source", sa.String(100), nullable=False, server_default="manual"),
        sa.Column(
            "status",
            sa.Enum(
                "NEW", "SCRAPING", "SCRAPED", "GENERATING", "GENERATED",
                "EMAIL_SENT", "OPENED", "CONVERTED", "REJECTED", "FAILED",
                name="leadstatus", schema=SCHEMA,
            ),
            nullable=False,
            server_default="NEW",
        ),
        sa.Column("quality_score", sa.Float, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("scraped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey(f"{SCHEMA}.users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_index("idx_leads_status", "leads", ["status"], schema=SCHEMA)
    op.create_index("idx_leads_email", "leads", ["email"], schema=SCHEMA)
    op.create_index("idx_leads_website_url", "leads", ["website_url"], schema=SCHEMA)
    op.create_index("idx_leads_created_by", "leads", ["created_by"], schema=SCHEMA)

    # --- Scraped Data ---
    op.create_table(
        "scraped_data",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("lead_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.leads.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("logo_url", sa.String(500), nullable=True),
        sa.Column("colors", sa.JSON, nullable=True),
        sa.Column("texts", sa.JSON, nullable=True),
        sa.Column("images", sa.JSON, nullable=True),
        sa.Column("contact_info", sa.JSON, nullable=True),
        sa.Column("meta_info", sa.JSON, nullable=True),
        sa.Column("raw_html_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_index("idx_scraped_data_lead_id", "scraped_data", ["lead_id"], schema=SCHEMA)

    # --- Generated Sites ---
    op.create_table(
        "generated_sites",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("lead_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.leads.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("site_data", sa.JSON, nullable=False),
        sa.Column("template", sa.String(50), nullable=False, server_default="default"),
        sa.Column(
            "status",
            sa.Enum("DRAFT", "PUBLISHED", "PURCHASED", "ARCHIVED", name="sitestatus", schema=SCHEMA),
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column("subdomain", sa.String(100), unique=True, nullable=True),
        sa.Column("custom_domain", sa.String(255), nullable=True),
        sa.Column("views", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tokens_used", sa.Integer, nullable=True),
        sa.Column("ai_model", sa.String(50), nullable=True),
        sa.Column("generation_cost_usd", sa.Float, nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purchased_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_index("idx_generated_sites_lead_id", "generated_sites", ["lead_id"], schema=SCHEMA)
    op.create_index("idx_generated_sites_subdomain", "generated_sites", ["subdomain"], schema=SCHEMA)
    op.create_index("idx_generated_sites_status", "generated_sites", ["status"], schema=SCHEMA)

    # --- Outreach Emails ---
    op.create_table(
        "outreach_emails",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("lead_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("site_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.generated_sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("to_email", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("body_html", sa.Text, nullable=False),
        sa.Column("resend_id", sa.String(255), nullable=True),
        sa.Column(
            "status",
            sa.Enum("PENDING", "SENT", "DELIVERED", "OPENED", "CLICKED", "BOUNCED", "FAILED", name="emailstatus", schema=SCHEMA),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("clicked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_index("idx_outreach_emails_lead_id", "outreach_emails", ["lead_id"], schema=SCHEMA)
    op.create_index("idx_outreach_emails_site_id", "outreach_emails", ["site_id"], schema=SCHEMA)
    op.create_index("idx_outreach_emails_resend_id", "outreach_emails", ["resend_id"], schema=SCHEMA)
    op.create_index("idx_outreach_emails_status", "outreach_emails", ["status"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_table("outreach_emails", schema=SCHEMA)
    op.drop_table("generated_sites", schema=SCHEMA)
    op.drop_table("scraped_data", schema=SCHEMA)
    op.drop_table("leads", schema=SCHEMA)
    op.execute(f"DROP TYPE IF EXISTS {SCHEMA}.emailstatus")
    op.execute(f"DROP TYPE IF EXISTS {SCHEMA}.sitestatus")
    op.execute(f"DROP TYPE IF EXISTS {SCHEMA}.leadstatus")
