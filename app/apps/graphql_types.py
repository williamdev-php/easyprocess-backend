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
    requires_payments: bool = False
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
    requires_payments: bool = False
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


# ---------------------------------------------------------------------------
# Booking enums
# ---------------------------------------------------------------------------

@strawberry.enum
class BookingStatusGQL(enum.Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


@strawberry.enum
class BookingPaymentStatusGQL(enum.Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"
    FAILED = "FAILED"


# ---------------------------------------------------------------------------
# Booking types
# ---------------------------------------------------------------------------

@strawberry.type
class BookingServiceType:
    id: str
    site_id: str
    name: str
    description: str | None = None
    duration_minutes: int = 60
    price: float = 0
    currency: str = "SEK"
    is_active: bool = True
    sort_order: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


@strawberry.type
class BookingFormFieldType:
    id: str
    site_id: str
    label: str
    field_type: str
    placeholder: str | None = None
    is_required: bool = False
    options: JSON | None = None
    sort_order: int = 0
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


@strawberry.type
class BookingPaymentMethodsType:
    id: str
    site_id: str
    stripe_connect_enabled: bool = False
    on_site_enabled: bool = True
    klarna_enabled: bool = False
    swish_enabled: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


@strawberry.type
class BookingType:
    id: str
    site_id: str
    service_id: str | None = None
    service_name: str | None = None
    customer_name: str
    customer_email: str
    customer_phone: str | None = None
    form_data: JSON | None = None
    status: BookingStatusGQL = BookingStatusGQL.PENDING
    payment_method: str | None = None
    payment_status: BookingPaymentStatusGQL = BookingPaymentStatusGQL.UNPAID
    stripe_payment_intent_id: str | None = None
    amount: float = 0
    currency: str = "SEK"
    notes: str | None = None
    booking_date: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@strawberry.type
class BookingListType:
    items: list[BookingType]
    total: int
    page: int
    page_size: int


@strawberry.type
class BookingStatsType:
    total_bookings: int
    pending_count: int
    confirmed_count: int
    completed_count: int
    cancelled_count: int
    total_revenue: float
    currency: str


@strawberry.type
class ConnectedAccountType:
    id: str
    site_id: str
    stripe_account_id: str
    onboarding_status: str
    charges_enabled: bool = False
    payouts_enabled: bool = False
    details_submitted: bool = False
    country: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ---------------------------------------------------------------------------
# Booking input types
# ---------------------------------------------------------------------------

@strawberry.input
class CreateBookingServiceInput:
    site_id: str
    name: str
    description: str | None = None
    duration_minutes: int = 60
    price: float = 0
    currency: str = "SEK"


@strawberry.input
class UpdateBookingServiceInput:
    id: str
    site_id: str
    name: str | None = None
    description: str | None = None
    duration_minutes: int | None = None
    price: float | None = None
    currency: str | None = None
    is_active: bool | None = None
    sort_order: int | None = None


@strawberry.input
class CreateBookingFormFieldInput:
    site_id: str
    label: str
    field_type: str
    placeholder: str | None = None
    is_required: bool = False
    options: JSON | None = None


@strawberry.input
class UpdateBookingFormFieldInput:
    id: str
    site_id: str
    label: str | None = None
    field_type: str | None = None
    placeholder: str | None = None
    is_required: bool | None = None
    options: JSON | None = None
    sort_order: int | None = None
    is_active: bool | None = None


@strawberry.input
class UpdateBookingPaymentMethodsInput:
    site_id: str
    stripe_connect_enabled: bool | None = None
    on_site_enabled: bool | None = None
    klarna_enabled: bool | None = None
    swish_enabled: bool | None = None


@strawberry.input
class BookingFilterInput:
    status: BookingStatusGQL | None = None
    payment_status: BookingPaymentStatusGQL | None = None
    search: str | None = None
    page: int = 1
    page_size: int = 20


@strawberry.input
class UpdateBookingStatusInput:
    id: str
    site_id: str
    status: BookingStatusGQL
    notes: str | None = None
