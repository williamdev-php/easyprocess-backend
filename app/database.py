import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger(__name__)

SCHEMA = "easyprocess"

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
