import asyncio
import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from slowapi.middleware import SlowAPIMiddleware

from sqlalchemy import text

from app.cache import cache
from app.config import settings
from app.rate_limit import limiter
from app.database import engine, Base, SCHEMA

# Import all models so Base.metadata knows about them
from app.auth.models import User, Session, AuditLog, SocialAccount, SettingsAuditLog  # noqa: F401
from app.sites.models import Lead, ScrapedData, GeneratedSite, SiteVersion, OutreachEmail, InboundEmail, PageView, CustomDomain, DomainPurchase  # noqa: F401
from app.billing.models import Subscription, Payment, BillingDetails  # noqa: F401
from app.media.models import MediaFile  # noqa: F401
from app.smartlead.models import SmartleadCampaign, SmartleadEmailAccount  # noqa: F401


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

    # Verify Supabase Storage connectivity
    if settings.SUPABASE_URL:
        from app.storage.supabase import check_storage_health
        if check_storage_health():
            logger.info("Supabase Storage bucket '%s' is accessible", settings.SUPABASE_STORAGE_BUCKET)
        else:
            logger.warning("Supabase Storage bucket '%s' is NOT accessible — image storage will fail", settings.SUPABASE_STORAGE_BUCKET)

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

    smartlead_task = asyncio.create_task(_smartlead_sync_loop())

    yield

    # Graceful shutdown: cancel background tasks and let in-flight work drain.
    expiration_task.cancel()
    smartlead_task.cancel()
    for task in (expiration_task, smartlead_task):
        try:
            await task
        except asyncio.CancelledError:
            pass
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
app.add_middleware(SlowAPIMiddleware)

# REST routes
from app.auth.router import router as auth_router  # noqa: E402
from app.sites.router import router as sites_router  # noqa: E402
from app.sites.router import webhook_router  # noqa: E402
from app.billing.router import router as billing_router  # noqa: E402
from app.billing.router import webhook_router as stripe_webhook_router  # noqa: E402
from app.media.router import router as media_router  # noqa: E402

app.include_router(auth_router)
app.include_router(sites_router)
app.include_router(webhook_router)
app.include_router(billing_router)
app.include_router(stripe_webhook_router)
app.include_router(media_router)

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
