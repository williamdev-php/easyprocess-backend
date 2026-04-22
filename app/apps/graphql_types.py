from __future__ import annotations

import enum
from datetime import datetime

import strawberry
from strawberry.scalars import JSON


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

@strawberry.enum
class BlogPostStatusGQL(enum.Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


@strawberry.enum
class AppPricingTypeGQL(enum.Enum):
    FREE = "FREE"
    ONE_TIME = "ONE_TIME"
    MONTHLY = "MONTHLY"
    USAGE = "USAGE"


# ---------------------------------------------------------------------------
# App types
# ---------------------------------------------------------------------------

@strawberry.type
class AppType:
    id: str
    slug: str
    name: str
    description: JSON | None = None
    long_description: JSON | None = None
    icon_url: str | None = None
    version: str = "1.0.0"
    scopes: JSON | None = None
    sidebar_links: JSON | None = None
    screenshots: JSON | None = None
    features: JSON | None = None
    developer_name: str | None = None
    developer_url: str | None = None
    category: str | None = None
    pricing_type: AppPricingTypeGQL = AppPricingTypeGQL.FREE
    price: float = 0
    price_description: str | None = None
    install_count: int = 0
    avg_rating: float = 0
    review_count: int = 0


@strawberry.type
class AppInstallationType:
    id: str
    app_id: str
    app_slug: str
    app_name: str
    site_id: str
    is_active: bool = True
    settings: JSON | None = None
    sidebar_links: JSON | None = None
    installed_at: datetime | None = None


@strawberry.type
class AppReviewType:
    id: str
    app_id: str
    user_id: str
    user_name: str
    site_id: str
    rating: int
    title: str | None = None
    body: str | None = None
    locale: str | None = None
    created_at: datetime | None = None


# ---------------------------------------------------------------------------
# Blog types
# ---------------------------------------------------------------------------

@strawberry.type
class BlogPostType:
    id: str
    site_id: str
    title: str
    slug: str
    excerpt: str | None = None
    content: str = ""
    featured_image: str | None = None
    author_name: str | None = None
    author_id: str | None = None
    category_id: str | None = None
    category_name: str | None = None
    status: BlogPostStatusGQL = BlogPostStatusGQL.DRAFT
    published_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@strawberry.type
class BlogPostListType:
    items: list[BlogPostType]
    total: int
    page: int
    page_size: int


@strawberry.type
class BlogCategoryType:
    id: str
    site_id: str
    name: str
    slug: str
    description: str | None = None
    sort_order: int = 0
    post_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------

@strawberry.input
class InstallAppInput:
    app_slug: str
    site_id: str


@strawberry.input
class UninstallAppInput:
    app_slug: str
    site_id: str


@strawberry.input
class CreateBlogPostInput:
    site_id: str
    title: str
    content: str = ""
    slug: str | None = None
    excerpt: str | None = None
    featured_image: str | None = None
    category_id: str | None = None
    status: BlogPostStatusGQL = BlogPostStatusGQL.DRAFT


@strawberry.input
class UpdateBlogPostInput:
    id: str
    site_id: str
    title: str | None = None
    slug: str | None = None
    content: str | None = None
    excerpt: str | None = None
    featured_image: str | None = None
    category_id: str | None = None
    status: BlogPostStatusGQL | None = None


@strawberry.input
class CreateBlogCategoryInput:
    site_id: str
    name: str
    slug: str | None = None
    description: str | None = None


@strawberry.input
class UpdateBlogCategoryInput:
    id: str
    site_id: str
    name: str | None = None
    slug: str | None = None
    description: str | None = None


@strawberry.input
class BlogPostFilterInput:
    status: BlogPostStatusGQL | None = None
    category_id: str | None = None
    search: str | None = None
    page: int = 1
    page_size: int = 20


@strawberry.input
class CreateAppReviewInput:
    app_slug: str
    site_id: str
    rating: int
    title: str | None = None
    body: str | None = None
    locale: str | None = None


@strawberry.input
class DeleteAppReviewInput:
    review_id: str


# ---------------------------------------------------------------------------
# Chat enums
# ---------------------------------------------------------------------------

@strawberry.enum
class ChatConversationStatusGQL(enum.Enum):
    OPEN = "open"
    CLOSED = "closed"


@strawberry.enum
class ChatSenderTypeGQL(enum.Enum):
    VISITOR = "visitor"
    AGENT = "agent"


# ---------------------------------------------------------------------------
# Chat types
# ---------------------------------------------------------------------------

@strawberry.type
class ChatMessageType:
    id: str
    conversation_id: str
    sender_type: ChatSenderTypeGQL
    sender_name: str | None = None
    content: str
    created_at: datetime | None = None


@strawberry.type
class ChatConversationType:
    id: str
    site_id: str
    visitor_email: str
    visitor_name: str | None = None
    status: ChatConversationStatusGQL = ChatConversationStatusGQL.OPEN
    subject: str | None = None
    last_message_at: datetime | None = None
    message_count: int = 0
    last_message_preview: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@strawberry.type
class ChatConversationDetailType:
    conversation: ChatConversationType
    messages: list[ChatMessageType]


@strawberry.type
class ChatConversationListType:
    items: list[ChatConversationType]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Chat input types
# ---------------------------------------------------------------------------

@strawberry.input
class ChatConversationFilterInput:
    status: ChatConversationStatusGQL | None = None
    search: str | None = None
    page: int = 1
    page_size: int = 20


@strawberry.input
class SendChatReplyInput:
    conversation_id: str
    site_id: str
    content: str
