"""
REST endpoints for the app system — consumed by the viewer and public app library.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import cache
from app.config import settings
from app.database import get_db
from app.apps.models import App, AppInstallation, AppReview, BlogCategory, BlogPost, BlogPostStatus, Booking, BookingFormField, BookingPaymentMethods, BookingPaymentStatus, BookingService, BookingStatus, ChatConversation, ChatMessage
from app.auth.models import User

router = APIRouter(prefix="/api", tags=["apps"])

BLOG_CACHE_TTL = 300  # 5 minutes


# ---------------------------------------------------------------------------
# Public: Installed apps for a site
# ---------------------------------------------------------------------------

@router.get("/sites/{site_id}/apps/installed")
async def get_installed_apps(
    site_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[str]:
    """Return list of installed app slugs for a site."""
    cache_key = f"site:apps:{site_id}"
    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

    result = await db.execute(
        select(App.slug)
        .join(AppInstallation, AppInstallation.app_id == App.id)
        .where(
            AppInstallation.site_id == site_id,
            AppInstallation.is_active == True,  # noqa: E712
        )
    )
    slugs = [row[0] for row in result.all()]
    await cache.set(cache_key, slugs, ttl=BLOG_CACHE_TTL)
    return slugs


# ---------------------------------------------------------------------------
# Public: Blog posts
# ---------------------------------------------------------------------------

@router.get("/sites/{site_id}/blog/posts")
async def list_blog_posts(
    site_id: str,
    page: int = 1,
    page_size: int = 10,
    category: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List published blog posts for a site (public)."""
    page_size = min(page_size, 50)
    cache_key = f"blog:posts:{site_id}:p{page}:s{page_size}:c{category or ''}"
    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

    base = select(BlogPost).where(
        BlogPost.site_id == site_id,
        BlogPost.status == BlogPostStatus.PUBLISHED,
    )
    count_base = select(func.count(BlogPost.id)).where(
        BlogPost.site_id == site_id,
        BlogPost.status == BlogPostStatus.PUBLISHED,
    )

    if category:
        base = base.join(BlogCategory, BlogPost.category_id == BlogCategory.id).where(
            BlogCategory.slug == category
        )
        count_base = count_base.join(BlogCategory, BlogPost.category_id == BlogCategory.id).where(
            BlogCategory.slug == category
        )

    total_result = await db.execute(count_base)
    total = total_result.scalar() or 0

    offset = (page - 1) * page_size
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        base.options(selectinload(BlogPost.category))
        .order_by(BlogPost.published_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    posts = result.scalars().all()

    data = {
        "items": [
            {
                "id": p.id,
                "title": p.title,
                "slug": p.slug,
                "excerpt": p.excerpt,
                "featured_image": p.featured_image,
                "author_name": p.author_name,
                "category_name": p.category.name if p.category else None,
                "category_slug": p.category.slug if p.category else None,
                "published_at": p.published_at.isoformat() if p.published_at else None,
            }
            for p in posts
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
    await cache.set(cache_key, data, ttl=BLOG_CACHE_TTL)
    return data


@router.get("/sites/{site_id}/blog/posts/{slug}")
async def get_blog_post(
    site_id: str,
    slug: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get a single published blog post by slug (public)."""
    cache_key = f"blog:post:{site_id}:{slug}"
    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(BlogPost)
        .options(selectinload(BlogPost.category))
        .where(
            BlogPost.site_id == site_id,
            BlogPost.slug == slug,
            BlogPost.status == BlogPostStatus.PUBLISHED,
        )
    )
    post = result.scalar_one_or_none()
    if post is None:
        raise HTTPException(status_code=404, detail="Blog post not found")

    data = {
        "id": post.id,
        "title": post.title,
        "slug": post.slug,
        "excerpt": post.excerpt,
        "content": post.content,
        "featured_image": post.featured_image,
        "author_name": post.author_name,
        "category_name": post.category.name if post.category else None,
        "category_slug": post.category.slug if post.category else None,
        "published_at": post.published_at.isoformat() if post.published_at else None,
        "created_at": post.created_at.isoformat() if post.created_at else None,
    }
    await cache.set(cache_key, data, ttl=BLOG_CACHE_TTL)
    return data


# ---------------------------------------------------------------------------
# Public: Blog categories
# ---------------------------------------------------------------------------

@router.get("/sites/{site_id}/blog/categories")
async def list_blog_categories(
    site_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List blog categories with post counts (public)."""
    cache_key = f"blog:categories:{site_id}"
    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

    result = await db.execute(
        select(BlogCategory, func.count(BlogPost.id).label("post_count"))
        .outerjoin(
            BlogPost,
            (BlogPost.category_id == BlogCategory.id)
            & (BlogPost.status == BlogPostStatus.PUBLISHED),
        )
        .where(BlogCategory.site_id == site_id)
        .group_by(BlogCategory.id)
        .order_by(BlogCategory.sort_order, BlogCategory.name)
    )

    data = [
        {
            "id": cat.id,
            "name": cat.name,
            "slug": cat.slug,
            "description": cat.description,
            "post_count": count,
        }
        for cat, count in result.all()
    ]
    await cache.set(cache_key, data, ttl=BLOG_CACHE_TTL)
    return data


# ---------------------------------------------------------------------------
# Public: App Library (no auth required)
# ---------------------------------------------------------------------------

@router.get("/apps")
async def list_apps(
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List all active apps for the public app library."""
    cache_key = "apps:library"
    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

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

    data = [
        {
            "id": app.id,
            "slug": app.slug,
            "name": app.name,
            "description": app.description,  # JSON: {"en": "...", "sv": "..."}
            "icon_url": app.icon_url,
            "category": app.category,
            "pricing_type": app.pricing_type.value if app.pricing_type else "FREE",
            "price": float(app.price) if app.price else 0,
            "install_count": app.install_count or 0,
            "avg_rating": round(float(avg), 1),
            "review_count": cnt,
            "version": app.version,
        }
        for app, avg, cnt in result.all()
    ]
    await cache.set(cache_key, data, ttl=300)
    return data


@router.get("/apps/{slug}")
async def get_app_detail(
    slug: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get full app detail for the showcase page."""
    cache_key = f"apps:detail:{slug}"
    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

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
        raise HTTPException(status_code=404, detail="App not found")

    app, avg, cnt = row
    data = {
        "id": app.id,
        "slug": app.slug,
        "name": app.name,
        "description": app.description,
        "long_description": app.long_description,
        "icon_url": app.icon_url,
        "version": app.version,
        "category": app.category,
        "screenshots": app.screenshots or [],
        "features": app.features or [],
        "developer_name": app.developer_name,
        "developer_url": app.developer_url,
        "pricing_type": app.pricing_type.value if app.pricing_type else "FREE",
        "price": float(app.price) if app.price else 0,
        "price_description": app.price_description,
        "install_count": app.install_count or 0,
        "avg_rating": round(float(avg), 1),
        "review_count": cnt,
    }
    await cache.set(cache_key, data, ttl=300)
    return data


@router.get("/apps/{slug}/reviews")
async def get_app_reviews(
    slug: str,
    locale: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Get reviews for an app (public). Optionally filter by locale."""
    cache_key = f"apps:reviews:{slug}:l:{locale or 'all'}"
    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

    query = (
        select(AppReview, User.full_name)
        .join(App, AppReview.app_id == App.id)
        .join(User, AppReview.user_id == User.id)
        .where(App.slug == slug)
    )
    if locale:
        query = query.where(AppReview.locale == locale)
    query = query.order_by(AppReview.created_at.desc())

    result = await db.execute(query)

    data = [
        {
            "id": review.id,
            "user_name": name or "Anonymous",
            "rating": review.rating,
            "title": review.title,
            "body": review.body,
            "locale": review.locale,
            "created_at": review.created_at.isoformat() if review.created_at else None,
        }
        for review, name in result.all()
    ]
    await cache.set(cache_key, data, ttl=300)
    return data


# ---------------------------------------------------------------------------
# Public: Chat (viewer endpoints)
# ---------------------------------------------------------------------------


async def _verify_chat_installed(site_id: str, db: AsyncSession) -> None:
    """Raise 404 if chat app is not installed on the site."""
    result = await db.execute(
        select(App.slug)
        .join(AppInstallation, AppInstallation.app_id == App.id)
        .where(
            App.slug == "chat",
            AppInstallation.site_id == site_id,
            AppInstallation.is_active == True,  # noqa: E712
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Chat is not available on this site")


@router.post("/sites/{site_id}/chat/conversations")
async def create_chat_conversation(
    site_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a new chat conversation (visitor-initiated)."""
    await _verify_chat_installed(site_id, db)

    import uuid as _uuid
    from datetime import datetime, timezone as tz

    email = (body.get("email") or "").strip().lower()
    name = (body.get("name") or "").strip()
    message = (body.get("message") or "").strip()
    subject = (body.get("subject") or "").strip()

    if not email or "@" not in email or len(email) > 320:
        raise HTTPException(status_code=400, detail="A valid email is required")
    if not message or len(message) > 5000:
        raise HTTPException(status_code=400, detail="Message is required (max 5000 characters)")

    now = datetime.now(tz.utc)

    conv = ChatConversation(
        id=str(_uuid.uuid4()),
        site_id=site_id,
        visitor_email=email,
        visitor_name=name or None,
        status="open",
        subject=subject or None,
        last_message_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(conv)
    await db.flush()

    msg = ChatMessage(
        id=str(_uuid.uuid4()),
        conversation_id=conv.id,
        sender_type="visitor",
        sender_name=name or email.split("@")[0],
        content=message,
        created_at=now,
    )
    db.add(msg)
    await db.commit()

    # Send email notification to site owner
    try:
        from app.email.service import send_transactional_email
        from app.sites.models import GeneratedSite, Lead

        site_result = await db.execute(
            select(GeneratedSite).where(GeneratedSite.id == site_id)
        )
        site = site_result.scalar_one_or_none()
        if site and site.claimed_by:
            owner_result = await db.execute(
                select(User).where(User.id == site.claimed_by)
            )
            owner = owner_result.scalar_one_or_none()
            if owner and owner.email:
                site_name = "din webbplats"
                if site.site_data:
                    site_name = site.site_data.get("business", {}).get("name") or site.site_data.get("meta", {}).get("title") or site_name

                await send_transactional_email(
                    to=owner.email,
                    subject=f"Nytt chattmeddelande från {name or email} - {site_name}",
                    html=f"""
                    <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
                        <h2 style="color: #333;">Nytt meddelande via Chat by Qvicko</h2>
                        <p style="color: #555;"><strong>Från:</strong> {name or 'Anonym'} ({email})</p>
                        {f'<p style="color: #555;"><strong>Ämne:</strong> {subject}</p>' if subject else ''}
                        <div style="background: #f7f7f7; padding: 16px; border-radius: 8px; margin: 16px 0;">
                            <p style="margin: 0; color: #555;">{message}</p>
                        </div>
                        <p style="color: #888; font-size: 14px;">
                            Svara på detta meddelande från din Qvicko-dashboard.
                        </p>
                        <hr style="border: none; border-top: 1px solid #eee; margin: 24px 0;" />
                        <p style="color: #aaa; font-size: 12px;">Chat by Qvicko</p>
                    </div>
                    """,
                    text=f"Nytt chattmeddelande från {name or email}:\n\n{message}\n\n---\nChat by Qvicko",
                    from_name="Chat by Qvicko",
                )
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Failed to send chat notification email")

    return {
        "conversation_id": conv.id,
        "message_id": msg.id,
    }


@router.post("/sites/{site_id}/chat/conversations/{conversation_id}/messages")
async def send_chat_message(
    site_id: str,
    conversation_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Send a follow-up message to an existing conversation (visitor)."""
    await _verify_chat_installed(site_id, db)

    import uuid as _uuid
    from datetime import datetime, timezone as tz

    email = (body.get("email") or "").strip().lower()
    message = (body.get("message") or "").strip()

    if not message or len(message) > 5000:
        raise HTTPException(status_code=400, detail="Message is required (max 5000 characters)")

    result = await db.execute(
        select(ChatConversation).where(
            ChatConversation.id == conversation_id,
            ChatConversation.site_id == site_id,
        )
    )
    conv = result.scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if email and conv.visitor_email != email:
        raise HTTPException(status_code=403, detail="Email does not match conversation")

    now = datetime.now(tz.utc)
    msg = ChatMessage(
        id=str(_uuid.uuid4()),
        conversation_id=conv.id,
        sender_type="visitor",
        sender_name=conv.visitor_name or conv.visitor_email.split("@")[0],
        content=message,
        created_at=now,
    )
    db.add(msg)
    conv.last_message_at = now
    conv.updated_at = now
    if conv.status == "closed":
        conv.status = "open"
    await db.commit()

    return {
        "message_id": msg.id,
    }


@router.get("/sites/{site_id}/chat/conversations/{conversation_id}/messages")
async def get_chat_messages(
    site_id: str,
    conversation_id: str,
    email: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Get messages for a conversation (viewer). Requires visitor email for verification."""
    await _verify_chat_installed(site_id, db)

    result = await db.execute(
        select(ChatConversation).where(
            ChatConversation.id == conversation_id,
            ChatConversation.site_id == site_id,
        )
    )
    conv = result.scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if email and conv.visitor_email != email.strip().lower():
        raise HTTPException(status_code=403, detail="Email does not match conversation")

    msg_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.created_at.asc())
    )
    messages = msg_result.scalars().all()

    return [
        {
            "id": m.id,
            "sender_type": m.sender_type,
            "sender_name": m.sender_name,
            "content": m.content,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in messages
    ]


@router.get("/sites/{site_id}/chat/conversations/lookup")
async def lookup_chat_conversations(
    site_id: str,
    email: str,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Look up conversations for a visitor by email."""
    await _verify_chat_installed(site_id, db)

    email = email.strip().lower()
    result = await db.execute(
        select(ChatConversation)
        .where(
            ChatConversation.site_id == site_id,
            ChatConversation.visitor_email == email,
        )
        .order_by(ChatConversation.last_message_at.desc().nullslast())
        .limit(20)
    )
    convs = result.scalars().all()

    return [
        {
            "id": c.id,
            "status": c.status,
            "subject": c.subject,
            "last_message_at": c.last_message_at.isoformat() if c.last_message_at else None,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in convs
    ]


# ---------------------------------------------------------------------------
# Public: Bookings (viewer endpoints)
# ---------------------------------------------------------------------------

BOOKINGS_CACHE_TTL = 300  # 5 minutes


async def _verify_bookings_installed(site_id: str, db: AsyncSession) -> None:
    """Raise 404 if bookings app is not installed on the site."""
    result = await db.execute(
        select(App.slug)
        .join(AppInstallation, AppInstallation.app_id == App.id)
        .where(
            App.slug == "bookings",
            AppInstallation.site_id == site_id,
            AppInstallation.is_active == True,  # noqa: E712
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Bookings is not available on this site")


@router.get("/sites/{site_id}/bookings/services")
async def list_booking_services(
    site_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List active booking services for a site (public)."""
    cache_key = f"bookings:services:{site_id}"
    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

    await _verify_bookings_installed(site_id, db)

    result = await db.execute(
        select(BookingService)
        .where(
            BookingService.site_id == site_id,
            BookingService.is_active == True,  # noqa: E712
        )
        .order_by(BookingService.sort_order, BookingService.name)
    )
    services = result.scalars().all()

    data = [
        {
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "duration_minutes": s.duration_minutes,
            "price": float(s.price) if s.price else 0,
            "currency": s.currency,
        }
        for s in services
    ]
    await cache.set(cache_key, data, ttl=BOOKINGS_CACHE_TTL)
    return data


@router.get("/sites/{site_id}/bookings/form-fields")
async def list_booking_form_fields(
    site_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List active booking form fields for a site (public)."""
    cache_key = f"bookings:form_fields:{site_id}"
    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

    await _verify_bookings_installed(site_id, db)

    result = await db.execute(
        select(BookingFormField)
        .where(
            BookingFormField.site_id == site_id,
            BookingFormField.is_active == True,  # noqa: E712
        )
        .order_by(BookingFormField.sort_order, BookingFormField.label)
    )
    fields = result.scalars().all()

    data = [
        {
            "id": f.id,
            "label": f.label,
            "field_type": f.field_type,
            "placeholder": f.placeholder,
            "is_required": f.is_required,
            "options": f.options,
        }
        for f in fields
    ]
    await cache.set(cache_key, data, ttl=BOOKINGS_CACHE_TTL)
    return data


@router.get("/sites/{site_id}/bookings/payment-methods")
async def get_booking_payment_methods(
    site_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get enabled payment methods for a site (public)."""
    cache_key = f"bookings:payment_methods:{site_id}"
    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

    await _verify_bookings_installed(site_id, db)

    result = await db.execute(
        select(BookingPaymentMethods).where(BookingPaymentMethods.site_id == site_id)
    )
    pm = result.scalar_one_or_none()

    data = {
        "stripe_connect_enabled": pm.stripe_connect_enabled if pm else False,
        "on_site_enabled": pm.on_site_enabled if pm else True,
        "klarna_enabled": pm.klarna_enabled if pm else False,
        "swish_enabled": pm.swish_enabled if pm else False,
    }
    await cache.set(cache_key, data, ttl=BOOKINGS_CACHE_TTL)
    return data


@router.post("/sites/{site_id}/bookings")
async def create_booking(
    site_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Submit a new booking (public, no auth required)."""
    await _verify_bookings_installed(site_id, db)

    import uuid as _uuid
    from datetime import datetime, timezone as tz

    # Validate required fields
    customer_name = (body.get("customer_name") or "").strip()
    customer_email = (body.get("customer_email") or "").strip().lower()
    customer_phone = (body.get("customer_phone") or "").strip() or None
    service_id = body.get("service_id")
    form_data = body.get("form_data") or {}
    payment_method = (body.get("payment_method") or "").strip() or None
    booking_date_str = body.get("booking_date")
    notes = (body.get("notes") or "").strip() or None

    if not customer_name:
        raise HTTPException(status_code=400, detail="Customer name is required")
    if not customer_email or "@" not in customer_email or len(customer_email) > 320:
        raise HTTPException(status_code=400, detail="A valid email is required")

    # Validate form_data against configured required fields
    result = await db.execute(
        select(BookingFormField).where(
            BookingFormField.site_id == site_id,
            BookingFormField.is_active == True,  # noqa: E712
            BookingFormField.is_required == True,  # noqa: E712
        )
    )
    required_fields = result.scalars().all()
    for field in required_fields:
        field_value = form_data.get(field.label, "")
        if not field_value or (isinstance(field_value, str) and not field_value.strip()):
            raise HTTPException(
                status_code=400,
                detail=f"Field '{field.label}' is required",
            )

    # Look up service
    service_name = None
    amount = 0.0
    currency = "SEK"
    if service_id:
        svc_result = await db.execute(
            select(BookingService).where(
                BookingService.id == service_id,
                BookingService.site_id == site_id,
                BookingService.is_active == True,  # noqa: E712
            )
        )
        service = svc_result.scalar_one_or_none()
        if service is None:
            raise HTTPException(status_code=400, detail="Service not found")
        service_name = service.name
        amount = float(service.price) if service.price else 0
        currency = service.currency

    # Parse booking_date
    booking_date = None
    if booking_date_str:
        try:
            booking_date = datetime.fromisoformat(booking_date_str)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid booking_date format")

    now = datetime.now(tz.utc)
    booking = Booking(
        id=str(_uuid.uuid4()),
        site_id=site_id,
        service_id=service_id,
        service_name=service_name,
        customer_name=customer_name,
        customer_email=customer_email,
        customer_phone=customer_phone,
        form_data=form_data if form_data else None,
        status=BookingStatus.PENDING,
        payment_method=payment_method,
        payment_status=BookingPaymentStatus.UNPAID,
        amount=amount,
        currency=currency,
        notes=notes,
        booking_date=booking_date,
        created_at=now,
        updated_at=now,
    )
    db.add(booking)

    stripe_client_secret = None

    # If payment_method is "stripe", create a PaymentIntent
    if payment_method == "stripe" and amount > 0:
        # TODO: Integrate with app.payments.service when available
        # For now, leave a placeholder for Stripe PaymentIntent creation
        pass

    await db.commit()

    # Send notification email to site owner
    try:
        from app.email.service import send_transactional_email
        from app.email.booking_templates import (
            build_booking_owner_notification_email,
            build_booking_customer_confirmation_email,
        )
        from app.sites.models import GeneratedSite

        site_result = await db.execute(
            select(GeneratedSite).where(GeneratedSite.id == site_id)
        )
        site = site_result.scalar_one_or_none()
        site_name = "din webbplats"
        if site and site.site_data:
            site_name = site.site_data.get("business", {}).get("name") or site.site_data.get("meta", {}).get("title") or site_name

        booking_date_display = booking_date.strftime("%Y-%m-%d %H:%M") if booking_date else "Ej angivet"
        dashboard_url = f"{settings.FRONTEND_URL}/dashboard/sites/{site_id}/apps/bookings/bookings"

        if site and site.claimed_by:
            owner_result = await db.execute(
                select(User).where(User.id == site.claimed_by)
            )
            owner = owner_result.scalar_one_or_none()
            if owner and owner.email:
                owner_subj, owner_html, owner_text = build_booking_owner_notification_email(
                    owner_name=owner.full_name or owner.email,
                    site_name=site_name,
                    customer_name=customer_name,
                    customer_email=customer_email,
                    customer_phone=customer_phone,
                    service_name=service_name,
                    booking_date=booking_date_display,
                    amount=amount,
                    currency=currency,
                    payment_method=payment_method,
                    dashboard_url=dashboard_url,
                    form_data=form_data if form_data else None,
                )
                await send_transactional_email(
                    to=owner.email,
                    subject=owner_subj,
                    html=owner_html,
                    text=owner_text,
                    from_name="Bookings by Qvicko",
                )
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Failed to send booking owner notification email")

    # Send confirmation email to customer
    try:
        from app.email.service import send_transactional_email
        from app.email.booking_templates import build_booking_customer_confirmation_email

        if not site_name or site_name == "din webbplats":
            site_result2 = await db.execute(
                select(GeneratedSite).where(GeneratedSite.id == site_id)
            )
            site2 = site_result2.scalar_one_or_none()
            if site2 and site2.site_data:
                site_name = site2.site_data.get("business", {}).get("name") or site2.site_data.get("meta", {}).get("title") or site_name

        booking_date_display = booking_date.strftime("%Y-%m-%d %H:%M") if booking_date else "Ej angivet"

        cust_subj, cust_html, cust_text = build_booking_customer_confirmation_email(
            customer_name=customer_name,
            site_name=site_name,
            service_name=service_name,
            booking_date=booking_date_display,
            amount=amount,
            currency=currency,
        )
        await send_transactional_email(
            to=customer_email,
            subject=cust_subj,
            html=cust_html,
            text=cust_text,
            from_name="Bookings by Qvicko",
        )
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Failed to send booking customer confirmation email")

    response = {
        "booking_id": booking.id,
    }
    if stripe_client_secret:
        response["stripe_client_secret"] = stripe_client_secret
    return response
