import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import MetaData
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger(__name__)

SCHEMA = "easyprocess"

# Transient error indicators that warrant a retry
_TRANSIENT_MESSAGES = (
    "connection was closed",
    "connection was terminated",
    "connection reset",
    "server closed the connection",
    "connection refused",
    "ConnectionDoesNotExistError",
    "InterfaceError",
    "connection is closed",
    "SSL connection has been closed",
    "Operation timed out",
    "could not connect to server",
)

engine = create_async_engine(
    settings.effective_database_url,
    echo=False,
    # Pool sizing
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,  # seconds to wait for a connection from the pool
    # Connection health
    pool_pre_ping=True,  # test connections before checkout
    pool_recycle=300,  # recycle connections every 5 minutes
    # asyncpg-specific timeouts
    connect_args={
        "timeout": 10,  # connection timeout (seconds)
        "command_timeout": 30,  # per-statement timeout (seconds)
        "server_settings": {
            "statement_timeout": "30000",  # PostgreSQL server-side timeout (ms)
        },
    },
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


def _is_transient_error(exc: Exception) -> bool:
    """Check if an exception is a transient database error worth retrying."""
    msg = str(exc).lower()
    return any(indicator.lower() in msg for indicator in _TRANSIENT_MESSAGES)


@asynccontextmanager
async def get_db_session(max_retries: int = 3) -> AsyncGenerator[AsyncSession, None]:
    """Async context manager that provides a database session with retry logic.

    Retries on transient connection errors (dropped connections, timeouts).
    Each retry creates a fresh session/connection.
    """
    last_exc: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            async with async_session() as session:
                try:
                    yield session
                    await session.commit()
                    return  # success
                except Exception:
                    await session.rollback()
                    raise
        except (OperationalError, DBAPIError, OSError, asyncio.TimeoutError) as exc:
            if not _is_transient_error(exc) and not isinstance(exc, asyncio.TimeoutError):
                raise  # not transient, don't retry
            last_exc = exc
            if attempt < max_retries:
                wait = min(0.5 * (2 ** (attempt - 1)), 4)  # 0.5s, 1s, 2s...
                logger.warning(
                    "Transient DB error (attempt %d/%d), retrying in %.1fs: %s",
                    attempt,
                    max_retries,
                    wait,
                    str(exc)[:200],
                )
                await asyncio.sleep(wait)
            else:
                logger.error(
                    "DB operation failed after %d attempts: %s",
                    max_retries,
                    str(exc)[:200],
                )
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
