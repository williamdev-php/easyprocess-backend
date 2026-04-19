"""
Shared fixtures for tests.

Uses an in-memory SQLite database so tests don't touch the real DB.
"""
from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.sites.models import Lead, LeadStatus

# Import all model modules to register on Base.metadata
import app.auth.models  # noqa: F401
import app.sites.models  # noqa: F401
import app.billing.models  # noqa: F401
import app.media.models  # noqa: F401


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db():
    """Provide a clean async session backed by in-memory SQLite.

    Uses schema_translate_map to map 'easyprocess' schema to None,
    so all schema-qualified queries work transparently.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        echo=False,
        execution_options={"schema_translate_map": {"easyprocess": None}},
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def lead_in_db(db: AsyncSession) -> Lead:
    """Insert a basic lead and return it."""
    lead = Lead(
        website_url="https://xnails.se/",
        business_name="X Beauty AB",
        industry="Naglar",
        source="manual",
        status=LeadStatus.NEW,
    )
    db.add(lead)
    await db.commit()
    await db.refresh(lead)
    return lead
