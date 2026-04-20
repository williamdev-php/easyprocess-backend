"""Add support_tickets table and superuser_promotion_log table.

Revision ID: 012_add_support_tickets
Revises: 011_add_tracking_events
Create Date: 2026-04-20
"""
from alembic import op
import sqlalchemy as sa

revision = "012_add_support_tickets"
down_revision = "011_add_tracking_events"
branch_labels = None
depends_on = None

SCHEMA = "easyprocess"


def upgrade() -> None:
    # --- Support tickets ---
    op.create_table(
        "support_tickets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("status", sa.Enum("OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED", name="ticketstatus", schema=SCHEMA), nullable=False, server_default="OPEN"),
        sa.Column("priority", sa.Enum("LOW", "NORMAL", "HIGH", "URGENT", name="ticketpriority", schema=SCHEMA), nullable=False, server_default="NORMAL"),
        sa.Column("is_read", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_archived", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("admin_reply", sa.Text, nullable=True),
        sa.Column("replied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_index("idx_support_tickets_user_id", "support_tickets", ["user_id"], schema=SCHEMA)
    op.create_index("idx_support_tickets_status", "support_tickets", ["status"], schema=SCHEMA)
    op.create_index("idx_support_tickets_created_at", "support_tickets", ["created_at"], schema=SCHEMA)

    # --- Superuser promotion log (for rate limiting to max 1/week) ---
    op.create_table(
        "superuser_promotions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("promoted_user_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("promoted_by_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_index("idx_superuser_promotions_created_at", "superuser_promotions", ["created_at"], schema=SCHEMA)

    # --- Add deleted_at to users for soft delete ---
    op.add_column("users", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True), schema=SCHEMA)

    # --- Notifications ---
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.Enum("TICKET_CREATED", "TICKET_REPLIED", "TICKET_STATUS_CHANGED", name="notificationtype", schema=SCHEMA), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text, nullable=True),
        sa.Column("link", sa.String(500), nullable=True),
        sa.Column("is_read", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema=SCHEMA,
    )
    op.create_index("idx_notifications_user_id", "notifications", ["user_id"], schema=SCHEMA)
    op.create_index("idx_notifications_user_unread", "notifications", ["user_id", "is_read"], schema=SCHEMA)
    op.create_index("idx_notifications_created_at", "notifications", ["created_at"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_table("notifications", schema=SCHEMA)
    op.execute(f"DROP TYPE IF EXISTS {SCHEMA}.notificationtype")
    op.drop_column("users", "deleted_at", schema=SCHEMA)
    op.drop_table("superuser_promotions", schema=SCHEMA)
    op.drop_table("support_tickets", schema=SCHEMA)
    op.execute(f"DROP TYPE IF EXISTS {SCHEMA}.ticketstatus")
    op.execute(f"DROP TYPE IF EXISTS {SCHEMA}.ticketpriority")
