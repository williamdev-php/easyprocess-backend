import asyncio
import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from slowapi.middleware import SlowAPIMiddleware

from app.autoblogger.exceptions import AutoBloggerError, autoblogger_exception_handler
from app.autoblogger.middleware import RequestIDMiddleware

from sqlalchemy import text

from app.cache import cache
from app.config import settings
from app.rate_limit import limiter
from app.database import engine, async_session, get_db_session, Base, SCHEMA

# Import all models so Base.metadata knows about them
from app.auth.models import User, Session, AuditLog, SocialAccount, SettingsAuditLog, SuperuserPromotion  # noqa: F401
from app.sites.models import Industry, Lead, ScrapedData, GeneratedSite, SiteVersion, OutreachEmail, InboundEmail, PageView, CustomDomain, DomainPurchase, GscConnection, AIChatSession, AIChatMessage  # noqa: F401
from app.billing.models import Subscription, Payment, BillingDetails  # noqa: F401
from app.media.models import MediaFile  # noqa: F401
from app.smartlead.models import SmartleadCampaign, SmartleadEmailAccount  # noqa: F401
from app.tracking.models import TrackingEvent  # noqa: F401
from app.support.models import SupportTicket  # noqa: F401
from app.support.notifications import Notification  # noqa: F401
from app.apps.models import App, AppInstallation, AppReview, BlogPost, BlogCategory, ChatConversation, ChatMessage, BookingService, BookingFormField, BookingPaymentMethods, Booking  # noqa: F401
from app.payments.models import ConnectedAccount, PlatformPayment  # noqa: F401
from app.oauth.models import OAuthAuthorizationCode, OAuthAccessToken  # noqa: F401
from app.autoblogger.models import Source, BlogPostAB, ContentSchedule, UserSettings, CreditBalance, CreditTransaction, AutoBloggerBase, AUTOBLOGGER_SCHEMA, AutoBloggerSubscription, AutoBloggerPayment, AnalyticsEvent, AutoBloggerUser, AutoBloggerSession, AutoBloggerAuditLog, AutoBloggerSocialAccount, AutoBloggerPasswordResetToken, AutoBloggerEmailVerificationToken  # noqa: F401
from app.feyra.models import FeyraBase, FEYRA_SCHEMA, EmailAccount, WarmupSettings, WarmupEmail, Lead as FeyraLead, CrawlJob, CrawlResult, Campaign, CampaignStep, CampaignLead, SentEmail, GlobalSettings  # noqa: F401


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Verify DB connectivity, then create schema/tables (dev convenience; use Alembic in production)
    async with engine.begin() as conn:
        try:
            await conn.execute(text("SELECT 1"))
            logger.info("Database connection verified")
        except Exception as e:
            logger.error("Database connection failed: %s", e)
            raise RuntimeError("Cannot connect to database") from e
        await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
        await conn.run_sync(Base.metadata.create_all)
        # AutoBlogger schema
        await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {AUTOBLOGGER_SCHEMA}"))
        await conn.run_sync(AutoBloggerBase.metadata.create_all)
        # Feyra schema
        await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {FEYRA_SCHEMA}"))
        await conn.run_sync(FeyraBase.metadata.create_all)

    # Verify Supabase Storage connectivity
    if settings.SUPABASE_URL:
        from app.storage.supabase import check_storage_health
        if check_storage_health():
            logger.info("Supabase Storage bucket '%s' is accessible", settings.SUPABASE_STORAGE_BUCKET)
        else:
            logger.warning("Supabase Storage bucket '%s' is NOT accessible — image storage will fail", settings.SUPABASE_STORAGE_BUCKET)

    # Re-enqueue orphaned leads from previous server run, then start stuck recovery loop
    async def _recover_orphaned_leads():
        """Re-enqueue leads stuck in SCRAPING/GENERATING from a prior server crash."""
        from app.sites.models import Lead, LeadStatus
        from app.pipeline_manager import pipeline_manager
        from sqlalchemy import select
        try:
            async with async_session() as session:
                result = await session.execute(
                    select(Lead).where(
                        Lead.status.in_([LeadStatus.SCRAPING, LeadStatus.GENERATING])
                    )
                )
                orphaned = result.scalars().all()
                if orphaned:
                    for lead in orphaned:
                        lead.status = LeadStatus.NEW
                        lead.error_message = None
                    await session.commit()
                    for lead in orphaned:
                        accepted = await pipeline_manager.enqueue(str(lead.id))
                        logger.info(
                            "Re-enqueued orphaned lead %s (accepted=%s)", lead.id, accepted
                        )
                    logger.info("Re-enqueued %d orphaned leads at startup", len(orphaned))
        except Exception:
            logger.exception("Orphaned lead recovery failed at startup")

    async def _stuck_lead_recovery_loop():
        from app.sites.models import Lead, LeadStatus
        from sqlalchemy import select, and_
        # On startup: re-enqueue orphaned leads first
        await asyncio.sleep(5)  # brief delay for app init
        await _recover_orphaned_leads()
        # Then run periodic stuck detection
        await asyncio.sleep(295)  # total ~5 min before first stuck check
        while True:
            try:
                threshold = datetime.now(timezone.utc) - timedelta(minutes=10)
                async with async_session() as session:
                    result = await session.execute(
                        select(Lead).where(
                            and_(
                                Lead.status.in_([LeadStatus.SCRAPING, LeadStatus.GENERATING]),
                                Lead.updated_at < threshold,
                            )
                        )
                    )
                    stuck_leads = result.scalars().all()
                    if stuck_leads:
                        for lead in stuck_leads:
                            lead.status = LeadStatus.FAILED
                            lead.error_message = "Pipeline timed out (stuck recovery)"
                            logger.warning("Recovered stuck lead %s (was %s)", lead.id, lead.status)
                        await session.commit()
                        logger.info("Recovered %d stuck leads", len(stuck_leads))
            except Exception:
                logger.exception("Stuck lead recovery failed")
            await asyncio.sleep(300)  # every 5 minutes

    stuck_recovery_task = asyncio.create_task(_stuck_lead_recovery_loop())

    # Start daily expiration check background task with exponential backoff
    async def _expiration_loop():
        from app.billing.expiration import check_expired_sites
        consecutive_failures = 0
        base_interval = 86400  # 24 hours
        while True:
            try:
                await check_expired_sites()
                logger.info("Site expiration check completed")
                consecutive_failures = 0
                await asyncio.sleep(base_interval)
            except Exception:
                consecutive_failures += 1
                # Backoff: 5min, 15min, 45min, capped at 2 hours
                backoff = min(300 * (3 ** (consecutive_failures - 1)), 7200)
                logger.exception(
                    "Site expiration check failed (attempt %d), retrying in %ds",
                    consecutive_failures, backoff,
                )
                await asyncio.sleep(backoff)

    expiration_task = asyncio.create_task(_expiration_loop())

    # Smartlead status sync: poll every 15 minutes for email status updates
    smartlead_task: asyncio.Task | None = None

    async def _smartlead_sync_loop():
        from app.smartlead.service import sync_lead_statuses
        from app.database import get_db_session
        await asyncio.sleep(60)  # Initial delay — let app stabilize
        while True:
            try:
                async with get_db_session() as db:
                    await sync_lead_statuses(db)
                logger.info("Smartlead status sync completed")
            except Exception:
                logger.exception("Smartlead status sync failed")
            await asyncio.sleep(900)  # 15 minutes

    if settings.SMARTLEAD_API_KEY:
        smartlead_task = asyncio.create_task(_smartlead_sync_loop())
    else:
        logger.info("Smartlead sync disabled — SMARTLEAD_API_KEY not configured")

    # AutoBlogger: monthly credit reset check (every 6 hours)
    async def _credit_reset_loop():
        from app.autoblogger.credits import reset_monthly_credits
        await asyncio.sleep(120)  # Initial delay
        while True:
            try:
                async with get_db_session() as db:
                    count = await reset_monthly_credits(db)
                    if count > 0:
                        logger.info("AutoBlogger: reset credits for %d users", count)
            except Exception:
                logger.exception("AutoBlogger credit reset failed")
            await asyncio.sleep(21600)  # 6 hours

    credit_reset_task = asyncio.create_task(_credit_reset_loop())

    # AutoBlogger: schedule execution worker (every 60 seconds)
    async def _schedule_execution_loop():
        from app.autoblogger.models import ContentSchedule, BlogPostAB, PostStatus, Source, UserSettings
        from app.autoblogger.generator import generate_blog_post
        from app.autoblogger.images import generate_featured_image
        from app.autoblogger.credits import validate_credits, deduct_credits, calculate_credits_for_post
        from app.autoblogger.scheduler import calculate_next_run_at
        from sqlalchemy import select, and_
        import random

        await asyncio.sleep(30)  # Initial delay
        while True:
            try:
                now = datetime.now(timezone.utc)
                async with get_db_session() as db:
                    # Find due schedules
                    result = await db.execute(
                        select(ContentSchedule).where(
                            and_(
                                ContentSchedule.is_active.is_(True),
                                ContentSchedule.next_run_at <= now,
                            )
                        )
                    )
                    due_schedules = result.scalars().all()

                    for schedule in due_schedules:
                        try:
                            # Fetch source for brand_voice
                            src_result = await db.execute(
                                select(Source).where(Source.id == schedule.source_id)
                            )
                            source = src_result.scalar_one_or_none()
                            if not source or not source.is_active:
                                logger.warning("Schedule %s: source not found or inactive", schedule.id)
                                continue

                            # Fetch user settings
                            settings_result = await db.execute(
                                select(UserSettings).where(UserSettings.user_id == schedule.user_id)
                            )
                            user_settings = settings_result.scalar_one_or_none()
                            ai_model = user_settings.ai_model if user_settings else "claude-sonnet-4-20250514"
                            auto_publish = schedule.auto_publish
                            image_gen = user_settings.image_generation if user_settings else True

                            # Generate posts_per_day posts
                            successful_posts = 0
                            for i in range(schedule.posts_per_day):
                                # Pick a topic from the schedule's topic list (cycle through)
                                topic = None
                                if schedule.topics:
                                    topic = schedule.topics[(schedule.posts_generated + i) % len(schedule.topics)]
                                else:
                                    topic = f"Blog post for {source.name}"

                                keywords = schedule.keywords or []

                                # Check credits
                                try:
                                    await validate_credits(db, schedule.user_id)
                                except Exception:
                                    logger.warning("Schedule %s: user %s has insufficient credits", schedule.id, schedule.user_id)
                                    break

                                # Create post record
                                post = BlogPostAB(
                                    source_id=schedule.source_id,
                                    user_id=schedule.user_id,
                                    title=topic,
                                    language=schedule.language,
                                    status=PostStatus.GENERATING,
                                )
                                db.add(post)
                                await db.flush()

                                try:
                                    gen_result = await generate_blog_post(
                                        topic=topic,
                                        keywords=keywords,
                                        language=schedule.language,
                                        brand_voice=source.brand_voice,
                                        ai_model=ai_model,
                                    )

                                    # Optional image
                                    featured_url = None
                                    if image_gen:
                                        featured_url = await generate_featured_image(
                                            title=gen_result.title,
                                            keywords=keywords,
                                            brand_images=source.brand_images,
                                        )

                                    post.title = gen_result.title
                                    post.slug = gen_result.slug
                                    post.content = gen_result.content
                                    post.excerpt = gen_result.excerpt
                                    post.meta_title = gen_result.meta_title
                                    post.meta_description = gen_result.meta_description
                                    post.tags = gen_result.tags
                                    post.schema_markup = gen_result.schema_markup
                                    post.internal_links = gen_result.internal_links
                                    post.generation_prompt = gen_result.generation_prompt
                                    post.target_keyword = keywords[0] if keywords else None
                                    post.ai_model = gen_result.ai_model
                                    post.word_count = gen_result.word_count
                                    post.reading_time_minutes = gen_result.reading_time_minutes
                                    post.featured_image_url = featured_url

                                    credits = calculate_credits_for_post(gen_result.word_count)
                                    await deduct_credits(
                                        db, schedule.user_id, credits,
                                        description=f"Scheduled post: {gen_result.title[:100]}",
                                        post_id=post.id,
                                    )
                                    post.credits_used = credits

                                    post.status = PostStatus.PUBLISHED if auto_publish else PostStatus.REVIEW
                                    if auto_publish:
                                        post.published_at = datetime.now(timezone.utc)
                                    post.updated_at = datetime.now(timezone.utc)

                                    logger.info("Schedule %s: generated post '%s'", schedule.id, gen_result.title)
                                    successful_posts += 1

                                    # Track POST_GENERATED analytics event
                                    from app.autoblogger.analytics import track_event
                                    from app.autoblogger.models import AnalyticsEventType
                                    await track_event(db, schedule.user_id, AnalyticsEventType.POST_GENERATED, {
                                        "post_id": post.id,
                                        "model": gen_result.ai_model,
                                        "language": schedule.language,
                                        "word_count": gen_result.word_count,
                                        "credits_used": credits,
                                        "scheduled": True,
                                        "schedule_id": schedule.id,
                                    })

                                except Exception as gen_err:
                                    post.status = PostStatus.FAILED
                                    post.error_message = str(gen_err)
                                    post.updated_at = datetime.now(timezone.utc)
                                    logger.exception("Schedule %s: post generation failed", schedule.id)

                                    # Track GENERATION_FAILED analytics event
                                    from app.autoblogger.analytics import track_event as track_fail
                                    from app.autoblogger.models import AnalyticsEventType as AET
                                    await track_fail(db, schedule.user_id, AET.GENERATION_FAILED, {
                                        "post_id": post.id,
                                        "error": str(gen_err)[:500],
                                        "schedule_id": schedule.id,
                                    })

                            # Track SCHEDULE_EXECUTED analytics event
                            from app.autoblogger.analytics import track_event as track_sched
                            from app.autoblogger.models import AnalyticsEventType as AET2
                            await track_sched(db, schedule.user_id, AET2.SCHEDULE_EXECUTED, {
                                "schedule_id": schedule.id,
                                "posts_attempted": schedule.posts_per_day,
                                "posts_succeeded": successful_posts,
                                "success": successful_posts > 0,
                            })

                            # Update schedule
                            schedule.last_run_at = datetime.now(timezone.utc)
                            schedule.next_run_at = calculate_next_run_at(
                                frequency=schedule.frequency,
                                preferred_time=schedule.preferred_time,
                                timezone_str=schedule.timezone,
                                days_of_week=schedule.days_of_week,
                                last_run_at=schedule.last_run_at,
                            )
                            schedule.posts_generated += successful_posts
                            schedule.updated_at = datetime.now(timezone.utc)
                            await db.flush()

                        except Exception:
                            logger.exception("Schedule %s execution failed", schedule.id)

            except Exception:
                logger.exception("Schedule execution loop error")
            await asyncio.sleep(60)  # Check every 60 seconds

    schedule_worker_task = asyncio.create_task(_schedule_execution_loop())

    # AutoBlogger: stuck generation recovery + cleanup (every 5 minutes)
    async def _ab_stuck_recovery_loop():
        from app.autoblogger.cleanup import run_all_cleanup

        await asyncio.sleep(300)  # Initial delay: 5 min
        while True:
            try:
                async with get_db_session() as db:
                    summary = await run_all_cleanup(db)
                    if any(summary.values()):
                        logger.info("AutoBlogger cleanup: %s", summary)
            except Exception:
                logger.exception("AutoBlogger stuck recovery failed")
            await asyncio.sleep(300)  # Every 5 minutes

    ab_stuck_task = asyncio.create_task(_ab_stuck_recovery_loop())

    yield

    # Graceful shutdown: cancel background tasks and let in-flight work drain.
    expiration_task.cancel()
    stuck_recovery_task.cancel()
    credit_reset_task.cancel()
    schedule_worker_task.cancel()
    ab_stuck_task.cancel()
    tasks_to_cancel = [expiration_task, stuck_recovery_task, credit_reset_task, schedule_worker_task, ab_stuck_task]
    if smartlead_task is not None:
        smartlead_task.cancel()
        tasks_to_cancel.append(smartlead_task)
    for task in tasks_to_cancel:
        try:
            await task
        except asyncio.CancelledError:
            pass
    # Close shared httpx clients
    from app.ai.generator import close_http_client
    await close_http_client()
    from app.autoblogger.generator import close_http_client as close_ab_gen_client
    from app.autoblogger.images import close_http_client as close_ab_img_client
    from app.autoblogger.integrations.shopify import close_http_client as close_shopify_client
    await close_ab_gen_client()
    await close_ab_img_client()
    await close_shopify_client()
    await cache.close()
    await engine.dispose()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Qvicko API",
    description="Backend for the Qvicko platform",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow configured origins + any viewer subdomain / custom domain.
# The viewer sends tracking beacons from *.qvickosite.com and custom domains,
# so we need a regex pattern in addition to the explicit allow-list.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_origin_regex=r"https?://(.+\.)?" + settings.BASE_DOMAIN.replace(".", r"\.") + r"(:\d+)?",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_exception_handler(AutoBloggerError, autoblogger_exception_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(RequestIDMiddleware)


# Request logging middleware — log AutoBlogger API requests with response times
@app.middleware("http")
async def log_autoblogger_requests(request, call_next):
    import time as _time
    path = request.url.path
    if path.startswith("/api/autoblogger"):
        start = _time.monotonic()
        response = await call_next(request)
        duration_ms = round((_time.monotonic() - start) * 1000, 1)
        logger.info(
            "AutoBlogger API: method=%s path=%s status=%d duration_ms=%.1f",
            request.method, path, response.status_code, duration_ms,
        )
        return response
    return await call_next(request)


# REST routes
from app.auth.router import router as auth_router  # noqa: E402
from app.sites.router import router as sites_router  # noqa: E402
from app.sites.router import webhook_router  # noqa: E402
from app.billing.router import router as billing_router  # noqa: E402
from app.billing.router import webhook_router as stripe_webhook_router  # noqa: E402
from app.media.router import router as media_router  # noqa: E402
from app.tracking.router import router as tracking_router  # noqa: E402
from app.apps.router import router as apps_router  # noqa: E402
from app.gsc.router import router as gsc_router  # noqa: E402
from app.payments.router import router as payments_router  # noqa: E402
from app.autoblogger.router import router as autoblogger_router  # noqa: E402
from app.autoblogger.api import router as autoblogger_api_router  # noqa: E402
from app.autoblogger.billing import router as autoblogger_billing_router  # noqa: E402
from app.autoblogger.integrations.shopify_router import router as shopify_router  # noqa: E402
from app.autoblogger.integrations.qvicko_router import router as qvicko_router  # noqa: E402
from app.autoblogger.integrations.wordpress_router import router as wordpress_router  # noqa: E402
from app.feyra.router import router as feyra_router  # noqa: E402
from app.feyra.api import router as feyra_api_router  # noqa: E402
from app.autoblogger.analytics import router as autoblogger_analytics_router  # noqa: E402
from app.autoblogger.health import router as autoblogger_health_router  # noqa: E402
from app.oauth.router import router as oauth_router  # noqa: E402
from app.oauth.blog_api import router as oauth_blog_router  # noqa: E402
from app.newsletter.router import router as newsletter_router  # noqa: E402
from app.sites.ai_chat import router as ai_chat_router  # noqa: E402

app.include_router(auth_router)
app.include_router(sites_router)
app.include_router(webhook_router)
app.include_router(billing_router)
app.include_router(stripe_webhook_router)
app.include_router(media_router)
app.include_router(tracking_router)
app.include_router(apps_router)
app.include_router(gsc_router)
app.include_router(payments_router)
app.include_router(autoblogger_router)
app.include_router(autoblogger_api_router)
app.include_router(autoblogger_billing_router)
app.include_router(autoblogger_analytics_router)
app.include_router(autoblogger_health_router)
app.include_router(shopify_router)
app.include_router(qvicko_router)
app.include_router(wordpress_router)
app.include_router(oauth_router)
app.include_router(oauth_blog_router)
app.include_router(feyra_router)
app.include_router(feyra_api_router)
app.include_router(newsletter_router)
app.include_router(ai_chat_router)

# GraphQL
from app.graphql.schema import graphql_app  # noqa: E402

app.include_router(graphql_app, prefix="/graphql")


@app.get("/health")
async def health() -> dict:
    result: dict = {"status": "ok", "cache": cache.backend}
    if settings.SUPABASE_URL:
        from app.storage.supabase import check_storage_health
        result["storage"] = check_storage_health()
    return result


@app.get("/health/pipeline")
async def pipeline_status() -> dict:
    """Return current pipeline concurrency stats for monitoring."""
    from app.pipeline_manager import pipeline_manager
    return pipeline_manager.stats()
