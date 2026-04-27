import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger(__name__)

SCHEMA = "easyprocess"

_ENGINE_KWARGS = dict(
    echo=False,
    # Pool sizing
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,  # seconds to wait for a connection from the pool
    # Connection health
    pool_pre_ping=True,  # test connections before checkout
    pool_recycle=3600,  # recycle connections every hour to avoid stale connections
    # asyncpg-specific timeouts
    connect_args={
        "timeout": 10,  # connection timeout (seconds)
        "command_timeout": 30,  # per-statement timeout (seconds)
        "server_settings": {
            "statement_timeout": "30000",  # PostgreSQL server-side timeout (ms)
        },
    },
)

engine = create_async_engine(settings.effective_database_url, **_ENGINE_KWARGS)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# ---------------------------------------------------------------------------
# Optional read-replica engine
# ---------------------------------------------------------------------------
# Set DATABASE_READ_REPLICA_URL to route read-heavy queries to a replica.
# When the env var is not set, read sessions fall back to the primary engine.

_replica_url = settings.DATABASE_READ_REPLICA_URL
if _replica_url:
    read_replica_engine = create_async_engine(
        _replica_url,
        **{**_ENGINE_KWARGS, "pool_size": 5, "max_overflow": 10},
    )
    logger.info("Read-replica engine configured")
else:
    read_replica_engine = None

_read_session_factory = async_sessionmaker(
    read_replica_engine or engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager that provides a database session.

    Relies on pool_pre_ping to discard stale connections at checkout time.
    """
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def get_read_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager for read-only queries.

    Uses the read-replica engine when configured (DATABASE_READ_REPLICA_URL),
    otherwise falls back to the primary engine.  The session is never committed
    since it is intended for SELECT-only workloads.
    """
    async with _read_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that provides a database session with retry-aware setup.

    Note: FastAPI dependencies using yield cannot directly retry, so this relies
    on the engine-level pool_pre_ping and timeouts for resilience.
    """
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
