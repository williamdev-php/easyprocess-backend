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
from app.sites.models import Lead, ScrapedData, GeneratedSite, OutreachEmail, InboundEmail, PageView, CustomDomain  # noqa: F401


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Create schema and tables on startup (dev convenience; use Alembic in production)
    async with engine.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
        await conn.run_sync(Base.metadata.create_all)

    # Verify Supabase Storage connectivity
    if settings.SUPABASE_URL:
        from app.storage.supabase import check_storage_health
        if check_storage_health():
            logger.info("Supabase Storage bucket '%s' is accessible", settings.SUPABASE_STORAGE_BUCKET)
        else:
            logger.warning("Supabase Storage bucket '%s' is NOT accessible — image storage will fail", settings.SUPABASE_STORAGE_BUCKET)

    yield
    await cache.close()
    await engine.dispose()


app = FastAPI(
    title="Qvicko API",
    description="Backend for the Qvicko platform",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
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

app.include_router(auth_router)
app.include_router(sites_router)
app.include_router(webhook_router)

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
