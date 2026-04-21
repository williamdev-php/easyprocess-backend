"""Add apps system and blog tables.

Revision ID: 017_add_apps_and_blog
Revises: 016_add_industry_prompt_hint
Create Date: 2026-04-21
"""
import uuid

from alembic import op
import sqlalchemy as sa

revision = "017_add_apps_and_blog"
down_revision = "016_add_industry_prompt_hint"
branch_labels = None
depends_on = None

SCHEMA = "easyprocess"

BLOG_APP_ID = str(uuid.uuid4())


def _table_exists(conn, table: str) -> bool:
    result = conn.execute(sa.text(
        "SELECT table_name FROM information_schema.tables "
        f"WHERE table_schema='{SCHEMA}' AND table_name=:table"
    ), {"table": table})
    return result.fetchone() is not None


def upgrade() -> None:
    conn = op.get_bind()

    # --- apps ---
    if not _table_exists(conn, "apps"):
        op.create_table(
            "apps",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("slug", sa.String(50), unique=True, nullable=False),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("icon_url", sa.String(500), nullable=True),
            sa.Column("version", sa.String(20), nullable=False, server_default="1.0.0"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("scopes", sa.JSON(), nullable=True),
            sa.Column("sidebar_links", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            schema=SCHEMA,
        )
        op.create_index("idx_apps_slug", "apps", ["slug"], schema=SCHEMA)

    # --- app_installations ---
    if not _table_exists(conn, "app_installations"):
        op.create_table(
            "app_installations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("app_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.apps.id", ondelete="CASCADE"), nullable=False),
            sa.Column("site_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.generated_sites.id", ondelete="CASCADE"), nullable=False),
            sa.Column("installed_by", sa.String(36), sa.ForeignKey(f"{SCHEMA}.users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("settings", sa.JSON(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("installed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("app_id", "site_id", name="uq_app_installations_app_site"),
            schema=SCHEMA,
        )
        op.create_index("idx_app_installations_app_id", "app_installations", ["app_id"], schema=SCHEMA)
        op.create_index("idx_app_installations_site_id", "app_installations", ["site_id"], schema=SCHEMA)

    # --- blog_categories ---
    if not _table_exists(conn, "blog_categories"):
        op.create_table(
            "blog_categories",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("site_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.generated_sites.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("slug", sa.String(100), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("site_id", "slug", name="uq_blog_categories_site_slug"),
            schema=SCHEMA,
        )
        op.create_index("idx_blog_categories_site_id", "blog_categories", ["site_id"], schema=SCHEMA)

    # --- blog_posts ---
    if not _table_exists(conn, "blog_posts"):
        op.create_table(
            "blog_posts",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("site_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.generated_sites.id", ondelete="CASCADE"), nullable=False),
            sa.Column("category_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.blog_categories.id", ondelete="SET NULL"), nullable=True),
            sa.Column("title", sa.String(500), nullable=False),
            sa.Column("slug", sa.String(500), nullable=False),
            sa.Column("excerpt", sa.Text(), nullable=True),
            sa.Column("content", sa.Text(), nullable=False, server_default=""),
            sa.Column("featured_image", sa.String(500), nullable=True),
            sa.Column("author_name", sa.String(255), nullable=True),
            sa.Column("author_id", sa.String(36), sa.ForeignKey(f"{SCHEMA}.users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("status", sa.Enum("DRAFT", "PUBLISHED", "ARCHIVED", name="blogpoststatus", schema=SCHEMA), nullable=False, server_default="DRAFT"),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("site_id", "slug", name="uq_blog_posts_site_slug"),
            schema=SCHEMA,
        )
        op.create_index("idx_blog_posts_site_id", "blog_posts", ["site_id"], schema=SCHEMA)
        op.create_index("idx_blog_posts_status", "blog_posts", ["status"], schema=SCHEMA)
        op.create_index("idx_blog_posts_published_at", "blog_posts", ["published_at"], schema=SCHEMA)
        op.create_index("idx_blog_posts_category_id", "blog_posts", ["category_id"], schema=SCHEMA)
        op.create_index("idx_blog_posts_site_status", "blog_posts", ["site_id", "status"], schema=SCHEMA)

    # --- Seed the "blog" app ---
    conn.execute(sa.text(f"""
        INSERT INTO {SCHEMA}.apps (id, slug, name, description, icon_url, version, is_active, scopes, sidebar_links, created_at, updated_at)
        VALUES (
            :id, 'blog', 'Blogs by Qvicko',
            'Skapa och hantera blogginlägg för din webbplats. Publicera artiklar, organisera med kategorier och öka din synlighet online.',
            NULL, '1.0.0', true,
            :scopes,
            :sidebar_links,
            NOW(), NOW()
        )
        ON CONFLICT (slug) DO NOTHING
    """), {
        "id": BLOG_APP_ID,
        "scopes": '["blog:read", "blog:write"]',
        "sidebar_links": '[{"key": "posts", "href_suffix": "/posts", "icon": "M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"}, {"key": "categories", "href_suffix": "/categories", "icon": "M9.568 3H5.25A2.25 2.25 0 003 5.25v4.318c0 .597.237 1.17.659 1.591l9.581 9.581c.699.699 1.78.872 2.607.33a18.095 18.095 0 005.223-5.223c.542-.827.369-1.908-.33-2.607L11.16 3.66A2.25 2.25 0 009.568 3z M6 6h.008v.008H6V6z"}]',
    })


def downgrade() -> None:
    op.drop_table("blog_posts", schema=SCHEMA)
    op.drop_table("blog_categories", schema=SCHEMA)
    op.drop_table("app_installations", schema=SCHEMA)
    op.drop_table("apps", schema=SCHEMA)
    # Drop the enum type
    op.execute(f"DROP TYPE IF EXISTS {SCHEMA}.blogpoststatus")
