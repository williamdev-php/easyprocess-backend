"""Convert app description and long_description to JSON for i18n support.

Revision ID: 023_i18n_app_descriptions
Revises: 022_add_chat
Create Date: 2026-04-22
"""
import json

from alembic import op
import sqlalchemy as sa

revision = "023_i18n_app_descriptions"
down_revision = "022_add_chat"
branch_labels = None
depends_on = None

SCHEMA = "easyprocess"


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Add new JSON columns
    op.add_column(
        "apps",
        sa.Column("description_i18n", sa.JSON(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "apps",
        sa.Column("long_description_i18n", sa.JSON(), nullable=True),
        schema=SCHEMA,
    )

    # 2. Migrate existing Swedish descriptions to i18n JSON and fix names to English
    # Blog app
    conn.execute(sa.text(f"""
        UPDATE {SCHEMA}.apps
        SET description_i18n = :desc_json, name = 'Blog by Qvicko'
        WHERE slug = 'blog'
    """), {
        "desc_json": json.dumps({
            "en": "Create and manage blog posts for your website. Publish articles, organize with categories, and boost your online visibility.",
            "sv": "Skapa och hantera blogginlägg för din webbplats. Publicera artiklar, organisera med kategorier och öka din synlighet online.",
        }),
    })

    # Chat app
    conn.execute(sa.text(f"""
        UPDATE {SCHEMA}.apps
        SET description_i18n = :desc_json
        WHERE slug = 'chat'
    """), {
        "desc_json": json.dumps({
            "en": "Add a chat widget to your website. Visitors can send messages directly and you reply from your dashboard.",
            "sv": "Lägg till en chattbubbla på din webbplats. Besökare kan skicka meddelanden direkt och du svarar från din dashboard.",
        }),
    })

    # 3. Drop old text columns and rename new ones
    op.drop_column("apps", "description", schema=SCHEMA)
    op.drop_column("apps", "long_description", schema=SCHEMA)
    op.alter_column(
        "apps", "description_i18n",
        new_column_name="description",
        schema=SCHEMA,
    )
    op.alter_column(
        "apps", "long_description_i18n",
        new_column_name="long_description",
        schema=SCHEMA,
    )


def downgrade() -> None:
    conn = op.get_bind()

    # Add back text columns
    op.add_column(
        "apps",
        sa.Column("description_text", sa.Text(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "apps",
        sa.Column("long_description_text", sa.Text(), nullable=True),
        schema=SCHEMA,
    )

    # Extract Swedish text from JSON
    conn.execute(sa.text(f"""
        UPDATE {SCHEMA}.apps
        SET description_text = description->>'sv',
            long_description_text = long_description->>'sv'
    """))

    op.drop_column("apps", "description", schema=SCHEMA)
    op.drop_column("apps", "long_description", schema=SCHEMA)
    op.alter_column(
        "apps", "description_text",
        new_column_name="description",
        schema=SCHEMA,
    )
    op.alter_column(
        "apps", "long_description_text",
        new_column_name="long_description",
        schema=SCHEMA,
    )
