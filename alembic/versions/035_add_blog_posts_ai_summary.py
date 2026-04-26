"""Add ai_summary column to autoblogger.blog_posts.

Revision ID: 035_add_blog_posts_ai_summary
Revises: 034_add_qvicko_newsletter
Create Date: 2026-04-26
"""

from alembic import op
import sqlalchemy as sa

revision = "035_add_blog_posts_ai_summary"
down_revision = "034_add_qvicko_newsletter"
branch_labels = None
depends_on = None

SCHEMA = "autoblogger"


def upgrade() -> None:
    op.add_column(
        "blog_posts",
        sa.Column("ai_summary", sa.Text(), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("blog_posts", "ai_summary", schema=SCHEMA)
