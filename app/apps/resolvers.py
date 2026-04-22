from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime, timezone

import nh3
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
    AppPricingType,
    AppReview,
    BlogCategory,
    BlogPost,
    BlogPostStatus,
    ChatConversation,
    ChatMessage,
)
from app.apps.graphql_types import (
    AppInstallationType,
    AppPricingTypeGQL,
    AppReviewType,
    AppType,
    BlogCategoryType,
    BlogPostFilterInput,
    BlogPostListType,
    BlogPostStatusGQL,
    BlogPostType,
    ChatConversationDetailType,
    ChatConversationFilterInput,
    ChatConversationListType,
    ChatConversationStatusGQL,
    ChatConversationType,
    ChatMessageType,
    ChatSenderTypeGQL,
    CreateAppReviewInput,
    CreateBlogCategoryInput,
    CreateBlogPostInput,
    DeleteAppReviewInput,
    InstallAppInput,
    SendChatReplyInput,
    UninstallAppInput,
    UpdateBlogCategoryInput,
    UpdateBlogPostInput,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BLOG_ALLOWED_TAGS = {
    "p", "br", "hr",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "strong", "b", "em", "i", "u", "s", "del",
    "ul", "ol", "li",
    "a", "img",
    "blockquote", "pre", "code",
    "figure", "figcaption",
    "table", "thead", "tbody", "tr", "th", "td",
    "div", "span",
}

_BLOG_ALLOWED_ATTRIBUTES: dict[str, set[str]] = {
    "*": {"class", "style"},
    "a": {"href", "target", "rel", "title"},
    "img": {"src", "alt", "title", "width", "height", "style"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
}

_BLOG_ALLOWED_URL_SCHEMES = {"http", "https", "mailto"}


def _sanitize_blog_html(html: str) -> str:
    """Sanitize user-supplied blog HTML to prevent XSS."""
    if not html:
        return html
    return nh3.clean(
        html,
        tags=_BLOG_ALLOWED_TAGS,
        attributes=_BLOG_ALLOWED_ATTRIBUTES,
        url_schemes=_BLOG_ALLOWED_URL_SCHEMES,
        link_rel=None,
    )


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


async def _require_chat_installed(site_id: str) -> None:
    """Verify the chat app is installed on the given site."""
    async with get_db_session() as db:
        result = await db.execute(
            select(AppInstallation)
            .join(App, AppInstallation.app_id == App.id)
            .where(
                App.slug == "chat",
                AppInstallation.site_id == site_id,
                AppInstallation.is_active == True,  # noqa: E712
            )
        )
        if result.scalar_one_or_none() is None:
            raise ValueError("Chat app is not installed on this site")


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


def _app_to_gql(app: App, avg_rating: float = 0, review_count: int = 0) -> AppType:
    return AppType(
        id=app.id,
        slug=app.slug,
        name=app.name,
        description=app.description,
        long_description=app.long_description,
        icon_url=app.icon_url,
        version=app.version,
        scopes=app.scopes,
        sidebar_links=app.sidebar_links,
        screenshots=app.screenshots,
        features=app.features,
        developer_name=app.developer_name,
        developer_url=app.developer_url,
        category=app.category,
        pricing_type=AppPricingTypeGQL(app.pricing_type.value) if app.pricing_type else AppPricingTypeGQL.FREE,
        price=float(app.price) if app.price else 0,
        price_description=app.price_description,
        install_count=app.install_count or 0,
        avg_rating=avg_rating,
        review_count=review_count,
    )


def _review_to_gql(review: AppReview, user_name: str = "") -> AppReviewType:
    return AppReviewType(
        id=review.id,
        app_id=review.app_id,
        user_id=review.user_id,
        user_name=user_name,
        site_id=review.site_id,
        rating=review.rating,
        title=review.title,
        body=review.body,
        locale=review.locale,
        created_at=review.created_at,
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


def _conversation_to_gql(
    conv: ChatConversation, message_count: int = 0, last_preview: str | None = None
) -> ChatConversationType:
    return ChatConversationType(
        id=conv.id,
        site_id=conv.site_id,
        visitor_email=conv.visitor_email,
        visitor_name=conv.visitor_name,
        status=ChatConversationStatusGQL(conv.status),
        subject=conv.subject,
        last_message_at=conv.last_message_at,
        message_count=message_count,
        last_message_preview=last_preview,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


def _message_to_gql(msg: ChatMessage) -> ChatMessageType:
    return ChatMessageType(
        id=msg.id,
        conversation_id=msg.conversation_id,
        sender_type=ChatSenderTypeGQL(msg.sender_type),
        sender_name=msg.sender_name,
        content=msg.content,
        created_at=msg.created_at,
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
                select(
                    App,
                    func.coalesce(func.avg(AppReview.rating), 0).label("avg_rating"),
                    func.count(AppReview.id).label("review_count"),
                )
                .outerjoin(AppReview, AppReview.app_id == App.id)
                .where(App.is_active == True)  # noqa: E712
                .group_by(App.id)
                .order_by(App.name)
            )
            return [
                _app_to_gql(a, float(avg), cnt)
                for a, avg, cnt in result.all()
            ]

    @strawberry.field
    async def app(self, info: Info, slug: str) -> AppType | None:
        async with get_db_session() as db:
            result = await db.execute(
                select(
                    App,
                    func.coalesce(func.avg(AppReview.rating), 0).label("avg_rating"),
                    func.count(AppReview.id).label("review_count"),
                )
                .outerjoin(AppReview, AppReview.app_id == App.id)
                .where(App.slug == slug, App.is_active == True)  # noqa: E712
                .group_by(App.id)
            )
            row = result.one_or_none()
            if row is None:
                return None
            app, avg, cnt = row
            return _app_to_gql(app, float(avg), cnt)

    @strawberry.field
    async def app_reviews(self, info: Info, app_slug: str) -> list[AppReviewType]:
        """List reviews for an app (public)."""
        async with get_db_session() as db:
            result = await db.execute(
                select(AppReview, User.full_name)
                .join(App, AppReview.app_id == App.id)
                .join(User, AppReview.user_id == User.id)
                .where(App.slug == app_slug)
                .order_by(AppReview.created_at.desc())
            )
            return [
                _review_to_gql(review, name or "Anonymous")
                for review, name in result.all()
            ]

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

    # -------------------------------------------------------------------
    # Chat
    # -------------------------------------------------------------------

    @strawberry.field
    async def chat_conversations(
        self, info: Info, site_id: str, filter: ChatConversationFilterInput | None = None
    ) -> ChatConversationListType:
        """List chat conversations for a site. Requires site ownership."""
        await _require_site_owner(info, site_id)
        f = filter or ChatConversationFilterInput()
        async with get_db_session() as db:
            # Subquery for message count & last message preview
            msg_count_sq = (
                select(
                    ChatMessage.conversation_id,
                    func.count(ChatMessage.id).label("msg_count"),
                )
                .group_by(ChatMessage.conversation_id)
                .subquery()
            )

            base = (
                select(ChatConversation, func.coalesce(msg_count_sq.c.msg_count, 0).label("msg_count"))
                .outerjoin(msg_count_sq, msg_count_sq.c.conversation_id == ChatConversation.id)
                .where(ChatConversation.site_id == site_id)
            )
            count_base = select(func.count(ChatConversation.id)).where(ChatConversation.site_id == site_id)

            if f.status:
                base = base.where(ChatConversation.status == f.status.value)
                count_base = count_base.where(ChatConversation.status == f.status.value)
            if f.search:
                pattern = f"%{f.search}%"
                search_filter = or_(
                    ChatConversation.visitor_email.ilike(pattern),
                    ChatConversation.visitor_name.ilike(pattern),
                    ChatConversation.subject.ilike(pattern),
                )
                base = base.where(search_filter)
                count_base = count_base.where(search_filter)

            total_result = await db.execute(count_base)
            total = total_result.scalar() or 0

            offset = (f.page - 1) * f.page_size
            result = await db.execute(
                base.order_by(ChatConversation.last_message_at.desc().nullslast(), ChatConversation.created_at.desc())
                .offset(offset)
                .limit(f.page_size)
            )
            rows = result.all()

            items = []
            for conv, msg_count in rows:
                # Get last message preview
                last_msg_result = await db.execute(
                    select(ChatMessage.content)
                    .where(ChatMessage.conversation_id == conv.id)
                    .order_by(ChatMessage.created_at.desc())
                    .limit(1)
                )
                last_msg = last_msg_result.scalar_one_or_none()
                preview = last_msg[:100] if last_msg else None
                items.append(_conversation_to_gql(conv, msg_count, preview))

            return ChatConversationListType(
                items=items,
                total=total,
                page=f.page,
                page_size=f.page_size,
            )

    @strawberry.field
    async def chat_conversation(
        self, info: Info, site_id: str, conversation_id: str
    ) -> ChatConversationDetailType | None:
        """Get a chat conversation with all messages. Requires site ownership."""
        await _require_site_owner(info, site_id)
        async with get_db_session() as db:
            from sqlalchemy.orm import selectinload
            result = await db.execute(
                select(ChatConversation)
                .options(selectinload(ChatConversation.messages))
                .where(
                    ChatConversation.id == conversation_id,
                    ChatConversation.site_id == site_id,
                )
            )
            conv = result.scalar_one_or_none()
            if conv is None:
                return None

            messages = sorted(conv.messages, key=lambda m: m.created_at)
            return ChatConversationDetailType(
                conversation=_conversation_to_gql(conv, len(messages)),
                messages=[_message_to_gql(m) for m in messages],
            )


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
    # App reviews
    # -----------------------------------------------------------------------

    @strawberry.mutation
    async def create_app_review(self, info: Info, input: CreateAppReviewInput) -> AppReviewType:
        """Create a review. Requires the app to be installed on the user's site."""
        user = await _require_site_owner(info, input.site_id)
        if input.rating < 1 or input.rating > 5:
            raise ValueError("Rating must be between 1 and 5")

        async with get_db_session() as db:
            # Verify app exists
            app_result = await db.execute(
                select(App).where(App.slug == input.app_slug, App.is_active == True)  # noqa: E712
            )
            app = app_result.scalar_one_or_none()
            if app is None:
                raise ValueError(f"App '{input.app_slug}' not found")

            # Verify app is installed on this site
            inst_result = await db.execute(
                select(AppInstallation).where(
                    AppInstallation.app_id == app.id,
                    AppInstallation.site_id == input.site_id,
                    AppInstallation.is_active == True,  # noqa: E712
                )
            )
            if inst_result.scalar_one_or_none() is None:
                raise ValueError("You must have this app installed to leave a review")

            # Check for existing review
            existing = await db.execute(
                select(AppReview).where(
                    AppReview.app_id == app.id,
                    AppReview.user_id == str(user.id),
                    AppReview.site_id == input.site_id,
                )
            )
            if existing.scalar_one_or_none():
                raise ValueError("You have already reviewed this app for this site")

            review = AppReview(
                app_id=app.id,
                user_id=str(user.id),
                site_id=input.site_id,
                rating=input.rating,
                title=input.title,
                body=input.body,
                locale=input.locale,
            )
            db.add(review)
            await db.flush()
            return _review_to_gql(review, user.full_name or "Anonymous")

    @strawberry.mutation
    async def delete_app_review(self, info: Info, input: DeleteAppReviewInput) -> bool:
        """Delete own review."""
        user = _require_user(await _get_user_from_info(info))
        async with get_db_session() as db:
            result = await db.execute(
                select(AppReview).where(AppReview.id == input.review_id)
            )
            review = result.scalar_one_or_none()
            if review is None:
                raise ValueError("Review not found")
            if review.user_id != str(user.id) and not user.is_superuser:
                raise PermissionError("You can only delete your own reviews")
            await db.delete(review)
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
                content=_sanitize_blog_html(input.content),
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
                post.content = _sanitize_blog_html(input.content)
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


    # -----------------------------------------------------------------------
    # Chat
    # -----------------------------------------------------------------------

    @strawberry.mutation
    async def send_chat_reply(self, info: Info, input: SendChatReplyInput) -> ChatMessageType:
        """Send a reply to a chat conversation as the site owner (agent)."""
        user = await _require_site_owner(info, input.site_id)
        await _require_chat_installed(input.site_id)

        content = input.content.strip()
        if not content:
            raise ValueError("Message content cannot be empty")
        if len(content) > 5000:
            raise ValueError("Message content is too long (max 5000 characters)")

        async with get_db_session() as db:
            result = await db.execute(
                select(ChatConversation).where(
                    ChatConversation.id == input.conversation_id,
                    ChatConversation.site_id == input.site_id,
                )
            )
            conv = result.scalar_one_or_none()
            if conv is None:
                raise ValueError("Conversation not found")

            now = datetime.now(timezone.utc)
            msg = ChatMessage(
                conversation_id=conv.id,
                sender_type="agent",
                sender_name=user.full_name or "Support",
                content=content,
            )
            db.add(msg)
            conv.last_message_at = now
            conv.updated_at = now
            if conv.status == "closed":
                conv.status = "open"
            await db.flush()

            # Send email notification to visitor
            try:
                from app.email.service import send_transactional_email
                from app.sites.models import GeneratedSite
                site_result = await db.execute(
                    select(GeneratedSite).where(GeneratedSite.id == input.site_id)
                )
                site = site_result.scalar_one_or_none()
                site_name = "din webbplats"
                if site and site.site_data:
                    site_name = site.site_data.get("business", {}).get("name") or site.site_data.get("meta", {}).get("title") or site_name

                await send_transactional_email(
                    to=conv.visitor_email,
                    subject=f"Nytt svar från {site_name}",
                    html=f"""
                    <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
                        <h2 style="color: #333;">Nytt svar på ditt meddelande</h2>
                        <div style="background: #f7f7f7; padding: 16px; border-radius: 8px; margin: 16px 0;">
                            <p style="margin: 0; color: #555;">{content}</p>
                        </div>
                        <p style="color: #888; font-size: 14px;">
                            Du kan svara direkt genom att besöka webbplatsen igen.
                        </p>
                        <hr style="border: none; border-top: 1px solid #eee; margin: 24px 0;" />
                        <p style="color: #aaa; font-size: 12px;">Chat by Qvicko</p>
                    </div>
                    """,
                    text=f"Nytt svar från {site_name}:\n\n{content}\n\n---\nChat by Qvicko",
                    from_name="Chat by Qvicko",
                )
            except Exception:
                logger.exception("Failed to send chat reply notification email")

            return _message_to_gql(msg)

    @strawberry.mutation
    async def close_chat_conversation(self, info: Info, site_id: str, conversation_id: str) -> bool:
        """Close a chat conversation."""
        await _require_site_owner(info, site_id)
        async with get_db_session() as db:
            result = await db.execute(
                select(ChatConversation).where(
                    ChatConversation.id == conversation_id,
                    ChatConversation.site_id == site_id,
                )
            )
            conv = result.scalar_one_or_none()
            if conv is None:
                raise ValueError("Conversation not found")
            conv.status = "closed"
            conv.updated_at = datetime.now(timezone.utc)
        return True

    @strawberry.mutation
    async def reopen_chat_conversation(self, info: Info, site_id: str, conversation_id: str) -> bool:
        """Reopen a closed chat conversation."""
        await _require_site_owner(info, site_id)
        async with get_db_session() as db:
            result = await db.execute(
                select(ChatConversation).where(
                    ChatConversation.id == conversation_id,
                    ChatConversation.site_id == site_id,
                )
            )
            conv = result.scalar_one_or_none()
            if conv is None:
                raise ValueError("Conversation not found")
            conv.status = "open"
            conv.updated_at = datetime.now(timezone.utc)
        return True


# Fix missing import
from uuid import uuid4  # noqa: E402
