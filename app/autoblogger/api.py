"""AutoBlogger REST API — CRUD for sources, posts, schedules, settings, credits.

CSRF Note:
    This API exclusively uses Bearer token authentication (Authorization header).
    No cookie-based sessions are used for state-changing requests, so CSRF attacks
    are mitigated by design — browsers will not automatically attach the Authorization
    header to cross-origin requests. See: https://owasp.org/www-community/attacks/csrf
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from calendar import monthrange
from collections import defaultdict

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.autoblogger.auth_dependencies import get_current_autoblogger_user
from app.autoblogger.models import AutoBloggerUser
from app.autoblogger.credits import (
    calculate_credits_for_post,
    deduct_credits,
    get_or_create_credit_balance,
    validate_credits,
)
from app.autoblogger.encryption import decrypt_platform_config, encrypt_platform_config
from app.autoblogger.generator import generate_blog_post
from app.autoblogger.sanitize import sanitize_html, sanitize_text
from app.autoblogger.scheduler import calculate_initial_next_run_at
from app.autoblogger.images import generate_featured_image
from app.rate_limit import limiter
from app.database import get_db, get_db_session

from app.autoblogger.models import (
    AnalyticsEventType,
    BlogPostAB,
    ContentSchedule,
    CreditBalance,
    CreditTransaction,
    Notification,
    PlatformType,
    PostStatus,
    Source,
    TaskFrequency,
    UserSettings,
)
from app.autoblogger.analytics import track_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/autoblogger", tags=["autoblogger"])


# ─── Pydantic Schemas ───────────────────────────────────────────────────────


# Sources
class SourceCreate(BaseModel):
    name: str = Field(..., max_length=255)
    platform: PlatformType
    platform_url: Optional[str] = Field(None, max_length=1000)
    platform_config: Optional[dict] = None
    brand_voice: Optional[str] = None
    default_language: str = Field("en", max_length=10)
    target_keywords: Optional[list[str]] = None

    @field_validator("platform_url")
    @classmethod
    def validate_platform_url(cls, v: str | None) -> str | None:
        if v is None:
            return v
        parsed = urlparse(v)
        if parsed.scheme not in ("https", "http"):
            raise ValueError("URL must start with https:// (or http:// for localhost)")
        if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1"):
            raise ValueError("HTTP is only allowed for localhost URLs; use https://")
        if not parsed.hostname:
            raise ValueError("Invalid URL format: missing hostname")
        return v


class SourceUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    platform: Optional[PlatformType] = None
    platform_url: Optional[str] = Field(None, max_length=1000)
    platform_config: Optional[dict] = None
    brand_voice: Optional[str] = None
    brand_images: Optional[list[str]] = None
    default_language: Optional[str] = Field(None, max_length=10)
    target_keywords: Optional[list[str]] = None


class SourceResponse(BaseModel):
    id: str
    user_id: str
    name: str
    platform: str
    platform_url: Optional[str] = None
    platform_config: Optional[dict] = None
    brand_voice: Optional[str] = None
    brand_images: Optional[list] = None
    default_language: str
    target_keywords: Optional[list] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# Posts
class PostCreate(BaseModel):
    source_id: str
    title: Optional[str] = Field(None, max_length=500)
    topic: str = Field(..., max_length=500)
    keywords: list[str] = Field(default_factory=list)
    language: Optional[str] = Field(None, max_length=10)


class PostUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=500)
    content: Optional[str] = None
    status: Optional[PostStatus] = None
    scheduled_at: Optional[datetime] = None


class DeclineRequest(BaseModel):
    decline_reason: Optional[str] = Field(None, max_length=1000)


class PostResponse(BaseModel):
    id: str
    source_id: str
    user_id: str
    title: str
    slug: Optional[str] = None
    content: Optional[str] = None
    excerpt: Optional[str] = None
    meta_title: Optional[str] = None
    meta_description: Optional[str] = None
    featured_image_url: Optional[str] = None
    tags: Optional[list] = None
    language: str
    status: str
    scheduled_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    platform_post_id: Optional[str] = None
    target_keyword: Optional[str] = None
    ai_model: Optional[str] = None
    word_count: Optional[int] = None
    reading_time_minutes: Optional[int] = None
    credits_used: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# Schedules
class ScheduleCreate(BaseModel):
    source_id: str
    name: str = Field(..., max_length=255)
    frequency: TaskFrequency
    days_of_week: Optional[list[str]] = None
    posts_per_day: int = Field(1, ge=1, le=10)
    preferred_time: Optional[str] = Field(None, max_length=10)
    timezone: str = Field("Europe/Stockholm", max_length=50)
    topics: Optional[list[str]] = None
    keywords: Optional[list[str]] = None
    language: str = Field("en", max_length=10)
    auto_publish: bool = False


class ScheduleUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    frequency: Optional[TaskFrequency] = None
    days_of_week: Optional[list[str]] = None
    posts_per_day: Optional[int] = Field(None, ge=1, le=10)
    preferred_time: Optional[str] = Field(None, max_length=10)
    timezone: Optional[str] = Field(None, max_length=50)
    topics: Optional[list[str]] = None
    keywords: Optional[list[str]] = None
    language: Optional[str] = Field(None, max_length=10)
    auto_publish: Optional[bool] = None


class ScheduleResponse(BaseModel):
    id: str
    source_id: str
    user_id: str
    name: str
    frequency: str
    days_of_week: Optional[list] = None
    posts_per_day: int
    preferred_time: Optional[str] = None
    timezone: str
    topics: Optional[list] = None
    keywords: Optional[list] = None
    language: str
    auto_publish: bool
    is_active: bool
    next_run_at: Optional[datetime] = None
    last_run_at: Optional[datetime] = None
    posts_generated: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# Settings
class SettingsUpdate(BaseModel):
    auto_publish: Optional[bool] = None
    ai_model: Optional[str] = Field(None, max_length=100)
    image_generation: Optional[bool] = None
    default_language: Optional[str] = Field(None, max_length=10)
    brand_voice_global: Optional[str] = None
    posts_per_month_limit: Optional[int] = Field(None, ge=1)
    notification_email: Optional[bool] = None


class SettingsResponse(BaseModel):
    id: str
    user_id: str
    auto_publish: bool
    ai_model: str
    image_generation: bool
    default_language: str
    brand_voice_global: Optional[str] = None
    posts_per_month_limit: int
    notification_email: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# Credits
class CreditBalanceResponse(BaseModel):
    id: str
    user_id: str
    credits_remaining: int
    credits_used_total: int
    plan_credits_monthly: int
    last_reset_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CreditTransactionResponse(BaseModel):
    id: str
    user_id: str
    amount: int
    balance_after: int
    description: str
    post_id: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# Notifications
class NotificationResponse(BaseModel):
    id: str
    user_id: str
    type: str
    title: str
    message: str
    link: Optional[str] = None
    is_read: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# Dashboard
class DashboardStats(BaseModel):
    total_posts: int
    published_posts: int
    scheduled_posts: int
    draft_posts: int
    credits_remaining: int
    credits_used: int
    connected_sources: int
    active_schedules: int


# ─── Helpers ─────────────────────────────────────────────────────────────────


async def _get_or_create_credit_balance(db: AsyncSession, user_id: str) -> CreditBalance:
    result = await db.execute(
        select(CreditBalance).where(CreditBalance.user_id == user_id)
    )
    balance = result.scalar_one_or_none()
    if balance is None:
        balance = CreditBalance(user_id=user_id)
        db.add(balance)
        await db.flush()
    return balance


async def _get_or_create_settings(db: AsyncSession, user_id: str) -> UserSettings:
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    settings = result.scalar_one_or_none()
    if settings is None:
        settings = UserSettings(user_id=user_id)
        db.add(settings)
        await db.flush()
    return settings


def _source_response_decrypted(source: Source) -> SourceResponse:
    """Build a SourceResponse with platform_config secrets decrypted for the client."""
    resp = SourceResponse.model_validate(source)
    resp.platform_config = decrypt_platform_config(source.platform_config)
    return resp


# ─── Sources ─────────────────────────────────────────────────────────────────


@router.get("/sources", response_model=list[SourceResponse])
@limiter.limit("60/minute")
async def list_sources(
    request: Request,
    current_user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
) -> list[SourceResponse]:
    result = await db.execute(
        select(Source)
        .where(Source.user_id == current_user.id, Source.is_active.is_(True))
        .order_by(Source.created_at.desc())
    )
    sources = result.scalars().all()
    return [_source_response_decrypted(s) for s in sources]


@router.post("/sources", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
async def create_source(
    body: SourceCreate,
    request: Request,
    current_user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
) -> SourceResponse:
    source = Source(
        user_id=current_user.id,
        name=body.name,
        platform=body.platform,
        platform_url=body.platform_url,
        platform_config=encrypt_platform_config(body.platform_config),
        brand_voice=sanitize_text(body.brand_voice) if body.brand_voice else body.brand_voice,
        default_language=body.default_language,
        target_keywords=body.target_keywords,
    )
    db.add(source)
    await db.flush()
    await db.refresh(source)
    return _source_response_decrypted(source)


@router.get("/sources/{source_id}", response_model=SourceResponse)
@limiter.limit("60/minute")
async def get_source(
    source_id: str,
    request: Request,
    current_user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
) -> SourceResponse:
    result = await db.execute(
        select(Source).where(Source.id == source_id)
    )
    source = result.scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    if source.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your source")
    return _source_response_decrypted(source)


@router.patch("/sources/{source_id}", response_model=SourceResponse)
@limiter.limit("30/minute")
async def update_source(
    source_id: str,
    body: SourceUpdate,
    request: Request,
    current_user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
) -> SourceResponse:
    result = await db.execute(
        select(Source).where(Source.id == source_id)
    )
    source = result.scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    if source.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your source")

    update_data = body.model_dump(exclude_unset=True)
    # Sanitize brand_voice if present
    if "brand_voice" in update_data and update_data["brand_voice"] is not None:
        update_data["brand_voice"] = sanitize_text(update_data["brand_voice"])
    # Encrypt sensitive fields in platform_config before storing
    if "platform_config" in update_data and update_data["platform_config"] is not None:
        update_data["platform_config"] = encrypt_platform_config(update_data["platform_config"])
    for key, value in update_data.items():
        setattr(source, key, value)

    source.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(source)
    return _source_response_decrypted(source)


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
@limiter.limit("30/minute")
async def delete_source(
    source_id: str,
    request: Request,
    current_user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Source).where(Source.id == source_id)
    )
    source = result.scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    if source.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your source")

    source.is_active = False
    source.updated_at = datetime.now(timezone.utc)
    await db.flush()


# ─── Posts ───────────────────────────────────────────────────────────────────


async def _generate_post_background(
    post_id: str,
    body: PostCreate,
    user_settings: UserSettings,
    source: Source,
    user_id: str,
):
    """Generate a blog post in the background and update its record."""
    try:
        async with get_db_session() as db:
            result = await generate_blog_post(
                topic=body.topic,
                keywords=body.keywords,
                language=body.language or source.default_language,
                brand_voice=source.brand_voice,
                ai_model=user_settings.ai_model,
                title=body.title,
            )

            # Optional featured image
            featured_image_url = None
            if user_settings.image_generation:
                featured_image_url = await generate_featured_image(
                    title=result.title,
                    keywords=body.keywords,
                    brand_images=source.brand_images,
                )

            # Fetch the post record
            post_result = await db.execute(
                select(BlogPostAB).where(BlogPostAB.id == post_id)
            )
            post = post_result.scalar_one()

            post.title = result.title
            post.slug = result.slug
            post.content = result.content
            post.excerpt = result.excerpt
            post.meta_title = result.meta_title
            post.meta_description = result.meta_description
            post.tags = result.tags
            post.schema_markup = result.schema_markup
            post.internal_links = result.internal_links
            post.generation_prompt = result.generation_prompt
            post.target_keyword = body.keywords[0] if body.keywords else None
            post.ai_model = result.ai_model
            post.word_count = result.word_count
            post.reading_time_minutes = result.reading_time_minutes
            post.featured_image_url = featured_image_url

            # Credit handling — 1 credit was already deducted in the endpoint.
            # If long-form, deduct the extra credit now.
            total_credits = calculate_credits_for_post(result.word_count)
            if total_credits > post.credits_used:
                extra = total_credits - post.credits_used
                await deduct_credits(
                    db, user_id, extra,
                    description=f"Blog post generation (long-form extra): {result.title[:100]}",
                    post_id=post_id,
                )
                post.credits_used = total_credits

            # Track POST_GENERATED analytics event
            await track_event(db, user_id, AnalyticsEventType.POST_GENERATED, {
                "post_id": post_id,
                "model": result.ai_model,
                "language": post.language,
                "word_count": result.word_count,
                "credits_used": post.credits_used,
            })

            if user_settings.auto_publish:
                from app.autoblogger.publisher import execute_publish
                pub_result = await execute_publish(db, post_id)
                if not pub_result.success:
                    logger.warning("Auto-publish failed for post %s: %s", post_id, pub_result.error)
                    # Post status is already set to FAILED by execute_publish
            else:
                post.status = PostStatus.REVIEW
                post.updated_at = datetime.now(timezone.utc)

            await db.flush()
    except Exception as e:
        logger.exception("Background post generation failed for post_id=%s", post_id)
        try:
            async with get_db_session() as db:
                post_result = await db.execute(
                    select(BlogPostAB).where(BlogPostAB.id == post_id)
                )
                post = post_result.scalar_one()
                post.status = PostStatus.FAILED
                post.error_message = str(e)
                post.updated_at = datetime.now(timezone.utc)

                # Refund the credits that were deducted upfront
                if post.credits_used and post.credits_used > 0:
                    refund_amount = post.credits_used
                    balance = await get_or_create_credit_balance(db, user_id)
                    balance.credits_remaining += refund_amount
                    balance.credits_used_total -= refund_amount
                    refund_tx = CreditTransaction(
                        user_id=user_id,
                        amount=refund_amount,
                        balance_after=balance.credits_remaining,
                        description=f"Refund: generation failed for post {post_id}",
                        post_id=post_id,
                    )
                    db.add(refund_tx)
                    post.credits_used = 0
                    logger.info("Refunded %d credit(s) for failed post %s", refund_amount, post_id)

                # Track GENERATION_FAILED analytics event
                await track_event(db, user_id, AnalyticsEventType.GENERATION_FAILED, {
                    "post_id": post_id,
                    "error": str(e)[:500],
                })

                await db.flush()
        except Exception:
            logger.exception("Failed to mark post %s as FAILED", post_id)


@router.post("/posts", response_model=PostResponse, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("10/hour")
async def create_post(
    body: PostCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
) -> PostResponse:
    """Create a new blog post — generation happens in the background."""
    # Verify source belongs to user
    result = await db.execute(
        select(Source).where(Source.id == body.source_id, Source.user_id == current_user.id)
    )
    source = result.scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")

    # Validate user has credits
    await validate_credits(db, current_user.id)

    # Deduct 1 credit upfront (atomically with validation in the same session)
    # to prevent concurrent requests from overdrawing.
    initial_credits = 1
    await deduct_credits(
        db, current_user.id, initial_credits,
        description="Blog post generation (reserved)",
    )

    # Get user settings
    user_settings = await _get_or_create_settings(db, current_user.id)

    # Create post record with GENERATING status
    post = BlogPostAB(
        source_id=body.source_id,
        user_id=current_user.id,
        title=body.title or body.topic,
        language=body.language or source.default_language,
        status=PostStatus.GENERATING,
        credits_used=initial_credits,
    )
    db.add(post)
    await db.flush()
    await db.refresh(post)

    # Launch background generation
    background_tasks.add_task(
        _generate_post_background,
        post.id,
        body,
        user_settings,
        source,
        current_user.id,
    )

    return PostResponse.model_validate(post)


@router.get("/posts", response_model=list[PostResponse])
@limiter.limit("60/minute")
async def list_posts(
    request: Request,
    status_filter: Optional[str] = Query(None, alias="status"),
    source_id: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
) -> list[PostResponse]:
    query = select(BlogPostAB).where(BlogPostAB.user_id == current_user.id)

    if status_filter:
        query = query.where(BlogPostAB.status == status_filter)
    if source_id:
        query = query.where(BlogPostAB.source_id == source_id)

    query = query.order_by(BlogPostAB.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    posts = result.scalars().all()
    return [PostResponse.model_validate(p) for p in posts]


@router.get("/posts/calendar")
@limiter.limit("60/minute")
async def get_posts_calendar(
    request: Request,
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    current_user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
):
    """Return posts for the given month grouped by date."""
    year, month_num = int(month[:4]), int(month[5:7])
    _, last_day = monthrange(year, month_num)
    start = datetime(year, month_num, 1, tzinfo=timezone.utc)
    end = datetime(year, month_num, last_day, 23, 59, 59, tzinfo=timezone.utc)

    result = await db.execute(
        select(BlogPostAB).where(
            BlogPostAB.user_id == current_user.id,
            or_(
                and_(BlogPostAB.scheduled_at >= start, BlogPostAB.scheduled_at <= end),
                and_(BlogPostAB.published_at >= start, BlogPostAB.published_at <= end),
                and_(BlogPostAB.created_at >= start, BlogPostAB.created_at <= end),
            ),
        )
    )
    posts = result.scalars().all()

    days: dict[str, list] = defaultdict(list)
    for post in posts:
        # Pick the most relevant date
        date_val = post.scheduled_at or post.published_at or post.created_at
        day_key = date_val.strftime("%Y-%m-%d")
        days[day_key].append(PostResponse.model_validate(post))

    return {"days": dict(days)}


@router.get("/posts/{post_id}", response_model=PostResponse)
@limiter.limit("60/minute")
async def get_post(
    post_id: str,
    request: Request,
    current_user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
) -> PostResponse:
    result = await db.execute(
        select(BlogPostAB).where(BlogPostAB.id == post_id)
    )
    post = result.scalar_one_or_none()
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    if post.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your post")
    return PostResponse.model_validate(post)


@router.get("/posts/{post_id}/export")
@limiter.limit("60/minute")
async def export_post(
    post_id: str,
    request: Request,
    format: str = Query("html", pattern="^(html|markdown|text)$"),
    current_user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
):
    """Export post content for manual publishing. Returns HTML, markdown, or plain text."""
    result = await db.execute(
        select(BlogPostAB).where(BlogPostAB.id == post_id)
    )
    post = result.scalar_one_or_none()
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    if post.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your post")

    content = post.content or ""

    if format == "html":
        # Full HTML with title as h1
        full_html = f"<h1>{post.title}</h1>\n{content}"
        return {"format": "html", "content": full_html, "title": post.title, "meta_title": post.meta_title, "meta_description": post.meta_description}

    elif format == "text":
        # Strip HTML tags for plain text
        import re
        text = re.sub(r'<[^>]+>', '', content)
        text = f"{post.title}\n\n{text}"
        return {"format": "text", "content": text, "title": post.title}

    else:  # markdown
        # Basic HTML to markdown conversion
        import re
        md = content
        md = re.sub(r'<h2>(.*?)</h2>', r'## \1', md)
        md = re.sub(r'<h3>(.*?)</h3>', r'### \1', md)
        md = re.sub(r'<strong>(.*?)</strong>', r'**\1**', md)
        md = re.sub(r'<em>(.*?)</em>', r'*\1*', md)
        md = re.sub(r'<li>(.*?)</li>', r'- \1', md)
        md = re.sub(r'<blockquote>(.*?)</blockquote>', r'> \1', md)
        md = re.sub(r'<p>(.*?)</p>', r'\1\n\n', md)
        md = re.sub(r'<[^>]+>', '', md)  # strip remaining tags
        md = f"# {post.title}\n\n{md}"
        return {"format": "markdown", "content": md, "title": post.title}


@router.patch("/posts/{post_id}", response_model=PostResponse)
@limiter.limit("30/minute")
async def update_post(
    post_id: str,
    body: PostUpdate,
    request: Request,
    current_user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
) -> PostResponse:
    result = await db.execute(
        select(BlogPostAB).where(BlogPostAB.id == post_id)
    )
    post = result.scalar_one_or_none()
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    if post.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your post")

    update_data = body.model_dump(exclude_unset=True)
    # Sanitize content HTML if present
    if "content" in update_data and update_data["content"] is not None:
        update_data["content"] = sanitize_html(update_data["content"])
    for key, value in update_data.items():
        setattr(post, key, value)

    post.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(post)
    return PostResponse.model_validate(post)


@router.delete("/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
@limiter.limit("30/minute")
async def delete_post(
    post_id: str,
    request: Request,
    current_user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(BlogPostAB).where(BlogPostAB.id == post_id)
    )
    post = result.scalar_one_or_none()
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    if post.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your post")

    await db.delete(post)
    await db.flush()


@router.post("/posts/{post_id}/approve", response_model=PostResponse)
@limiter.limit("30/minute")
async def approve_post(
    post_id: str,
    request: Request,
    current_user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
) -> PostResponse:
    """Approve a post in REVIEW status — publish or schedule it."""
    result = await db.execute(
        select(BlogPostAB).where(BlogPostAB.id == post_id)
    )
    post = result.scalar_one_or_none()
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    if post.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your post")
    if post.status != PostStatus.REVIEW:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Post must be in REVIEW status to approve",
        )

    now = datetime.now(timezone.utc)
    if post.scheduled_at and post.scheduled_at > now:
        post.status = PostStatus.SCHEDULED
        post.updated_at = now
        await db.flush()
        await db.refresh(post)
    else:
        # Publish immediately via the publisher service
        from app.autoblogger.publisher import execute_publish
        publish_result = await execute_publish(db, post.id)
        await db.refresh(post)
        if not publish_result.success:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Publishing failed: {publish_result.error}",
            )

    return PostResponse.model_validate(post)


@router.post("/posts/{post_id}/decline", response_model=PostResponse)
@limiter.limit("30/minute")
async def decline_post(
    post_id: str,
    request: Request,
    body: Optional[DeclineRequest] = None,
    current_user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
) -> PostResponse:
    """Decline a post in REVIEW status — revert to DRAFT and refund credit."""
    result = await db.execute(
        select(BlogPostAB).where(BlogPostAB.id == post_id)
    )
    post = result.scalar_one_or_none()
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    if post.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your post")
    if post.status != PostStatus.REVIEW:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Post must be in REVIEW status to decline",
        )

    post.status = PostStatus.DRAFT
    if body and body.decline_reason:
        post.error_message = sanitize_text(body.decline_reason)

    # Refund credits used by this post (could be 2 for long-form)
    refund_amount = post.credits_used or 1
    balance = await get_or_create_credit_balance(db, current_user.id)
    balance.credits_remaining += refund_amount
    balance.credits_used_total -= refund_amount

    transaction = CreditTransaction(
        user_id=current_user.id,
        amount=refund_amount,
        balance_after=balance.credits_remaining,
        description=f"Refund: post declined ({refund_amount} credit{'s' if refund_amount != 1 else ''})",
        post_id=post_id,
    )
    db.add(transaction)

    post.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(post)
    return PostResponse.model_validate(post)


@router.post(
    "/posts/{post_id}/regenerate",
    response_model=PostResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit("10/hour")
async def regenerate_post(
    post_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
) -> PostResponse:
    """Re-generate a DRAFT or FAILED post in the background."""
    result = await db.execute(
        select(BlogPostAB).where(BlogPostAB.id == post_id)
    )
    post = result.scalar_one_or_none()
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    if post.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your post")
    if post.status not in (PostStatus.DRAFT, PostStatus.FAILED):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Post must be in DRAFT or FAILED status to regenerate",
        )

    # Validate credits
    await validate_credits(db, current_user.id)

    post.status = PostStatus.GENERATING
    post.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(post)

    # Gather context for background generation
    user_settings = await _get_or_create_settings(db, current_user.id)

    source_result = await db.execute(
        select(Source).where(Source.id == post.source_id)
    )
    source = source_result.scalar_one()

    body = PostCreate(
        source_id=post.source_id,
        topic=post.title,
        keywords=post.tags or [],
        language=post.language,
    )

    background_tasks.add_task(
        _generate_post_background,
        post.id,
        body,
        user_settings,
        source,
        current_user.id,
    )

    return PostResponse.model_validate(post)


# ─── Schedules ───────────────────────────────────────────────────────────────


@router.get("/schedules", response_model=list[ScheduleResponse])
@limiter.limit("60/minute")
async def list_schedules(
    request: Request,
    current_user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
) -> list[ScheduleResponse]:
    result = await db.execute(
        select(ContentSchedule)
        .where(ContentSchedule.user_id == current_user.id)
        .order_by(ContentSchedule.created_at.desc())
    )
    schedules = result.scalars().all()
    return [ScheduleResponse.model_validate(s) for s in schedules]


@router.post("/schedules", response_model=ScheduleResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
async def create_schedule(
    body: ScheduleCreate,
    request: Request,
    current_user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
) -> ScheduleResponse:
    # Verify source belongs to user
    result = await db.execute(
        select(Source).where(Source.id == body.source_id, Source.user_id == current_user.id)
    )
    source = result.scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")

    schedule = ContentSchedule(
        source_id=body.source_id,
        user_id=current_user.id,
        name=body.name,
        frequency=body.frequency,
        days_of_week=body.days_of_week,
        posts_per_day=body.posts_per_day,
        preferred_time=body.preferred_time,
        timezone=body.timezone,
        topics=body.topics,
        keywords=body.keywords,
        language=body.language,
        auto_publish=body.auto_publish,
        next_run_at=calculate_initial_next_run_at(
            frequency=body.frequency,
            preferred_time=body.preferred_time,
            timezone_str=body.timezone,
            days_of_week=body.days_of_week,
        ),
    )
    db.add(schedule)
    await db.flush()
    await db.refresh(schedule)
    return ScheduleResponse.model_validate(schedule)


@router.patch("/schedules/{schedule_id}", response_model=ScheduleResponse)
@limiter.limit("30/minute")
async def update_schedule(
    schedule_id: str,
    body: ScheduleUpdate,
    request: Request,
    current_user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
) -> ScheduleResponse:
    result = await db.execute(
        select(ContentSchedule).where(ContentSchedule.id == schedule_id)
    )
    schedule = result.scalar_one_or_none()
    if schedule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    if schedule.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your schedule")

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(schedule, key, value)

    # Recalculate next_run_at if scheduling parameters changed
    recalc_fields = {"frequency", "days_of_week", "preferred_time", "timezone"}
    if recalc_fields & update_data.keys():
        from app.autoblogger.scheduler import calculate_next_run_at
        schedule.next_run_at = calculate_next_run_at(
            frequency=schedule.frequency,
            preferred_time=schedule.preferred_time,
            timezone_str=schedule.timezone,
            days_of_week=schedule.days_of_week,
            last_run_at=schedule.last_run_at,
        )

    schedule.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(schedule)
    return ScheduleResponse.model_validate(schedule)


@router.delete("/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
@limiter.limit("30/minute")
async def delete_schedule(
    schedule_id: str,
    request: Request,
    current_user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ContentSchedule).where(ContentSchedule.id == schedule_id)
    )
    schedule = result.scalar_one_or_none()
    if schedule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    if schedule.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your schedule")

    await db.delete(schedule)
    await db.flush()


@router.post("/schedules/{schedule_id}/toggle", response_model=ScheduleResponse)
@limiter.limit("30/minute")
async def toggle_schedule(
    schedule_id: str,
    request: Request,
    current_user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
) -> ScheduleResponse:
    result = await db.execute(
        select(ContentSchedule).where(ContentSchedule.id == schedule_id)
    )
    schedule = result.scalar_one_or_none()
    if schedule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    if schedule.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your schedule")

    schedule.is_active = not schedule.is_active
    schedule.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(schedule)
    return ScheduleResponse.model_validate(schedule)


# ─── Settings ────────────────────────────────────────────────────────────────


@router.get("/settings", response_model=SettingsResponse)
@limiter.limit("60/minute")
async def get_settings(
    request: Request,
    current_user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
) -> SettingsResponse:
    settings = await _get_or_create_settings(db, current_user.id)
    return SettingsResponse.model_validate(settings)


@router.patch("/settings", response_model=SettingsResponse)
@limiter.limit("30/minute")
async def update_settings(
    body: SettingsUpdate,
    request: Request,
    current_user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
) -> SettingsResponse:
    settings = await _get_or_create_settings(db, current_user.id)

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(settings, key, value)

    settings.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(settings)
    return SettingsResponse.model_validate(settings)


# ─── Credits ─────────────────────────────────────────────────────────────────


@router.get("/credits", response_model=CreditBalanceResponse)
@limiter.limit("60/minute")
async def get_credits(
    request: Request,
    current_user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
) -> CreditBalanceResponse:
    balance = await _get_or_create_credit_balance(db, current_user.id)
    return CreditBalanceResponse.model_validate(balance)


@router.get("/credits/history", response_model=list[CreditTransactionResponse])
@limiter.limit("60/minute")
async def get_credit_history(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
) -> list[CreditTransactionResponse]:
    result = await db.execute(
        select(CreditTransaction)
        .where(CreditTransaction.user_id == current_user.id)
        .order_by(CreditTransaction.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    transactions = result.scalars().all()
    return [CreditTransactionResponse.model_validate(t) for t in transactions]


# ─── Notifications ──────────────────────────────────────────────────────────


@router.get("/notifications", response_model=list[NotificationResponse])
@limiter.limit("30/minute")
async def list_notifications(
    request: Request,
    current_user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
) -> list[NotificationResponse]:
    """Return the 20 most recent notifications for the current user."""
    result = await db.execute(
        select(Notification)
        .where(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(20)
    )
    notifications = result.scalars().all()
    return [NotificationResponse.model_validate(n) for n in notifications]


@router.get("/notifications/unread-count")
@limiter.limit("30/minute")
async def get_unread_count(
    request: Request,
    current_user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the number of unread notifications."""
    result = await db.execute(
        select(func.count(Notification.id)).where(
            Notification.user_id == current_user.id,
            Notification.is_read.is_(False),
        )
    )
    count = result.scalar() or 0
    return {"count": count}


@router.post("/notifications/{notification_id}/read", response_model=NotificationResponse)
@limiter.limit("30/minute")
async def mark_notification_read(
    request: Request,
    notification_id: str,
    current_user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationResponse:
    """Mark a single notification as read."""
    result = await db.execute(
        select(Notification).where(Notification.id == notification_id)
    )
    notification = result.scalar_one_or_none()
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    if notification.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your notification")

    notification.is_read = True
    await db.flush()
    await db.refresh(notification)
    return NotificationResponse.model_validate(notification)


@router.post("/notifications/read-all")
@limiter.limit("30/minute")
async def mark_all_notifications_read(
    request: Request,
    current_user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark all notifications as read for the current user."""
    from sqlalchemy import update

    await db.execute(
        update(Notification)
        .where(
            Notification.user_id == current_user.id,
            Notification.is_read.is_(False),
        )
        .values(is_read=True)
    )
    await db.flush()
    return {"status": "ok"}


# ─── Dashboard Stats ────────────────────────────────────────────────────────


@router.get("/stats", response_model=DashboardStats)
@limiter.limit("60/minute")
async def get_stats(
    request: Request,
    current_user: AutoBloggerUser = Depends(get_current_autoblogger_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardStats:
    user_id = current_user.id

    # Total posts
    total_result = await db.execute(
        select(func.count(BlogPostAB.id)).where(BlogPostAB.user_id == user_id)
    )
    total_posts = total_result.scalar() or 0

    # Published posts
    published_result = await db.execute(
        select(func.count(BlogPostAB.id)).where(
            BlogPostAB.user_id == user_id,
            BlogPostAB.status == PostStatus.PUBLISHED,
        )
    )
    published_posts = published_result.scalar() or 0

    # Scheduled posts
    scheduled_result = await db.execute(
        select(func.count(BlogPostAB.id)).where(
            BlogPostAB.user_id == user_id,
            BlogPostAB.status == PostStatus.SCHEDULED,
        )
    )
    scheduled_posts = scheduled_result.scalar() or 0

    # Draft posts
    draft_result = await db.execute(
        select(func.count(BlogPostAB.id)).where(
            BlogPostAB.user_id == user_id,
            BlogPostAB.status == PostStatus.DRAFT,
        )
    )
    draft_posts = draft_result.scalar() or 0

    # Credits
    balance = await _get_or_create_credit_balance(db, user_id)

    # Connected sources
    sources_result = await db.execute(
        select(func.count(Source.id)).where(
            Source.user_id == user_id,
            Source.is_active.is_(True),
        )
    )
    connected_sources = sources_result.scalar() or 0

    # Active schedules
    schedules_result = await db.execute(
        select(func.count(ContentSchedule.id)).where(
            ContentSchedule.user_id == user_id,
            ContentSchedule.is_active.is_(True),
        )
    )
    active_schedules = schedules_result.scalar() or 0

    return DashboardStats(
        total_posts=total_posts,
        published_posts=published_posts,
        scheduled_posts=scheduled_posts,
        draft_posts=draft_posts,
        credits_remaining=balance.credits_remaining,
        credits_used=balance.credits_used_total,
        connected_sources=connected_sources,
        active_schedules=active_schedules,
    )
