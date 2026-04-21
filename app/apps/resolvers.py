from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime, timezone

import strawberry
from sqlalchemy import func, select, or_
from strawberry.types import Info

from app.auth.models import User
from app.auth.resolvers import _get_user_from_info, _require_user
from app.database import get_db_session
from app.sites.models import GeneratedSite, Lead

from app.apps.models import (
    App,
    AppInstallation,
    BlogCategory,
    BlogPost,
    BlogPostStatus,
)
from app.apps.graphql_types import (
    AppInstallationType,
    AppType,
    BlogCategoryType,
    BlogPostFilterInput,
    BlogPostListType,
    BlogPostStatusGQL,
    BlogPostType,
    CreateBlogCategoryInput,
    CreateBlogPostInput,
    InstallAppInput,
    UninstallAppInput,
    UpdateBlogCategoryInput,
    UpdateBlogPostInput,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    """Generate a URL-safe slug from text."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text)
    return text.strip("-") or "untitled"


async def _require_site_owner(info: Info, site_id: str) -> User:
    """Verify the current user owns the given site."""
    user = _require_user(await _get_user_from_info(info))
    async with get_db_session() as db:
        result = await db.execute(
            select(GeneratedSite).where(GeneratedSite.id == site_id)
        )
        site = result.scalar_one_or_none()
        if site is None:
            raise ValueError("Site not found")
        if not user.is_superuser and site.claimed_by != str(user.id):
            # Also check if user created the lead
            lead_result = await db.execute(
                select(Lead).where(Lead.id == site.lead_id)
            )
            lead = lead_result.scalar_one_or_none()
            if not lead or lead.created_by != str(user.id):
                raise PermissionError("You do not own this site")
    return user


async def _require_blog_installed(site_id: str) -> None:
    """Verify the blog app is installed on the given site."""
    async with get_db_session() as db:
        result = await db.execute(
            select(AppInstallation)
            .join(App, AppInstallation.app_id == App.id)
            .where(
                App.slug == "blog",
                AppInstallation.site_id == site_id,
                AppInstallation.is_active == True,  # noqa: E712
            )
        )
        if result.scalar_one_or_none() is None:
            raise ValueError("Blog app is not installed on this site")


def _app_to_gql(app: App) -> AppType:
    return AppType(
        id=app.id,
        slug=app.slug,
        name=app.name,
        description=app.description,
        icon_url=app.icon_url,
        version=app.version,
        scopes=app.scopes,
        sidebar_links=app.sidebar_links,
    )


def _installation_to_gql(inst: AppInstallation) -> AppInstallationType:
    return AppInstallationType(
        id=inst.id,
        app_id=inst.app_id,
        app_slug=inst.app.slug,
        app_name=inst.app.name,
        site_id=inst.site_id,
        is_active=inst.is_active,
        settings=inst.settings,
        sidebar_links=inst.app.sidebar_links,
        installed_at=inst.installed_at,
    )


def _post_to_gql(post: BlogPost) -> BlogPostType:
    return BlogPostType(
        id=post.id,
        site_id=post.site_id,
        title=post.title,
        slug=post.slug,
        excerpt=post.excerpt,
        content=post.content,
        featured_image=post.featured_image,
        author_name=post.author_name,
        author_id=post.author_id,
        category_id=post.category_id,
        category_name=post.category.name if post.category else None,
        status=BlogPostStatusGQL(post.status.value),
        published_at=post.published_at,
        created_at=post.created_at,
        updated_at=post.updated_at,
    )


def _category_to_gql(cat: BlogCategory, post_count: int = 0) -> BlogCategoryType:
    return BlogCategoryType(
        id=cat.id,
        site_id=cat.site_id,
        name=cat.name,
        slug=cat.slug,
        description=cat.description,
        sort_order=cat.sort_order,
        post_count=post_count,
        created_at=cat.created_at,
        updated_at=cat.updated_at,
    )


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

@strawberry.type
class Query:

    @strawberry.field
    async def apps(self, info: Info) -> list[AppType]:
        """List all active apps from the catalog."""
        async with get_db_session() as db:
            result = await db.execute(
                select(App).where(App.is_active == True).order_by(App.name)  # noqa: E712
            )
            return [_app_to_gql(a) for a in result.scalars().all()]

    @strawberry.field
    async def app(self, info: Info, slug: str) -> AppType | None:
        async with get_db_session() as db:
            result = await db.execute(
                select(App).where(App.slug == slug, App.is_active == True)  # noqa: E712
            )
            app = result.scalar_one_or_none()
            return _app_to_gql(app) if app else None

    @strawberry.field
    async def site_apps(self, info: Info, site_id: str) -> list[AppInstallationType]:
        """List installed apps for a site. Requires site ownership."""
        await _require_site_owner(info, site_id)
        async with get_db_session() as db:
            from sqlalchemy.orm import selectinload
            result = await db.execute(
                select(AppInstallation)
                .options(selectinload(AppInstallation.app))
                .where(
                    AppInstallation.site_id == site_id,
                    AppInstallation.is_active == True,  # noqa: E712
                )
                .order_by(AppInstallation.installed_at)
            )
            return [_installation_to_gql(i) for i in result.scalars().all()]

    @strawberry.field
    async def blog_posts(
        self, info: Info, site_id: str, filter: BlogPostFilterInput | None = None
    ) -> BlogPostListType:
        """List blog posts for a site. Requires site ownership."""
        await _require_site_owner(info, site_id)
        f = filter or BlogPostFilterInput()
        async with get_db_session() as db:
            from sqlalchemy.orm import selectinload
            base = (
                select(BlogPost)
                .options(selectinload(BlogPost.category))
                .where(BlogPost.site_id == site_id)
            )
            count_base = select(func.count(BlogPost.id)).where(BlogPost.site_id == site_id)

            if f.status:
                base = base.where(BlogPost.status == BlogPostStatus(f.status.value))
                count_base = count_base.where(BlogPost.status == BlogPostStatus(f.status.value))
            if f.category_id:
                base = base.where(BlogPost.category_id == f.category_id)
                count_base = count_base.where(BlogPost.category_id == f.category_id)
            if f.search:
                pattern = f"%{f.search}%"
                search_filter = or_(
                    BlogPost.title.ilike(pattern),
                    BlogPost.excerpt.ilike(pattern),
                )
                base = base.where(search_filter)
                count_base = count_base.where(search_filter)

            total_result = await db.execute(count_base)
            total = total_result.scalar() or 0

            offset = (f.page - 1) * f.page_size
            result = await db.execute(
                base.order_by(BlogPost.created_at.desc())
                .offset(offset)
                .limit(f.page_size)
            )
            posts = result.scalars().all()
            return BlogPostListType(
                items=[_post_to_gql(p) for p in posts],
                total=total,
                page=f.page,
                page_size=f.page_size,
            )

    @strawberry.field
    async def blog_post(self, info: Info, site_id: str, post_id: str) -> BlogPostType | None:
        await _require_site_owner(info, site_id)
        async with get_db_session() as db:
            from sqlalchemy.orm import selectinload
            result = await db.execute(
                select(BlogPost)
                .options(selectinload(BlogPost.category))
                .where(BlogPost.id == post_id, BlogPost.site_id == site_id)
            )
            post = result.scalar_one_or_none()
            return _post_to_gql(post) if post else None

    @strawberry.field
    async def blog_categories(self, info: Info, site_id: str) -> list[BlogCategoryType]:
        await _require_site_owner(info, site_id)
        async with get_db_session() as db:
            # Get categories with post count
            result = await db.execute(
                select(BlogCategory, func.count(BlogPost.id).label("post_count"))
                .outerjoin(BlogPost, BlogPost.category_id == BlogCategory.id)
                .where(BlogCategory.site_id == site_id)
                .group_by(BlogCategory.id)
                .order_by(BlogCategory.sort_order, BlogCategory.name)
            )
            return [
                _category_to_gql(cat, count)
                for cat, count in result.all()
            ]


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------

@strawberry.type
class Mutation:

    @strawberry.mutation
    async def install_app(self, info: Info, input: InstallAppInput) -> AppInstallationType:
        user = await _require_site_owner(info, input.site_id)
        async with get_db_session() as db:
            from sqlalchemy.orm import selectinload
            # Find the app
            app_result = await db.execute(
                select(App).where(App.slug == input.app_slug, App.is_active == True)  # noqa: E712
            )
            app = app_result.scalar_one_or_none()
            if app is None:
                raise ValueError(f"App '{input.app_slug}' not found")

            # Check not already installed
            existing = await db.execute(
                select(AppInstallation).where(
                    AppInstallation.app_id == app.id,
                    AppInstallation.site_id == input.site_id,
                )
            )
            inst = existing.scalar_one_or_none()
            if inst is not None:
                if inst.is_active:
                    raise ValueError("App is already installed on this site")
                # Re-activate
                inst.is_active = True
                inst.updated_at = datetime.now(timezone.utc)
                await db.flush()
                # Reload with app relationship
                result = await db.execute(
                    select(AppInstallation)
                    .options(selectinload(AppInstallation.app))
                    .where(AppInstallation.id == inst.id)
                )
                inst = result.scalar_one()
                return _installation_to_gql(inst)

            inst = AppInstallation(
                app_id=app.id,
                site_id=input.site_id,
                installed_by=str(user.id),
            )
            db.add(inst)
            await db.flush()
            # Reload with app relationship
            result = await db.execute(
                select(AppInstallation)
                .options(selectinload(AppInstallation.app))
                .where(AppInstallation.id == inst.id)
            )
            inst = result.scalar_one()
            return _installation_to_gql(inst)

    @strawberry.mutation
    async def uninstall_app(self, info: Info, input: UninstallAppInput) -> bool:
        await _require_site_owner(info, input.site_id)
        async with get_db_session() as db:
            result = await db.execute(
                select(AppInstallation)
                .join(App, AppInstallation.app_id == App.id)
                .where(
                    App.slug == input.app_slug,
                    AppInstallation.site_id == input.site_id,
                    AppInstallation.is_active == True,  # noqa: E712
                )
            )
            inst = result.scalar_one_or_none()
            if inst is None:
                raise ValueError("App is not installed on this site")
            inst.is_active = False
            inst.updated_at = datetime.now(timezone.utc)
        return True

    # -----------------------------------------------------------------------
    # Blog posts
    # -----------------------------------------------------------------------

    @strawberry.mutation
    async def create_blog_post(self, info: Info, input: CreateBlogPostInput) -> BlogPostType:
        user = await _require_site_owner(info, input.site_id)
        await _require_blog_installed(input.site_id)

        slug = input.slug or _slugify(input.title)

        async with get_db_session() as db:
            from sqlalchemy.orm import selectinload
            # Ensure slug uniqueness
            existing = await db.execute(
                select(BlogPost).where(
                    BlogPost.site_id == input.site_id,
                    BlogPost.slug == slug,
                )
            )
            if existing.scalar_one_or_none():
                slug = f"{slug}-{str(uuid4())[:8]}"

            published_at = None
            if input.status == BlogPostStatusGQL.PUBLISHED:
                published_at = datetime.now(timezone.utc)

            post = BlogPost(
                site_id=input.site_id,
                title=input.title,
                slug=slug,
                content=input.content,
                excerpt=input.excerpt,
                featured_image=input.featured_image,
                category_id=input.category_id,
                author_id=str(user.id),
                author_name=user.full_name,
                status=BlogPostStatus(input.status.value),
                published_at=published_at,
            )
            db.add(post)
            await db.flush()
            # Reload with category
            result = await db.execute(
                select(BlogPost)
                .options(selectinload(BlogPost.category))
                .where(BlogPost.id == post.id)
            )
            post = result.scalar_one()
            return _post_to_gql(post)

    @strawberry.mutation
    async def update_blog_post(self, info: Info, input: UpdateBlogPostInput) -> BlogPostType:
        await _require_site_owner(info, input.site_id)
        async with get_db_session() as db:
            from sqlalchemy.orm import selectinload
            result = await db.execute(
                select(BlogPost)
                .options(selectinload(BlogPost.category))
                .where(BlogPost.id == input.id, BlogPost.site_id == input.site_id)
            )
            post = result.scalar_one_or_none()
            if post is None:
                raise ValueError("Blog post not found")

            if input.title is not None:
                post.title = input.title
            if input.slug is not None:
                # Verify slug uniqueness
                existing = await db.execute(
                    select(BlogPost).where(
                        BlogPost.site_id == input.site_id,
                        BlogPost.slug == input.slug,
                        BlogPost.id != input.id,
                    )
                )
                if existing.scalar_one_or_none():
                    raise ValueError(f"Slug '{input.slug}' is already in use")
                post.slug = input.slug
            if input.content is not None:
                post.content = input.content
            if input.excerpt is not None:
                post.excerpt = input.excerpt
            if input.featured_image is not None:
                post.featured_image = input.featured_image
            if input.category_id is not None:
                post.category_id = input.category_id if input.category_id else None
            if input.status is not None:
                new_status = BlogPostStatus(input.status.value)
                if new_status == BlogPostStatus.PUBLISHED and post.published_at is None:
                    post.published_at = datetime.now(timezone.utc)
                post.status = new_status

            post.updated_at = datetime.now(timezone.utc)
            await db.flush()
            # Reload
            result = await db.execute(
                select(BlogPost)
                .options(selectinload(BlogPost.category))
                .where(BlogPost.id == post.id)
            )
            post = result.scalar_one()
            return _post_to_gql(post)

    @strawberry.mutation
    async def delete_blog_post(self, info: Info, site_id: str, post_id: str) -> bool:
        await _require_site_owner(info, site_id)
        async with get_db_session() as db:
            result = await db.execute(
                select(BlogPost).where(BlogPost.id == post_id, BlogPost.site_id == site_id)
            )
            post = result.scalar_one_or_none()
            if post is None:
                raise ValueError("Blog post not found")
            await db.delete(post)
        return True

    # -----------------------------------------------------------------------
    # Blog categories
    # -----------------------------------------------------------------------

    @strawberry.mutation
    async def create_blog_category(self, info: Info, input: CreateBlogCategoryInput) -> BlogCategoryType:
        await _require_site_owner(info, input.site_id)
        await _require_blog_installed(input.site_id)

        slug = input.slug or _slugify(input.name)

        async with get_db_session() as db:
            existing = await db.execute(
                select(BlogCategory).where(
                    BlogCategory.site_id == input.site_id,
                    BlogCategory.slug == slug,
                )
            )
            if existing.scalar_one_or_none():
                raise ValueError(f"Category slug '{slug}' already exists")

            cat = BlogCategory(
                site_id=input.site_id,
                name=input.name,
                slug=slug,
                description=input.description,
            )
            db.add(cat)
            await db.flush()
            return _category_to_gql(cat, 0)

    @strawberry.mutation
    async def update_blog_category(self, info: Info, input: UpdateBlogCategoryInput) -> BlogCategoryType:
        await _require_site_owner(info, input.site_id)
        async with get_db_session() as db:
            result = await db.execute(
                select(BlogCategory).where(
                    BlogCategory.id == input.id,
                    BlogCategory.site_id == input.site_id,
                )
            )
            cat = result.scalar_one_or_none()
            if cat is None:
                raise ValueError("Category not found")

            if input.name is not None:
                cat.name = input.name
            if input.slug is not None:
                existing = await db.execute(
                    select(BlogCategory).where(
                        BlogCategory.site_id == input.site_id,
                        BlogCategory.slug == input.slug,
                        BlogCategory.id != input.id,
                    )
                )
                if existing.scalar_one_or_none():
                    raise ValueError(f"Category slug '{input.slug}' already exists")
                cat.slug = input.slug
            if input.description is not None:
                cat.description = input.description

            cat.updated_at = datetime.now(timezone.utc)
            await db.flush()

            # Get post count
            count_result = await db.execute(
                select(func.count(BlogPost.id)).where(BlogPost.category_id == cat.id)
            )
            count = count_result.scalar() or 0
            return _category_to_gql(cat, count)

    @strawberry.mutation
    async def delete_blog_category(self, info: Info, site_id: str, category_id: str) -> bool:
        await _require_site_owner(info, site_id)
        async with get_db_session() as db:
            result = await db.execute(
                select(BlogCategory).where(
                    BlogCategory.id == category_id,
                    BlogCategory.site_id == site_id,
                )
            )
            cat = result.scalar_one_or_none()
            if cat is None:
                raise ValueError("Category not found")
            await db.delete(cat)
        return True


# Fix missing import
from uuid import uuid4  # noqa: E402
