"""Add chat conversations and messages tables.

Revision ID: 022_add_chat
Revises: 021_add_review_locale
Create Date: 2026-04-22
"""
import uuid

from alembic import op
import sqlalchemy as sa

revision = "022_add_chat"
down_revision = "021_add_review_locale"
branch_labels = None
depends_on = None

SCHEMA = "easyprocess"

CHAT_APP_ID = str(uuid.uuid4())


def _table_exists(conn, table: str) -> bool:
    result = conn.execute(sa.text(
        "SELECT table_name FROM information_schema.tables "
        f"WHERE table_schema='{SCHEMA}' AND table_name=:table"
    ), {"table": table})
    return result.fetchone() is not None


def upgrade() -> None:
    conn = op.get_bind()

    # --- chat_conversations ---
    if not _table_exists(conn, "chat_conversations"):
        op.create_table(
            "chat_conversations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("site_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.generated_sites.id", ondelete="CASCADE"), nullable=False),
            sa.Column("visitor_email", sa.String(320), nullable=False),
            sa.Column("visitor_name", sa.String(200), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="open"),
            sa.Column("subject", sa.String(500), nullable=True),
            sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            schema=SCHEMA,
        )
        op.create_index("idx_chat_conversations_site_id", "chat_conversations", ["site_id"], schema=SCHEMA)
        op.create_index("idx_chat_conversations_status", "chat_conversations", ["status"], schema=SCHEMA)
        op.create_index("idx_chat_conversations_site_status", "chat_conversations", ["site_id", "status"], schema=SCHEMA)
        op.create_index("idx_chat_conversations_visitor_email", "chat_conversations", ["visitor_email"], schema=SCHEMA)

    # --- chat_messages ---
    if not _table_exists(conn, "chat_messages"):
        op.create_table(
            "chat_messages",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("conversation_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.chat_conversations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("sender_type", sa.String(20), nullable=False),
            sa.Column("sender_name", sa.String(200), nullable=True),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            schema=SCHEMA,
        )
        op.create_index("idx_chat_messages_conversation_id", "chat_messages", ["conversation_id"], schema=SCHEMA)
        op.create_index("idx_chat_messages_created_at", "chat_messages", ["created_at"], schema=SCHEMA)

    # --- Seed the "chat" app ---
    conn.execute(sa.text(f"""
        INSERT INTO {SCHEMA}.apps (id, slug, name, description, icon_url, version, is_active, scopes, sidebar_links, created_at, updated_at)
        VALUES (
            :id, 'chat', 'Chat by Qvicko',
            'Lägg till en chattbubbla på din webbplats. Besökare kan skicka meddelanden direkt och du svarar från din dashboard.',
            NULL, '1.0.0', true,
            :scopes,
            :sidebar_links,
            NOW(), NOW()
        )
        ON CONFLICT (slug) DO NOTHING
    """), {
        "id": CHAT_APP_ID,
        "scopes": '["chat:read", "chat:write"]',
        "sidebar_links": '[{"key": "conversations", "href_suffix": "/conversations", "icon": "M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.129.166 2.27.293 3.423.379.35.026.67.21.865.501L12 21l2.755-4.133a1.14 1.14 0 01.865-.501 48.172 48.172 0 003.423-.379c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z"}]',
    })


def downgrade() -> None:
    op.drop_table("chat_messages", schema=SCHEMA)
    op.drop_table("chat_conversations", schema=SCHEMA)
