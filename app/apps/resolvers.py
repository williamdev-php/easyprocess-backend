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
    Booking,
    BookingFormField,
    BookingPaymentMethods,
    BookingPaymentStatus,
    BookingService,
    BookingStatus,
    ChatConversation,
    ChatMessage,
)
from app.payments.models import ConnectedAccount
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
    BookingFilterInput,
    BookingListType,
    BookingPaymentMethodsType,
    BookingPaymentStatusGQL,
    BookingServiceType,
    BookingStatsType,
    BookingStatusGQL,
    BookingType,
    BookingFormFieldType,
    ChatConversationDetailType,
    ChatConversationFilterInput,
    ChatConversationListType,
    ChatConversationStatusGQL,
    ChatConversationType,
    ChatMessageType,
    ChatSenderTypeGQL,
    ConnectedAccountType,
    CreateAppReviewInput,
    CreateBlogCategoryInput,
    CreateBlogPostInput,
    CreateBookingFormFieldInput,
    CreateBookingServiceInput,
    DeleteAppReviewInput,
    InstallAppInput,
    SendChatReplyInput,
    UninstallAppInput,
    UpdateBlogCategoryInput,
    UpdateBlogPostInput,
    UpdateBookingFormFieldInput,
    UpdateBookingPaymentMethodsInput,
    UpdateBookingServiceInput,
    UpdateBookingStatusInput,
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
        requires_payments=app.requires_payments,
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
        requires_payments=inst.app.requires_payments,
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


async def _require_bookings_installed(site_id: str) -> None:
    """Verify the bookings app is installed on the given site."""
    async with get_db_session() as db:
        result = await db.execute(
            select(AppInstallation)
            .join(App, AppInstallation.app_id == App.id)
            .where(
                App.slug == "bookings",
                AppInstallation.site_id == site_id,
                AppInstallation.is_active == True,  # noqa: E712
            )
        )
        if result.scalar_one_or_none() is None:
            raise ValueError("Bookings app is not installed on this site")


def _service_to_gql(service: BookingService) -> BookingServiceType:
    return BookingServiceType(
        id=service.id,
        site_id=service.site_id,
        name=service.name,
        description=service.description,
        duration_minutes=service.duration_minutes,
        price=float(service.price) if service.price else 0,
        currency=service.currency,
        is_active=service.is_active,
        sort_order=service.sort_order,
        created_at=service.created_at,
        updated_at=service.updated_at,
    )


def _form_field_to_gql(field: BookingFormField) -> BookingFormFieldType:
    return BookingFormFieldType(
        id=field.id,
        site_id=field.site_id,
        label=field.label,
        field_type=field.field_type,
        placeholder=field.placeholder,
        is_required=field.is_required,
        options=field.options,
        sort_order=field.sort_order,
        is_active=field.is_active,
        created_at=field.created_at,
        updated_at=field.updated_at,
    )


def _payment_methods_to_gql(pm: BookingPaymentMethods) -> BookingPaymentMethodsType:
    return BookingPaymentMethodsType(
        id=pm.id,
        site_id=pm.site_id,
        stripe_connect_enabled=pm.stripe_connect_enabled,
        on_site_enabled=pm.on_site_enabled,
        klarna_enabled=pm.klarna_enabled,
        swish_enabled=pm.swish_enabled,
        created_at=pm.created_at,
        updated_at=pm.updated_at,
    )


def _booking_to_gql(booking: Booking) -> BookingType:
    return BookingType(
        id=booking.id,
        site_id=booking.site_id,
        service_id=booking.service_id,
        service_name=booking.service_name if hasattr(booking, "service_name") and booking.service_name else (booking.service.name if booking.service else None),
        customer_name=booking.customer_name,
        customer_email=booking.customer_email,
        customer_phone=booking.customer_phone,
        form_data=booking.form_data,
        status=BookingStatusGQL(booking.status.value),
        payment_method=booking.payment_method,
        payment_status=BookingPaymentStatusGQL(booking.payment_status.value),
        stripe_payment_intent_id=booking.stripe_payment_intent_id,
        amount=float(booking.amount) if booking.amount else 0,
        currency=booking.currency,
        notes=booking.notes,
        booking_date=booking.booking_date,
        created_at=booking.created_at,
        updated_at=booking.updated_at,
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

    # -------------------------------------------------------------------
    # Bookings
    # -------------------------------------------------------------------

    @strawberry.field
    async def booking_services(self, info: Info, site_id: str) -> list[BookingServiceType]:
        """List booking services for a site. Requires site ownership."""
        await _require_site_owner(info, site_id)
        await _require_bookings_installed(site_id)
        async with get_db_session() as db:
            result = await db.execute(
                select(BookingService)
                .where(BookingService.site_id == site_id)
                .order_by(BookingService.sort_order, BookingService.name)
            )
            return [_service_to_gql(s) for s in result.scalars().all()]

    @strawberry.field
    async def booking_form_fields(self, info: Info, site_id: str) -> list[BookingFormFieldType]:
        """List booking form fields for a site. Requires site ownership."""
        await _require_site_owner(info, site_id)
        await _require_bookings_installed(site_id)
        async with get_db_session() as db:
            result = await db.execute(
                select(BookingFormField)
                .where(BookingFormField.site_id == site_id)
                .order_by(BookingFormField.sort_order, BookingFormField.label)
            )
            return [_form_field_to_gql(f) for f in result.scalars().all()]

    @strawberry.field
    async def booking_payment_methods(self, info: Info, site_id: str) -> BookingPaymentMethodsType:
        """Get payment methods config for a site. Requires site ownership."""
        await _require_site_owner(info, site_id)
        await _require_bookings_installed(site_id)
        async with get_db_session() as db:
            result = await db.execute(
                select(BookingPaymentMethods)
                .where(BookingPaymentMethods.site_id == site_id)
            )
            pm = result.scalar_one_or_none()
            if pm is None:
                pm = BookingPaymentMethods(site_id=site_id)
                db.add(pm)
                await db.flush()
            return _payment_methods_to_gql(pm)

    @strawberry.field
    async def bookings(
        self, info: Info, site_id: str, filter: BookingFilterInput | None = None
    ) -> BookingListType:
        """List bookings for a site with filtering. Requires site ownership."""
        await _require_site_owner(info, site_id)
        await _require_bookings_installed(site_id)
        f = filter or BookingFilterInput()
        async with get_db_session() as db:
            from sqlalchemy.orm import selectinload
            base = (
                select(Booking)
                .options(selectinload(Booking.service))
                .where(Booking.site_id == site_id)
            )
            count_base = select(func.count(Booking.id)).where(Booking.site_id == site_id)

            if f.status:
                base = base.where(Booking.status == BookingStatus(f.status.value))
                count_base = count_base.where(Booking.status == BookingStatus(f.status.value))
            if f.payment_status:
                base = base.where(Booking.payment_status == BookingPaymentStatus(f.payment_status.value))
                count_base = count_base.where(Booking.payment_status == BookingPaymentStatus(f.payment_status.value))
            if f.search:
                pattern = f"%{f.search}%"
                search_filter = or_(
                    Booking.customer_name.ilike(pattern),
                    Booking.customer_email.ilike(pattern),
                )
                base = base.where(search_filter)
                count_base = count_base.where(search_filter)

            total_result = await db.execute(count_base)
            total = total_result.scalar() or 0

            offset = (f.page - 1) * f.page_size
            result = await db.execute(
                base.order_by(Booking.created_at.desc())
                .offset(offset)
                .limit(f.page_size)
            )
            bookings = result.scalars().all()
            return BookingListType(
                items=[_booking_to_gql(b) for b in bookings],
                total=total,
                page=f.page,
                page_size=f.page_size,
            )

    @strawberry.field
    async def booking(self, info: Info, site_id: str, booking_id: str) -> BookingType | None:
        """Get a single booking. Requires site ownership."""
        await _require_site_owner(info, site_id)
        async with get_db_session() as db:
            from sqlalchemy.orm import selectinload
            result = await db.execute(
                select(Booking)
                .options(selectinload(Booking.service))
                .where(Booking.id == booking_id, Booking.site_id == site_id)
            )
            booking = result.scalar_one_or_none()
            return _booking_to_gql(booking) if booking else None

    @strawberry.field
    async def booking_stats(self, info: Info, site_id: str) -> BookingStatsType:
        """Get aggregate booking stats. Requires site ownership."""
        await _require_site_owner(info, site_id)
        await _require_bookings_installed(site_id)
        async with get_db_session() as db:
            # Total count
            total_result = await db.execute(
                select(func.count(Booking.id)).where(Booking.site_id == site_id)
            )
            total = total_result.scalar() or 0

            # Counts by status
            status_result = await db.execute(
                select(Booking.status, func.count(Booking.id))
                .where(Booking.site_id == site_id)
                .group_by(Booking.status)
            )
            status_counts = {row[0]: row[1] for row in status_result.all()}

            # Total revenue (from PAID bookings)
            revenue_result = await db.execute(
                select(func.coalesce(func.sum(Booking.amount), 0))
                .where(
                    Booking.site_id == site_id,
                    Booking.payment_status == BookingPaymentStatus.PAID,
                )
            )
            total_revenue = float(revenue_result.scalar() or 0)

            # Get default currency from first booking or default
            currency_result = await db.execute(
                select(Booking.currency)
                .where(Booking.site_id == site_id)
                .limit(1)
            )
            currency = currency_result.scalar_one_or_none() or "SEK"

            return BookingStatsType(
                total_bookings=total,
                pending_count=status_counts.get(BookingStatus.PENDING, 0),
                confirmed_count=status_counts.get(BookingStatus.CONFIRMED, 0),
                completed_count=status_counts.get(BookingStatus.COMPLETED, 0),
                cancelled_count=status_counts.get(BookingStatus.CANCELLED, 0),
                total_revenue=total_revenue,
                currency=currency,
            )

    @strawberry.field
    async def connected_account(self, info: Info, site_id: str) -> ConnectedAccountType | None:
        """Get Stripe Connect account status. Requires site ownership."""
        await _require_site_owner(info, site_id)
        async with get_db_session() as db:
            result = await db.execute(
                select(ConnectedAccount).where(ConnectedAccount.site_id == site_id)
            )
            acct = result.scalar_one_or_none()
            if acct is None:
                return None
            return ConnectedAccountType(
                id=acct.id,
                site_id=acct.site_id,
                stripe_account_id=acct.stripe_account_id,
                onboarding_status=acct.onboarding_status,
                charges_enabled=acct.charges_enabled,
                payouts_enabled=acct.payouts_enabled,
                details_submitted=acct.details_submitted,
                country=acct.country,
                created_at=acct.created_at,
                updated_at=acct.updated_at,
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

    # -----------------------------------------------------------------------
    # Booking services
    # -----------------------------------------------------------------------

    @strawberry.mutation
    async def create_booking_service(self, info: Info, input: CreateBookingServiceInput) -> BookingServiceType:
        await _require_site_owner(info, input.site_id)
        await _require_bookings_installed(input.site_id)
        async with get_db_session() as db:
            service = BookingService(
                site_id=input.site_id,
                name=input.name,
                description=input.description,
                duration_minutes=input.duration_minutes,
                price=input.price,
                currency=input.currency,
            )
            db.add(service)
            await db.flush()
            return _service_to_gql(service)

    @strawberry.mutation
    async def update_booking_service(self, info: Info, input: UpdateBookingServiceInput) -> BookingServiceType:
        await _require_site_owner(info, input.site_id)
        async with get_db_session() as db:
            result = await db.execute(
                select(BookingService).where(
                    BookingService.id == input.id,
                    BookingService.site_id == input.site_id,
                )
            )
            service = result.scalar_one_or_none()
            if service is None:
                raise ValueError("Booking service not found")

            if input.name is not None:
                service.name = input.name
            if input.description is not None:
                service.description = input.description
            if input.duration_minutes is not None:
                service.duration_minutes = input.duration_minutes
            if input.price is not None:
                service.price = input.price
            if input.currency is not None:
                service.currency = input.currency
            if input.is_active is not None:
                service.is_active = input.is_active
            if input.sort_order is not None:
                service.sort_order = input.sort_order

            service.updated_at = datetime.now(timezone.utc)
            await db.flush()
            return _service_to_gql(service)

    @strawberry.mutation
    async def delete_booking_service(self, info: Info, site_id: str, service_id: str) -> bool:
        await _require_site_owner(info, site_id)
        async with get_db_session() as db:
            result = await db.execute(
                select(BookingService).where(
                    BookingService.id == service_id,
                    BookingService.site_id == site_id,
                )
            )
            service = result.scalar_one_or_none()
            if service is None:
                raise ValueError("Booking service not found")
            await db.delete(service)
        return True

    # -----------------------------------------------------------------------
    # Booking form fields
    # -----------------------------------------------------------------------

    @strawberry.mutation
    async def create_booking_form_field(self, info: Info, input: CreateBookingFormFieldInput) -> BookingFormFieldType:
        await _require_site_owner(info, input.site_id)
        await _require_bookings_installed(input.site_id)
        async with get_db_session() as db:
            field = BookingFormField(
                site_id=input.site_id,
                label=input.label,
                field_type=input.field_type,
                placeholder=input.placeholder,
                is_required=input.is_required,
                options=input.options,
            )
            db.add(field)
            await db.flush()
            return _form_field_to_gql(field)

    @strawberry.mutation
    async def update_booking_form_field(self, info: Info, input: UpdateBookingFormFieldInput) -> BookingFormFieldType:
        await _require_site_owner(info, input.site_id)
        async with get_db_session() as db:
            result = await db.execute(
                select(BookingFormField).where(
                    BookingFormField.id == input.id,
                    BookingFormField.site_id == input.site_id,
                )
            )
            field = result.scalar_one_or_none()
            if field is None:
                raise ValueError("Booking form field not found")

            if input.label is not None:
                field.label = input.label
            if input.field_type is not None:
                field.field_type = input.field_type
            if input.placeholder is not None:
                field.placeholder = input.placeholder
            if input.is_required is not None:
                field.is_required = input.is_required
            if input.options is not None:
                field.options = input.options
            if input.sort_order is not None:
                field.sort_order = input.sort_order
            if input.is_active is not None:
                field.is_active = input.is_active

            field.updated_at = datetime.now(timezone.utc)
            await db.flush()
            return _form_field_to_gql(field)

    @strawberry.mutation
    async def delete_booking_form_field(self, info: Info, site_id: str, field_id: str) -> bool:
        await _require_site_owner(info, site_id)
        async with get_db_session() as db:
            result = await db.execute(
                select(BookingFormField).where(
                    BookingFormField.id == field_id,
                    BookingFormField.site_id == site_id,
                )
            )
            field = result.scalar_one_or_none()
            if field is None:
                raise ValueError("Booking form field not found")
            await db.delete(field)
        return True

    # -----------------------------------------------------------------------
    # Booking payment methods
    # -----------------------------------------------------------------------

    @strawberry.mutation
    async def update_booking_payment_methods(self, info: Info, input: UpdateBookingPaymentMethodsInput) -> BookingPaymentMethodsType:
        await _require_site_owner(info, input.site_id)
        await _require_bookings_installed(input.site_id)
        async with get_db_session() as db:
            result = await db.execute(
                select(BookingPaymentMethods).where(
                    BookingPaymentMethods.site_id == input.site_id,
                )
            )
            pm = result.scalar_one_or_none()
            if pm is None:
                pm = BookingPaymentMethods(site_id=input.site_id)
                db.add(pm)
                await db.flush()

            if input.stripe_connect_enabled is not None:
                pm.stripe_connect_enabled = input.stripe_connect_enabled
            if input.on_site_enabled is not None:
                pm.on_site_enabled = input.on_site_enabled
            if input.klarna_enabled is not None:
                pm.klarna_enabled = input.klarna_enabled
            if input.swish_enabled is not None:
                pm.swish_enabled = input.swish_enabled

            pm.updated_at = datetime.now(timezone.utc)
            await db.flush()
            return _payment_methods_to_gql(pm)

    # -----------------------------------------------------------------------
    # Booking status
    # -----------------------------------------------------------------------

    @strawberry.mutation
    async def update_booking_status(self, info: Info, input: UpdateBookingStatusInput) -> BookingType:
        await _require_site_owner(info, input.site_id)
        async with get_db_session() as db:
            from sqlalchemy.orm import selectinload
            result = await db.execute(
                select(Booking)
                .options(selectinload(Booking.service))
                .where(
                    Booking.id == input.id,
                    Booking.site_id == input.site_id,
                )
            )
            booking = result.scalar_one_or_none()
            if booking is None:
                raise ValueError("Booking not found")

            booking.status = BookingStatus(input.status.value)
            if input.notes is not None:
                booking.notes = input.notes
            booking.updated_at = datetime.now(timezone.utc)
            await db.flush()

            # Send status change email to customer
            if input.status in (BookingStatusGQL.CONFIRMED, BookingStatusGQL.CANCELLED, BookingStatusGQL.COMPLETED):
                try:
                    from app.email.service import send_transactional_email
                    from app.email.booking_templates import (
                        build_booking_confirmed_email,
                        build_booking_cancelled_email,
                        build_booking_completed_email,
                    )
                    from app.sites.models import GeneratedSite

                    site_result = await db.execute(
                        select(GeneratedSite).where(GeneratedSite.id == input.site_id)
                    )
                    site = site_result.scalar_one_or_none()
                    site_name = "din webbplats"
                    if site and site.site_data:
                        site_name = site.site_data.get("business", {}).get("name") or site.site_data.get("meta", {}).get("title") or site_name

                    service_name = booking.service_name or (booking.service.name if booking.service else "")
                    booking_date_str = booking.booking_date.strftime("%Y-%m-%d %H:%M") if booking.booking_date else "Ej angivet"

                    if input.status == BookingStatusGQL.CONFIRMED:
                        subj, html, text = build_booking_confirmed_email(
                            customer_name=booking.customer_name,
                            site_name=site_name,
                            service_name=service_name,
                            booking_date=booking_date_str,
                            amount=float(booking.amount),
                            currency=booking.currency,
                        )
                    elif input.status == BookingStatusGQL.CANCELLED:
                        subj, html, text = build_booking_cancelled_email(
                            customer_name=booking.customer_name,
                            site_name=site_name,
                            service_name=service_name,
                            booking_date=booking_date_str,
                        )
                    else:  # COMPLETED
                        subj, html, text = build_booking_completed_email(
                            customer_name=booking.customer_name,
                            site_name=site_name,
                            service_name=service_name,
                            booking_date=booking_date_str,
                        )

                    await send_transactional_email(
                        to=booking.customer_email,
                        subject=subj,
                        html=html,
                        text=text,
                        from_name="Bookings by Qvicko",
                    )
                except Exception:
                    logger.exception("Failed to send booking status email")

            # Reload to get fresh data
            result = await db.execute(
                select(Booking)
                .options(selectinload(Booking.service))
                .where(Booking.id == booking.id)
            )
            booking = result.scalar_one()
            return _booking_to_gql(booking)


# Fix missing import
from uuid import uuid4  # noqa: E402
