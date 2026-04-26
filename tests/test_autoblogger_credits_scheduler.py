"""
Tests for AutoBlogger credit system and scheduler.

Uses an in-memory SQLite database with schema_translate_map for both
'easyprocess' and 'autoblogger' schemas.
"""
from __future__ import annotations

import uuid
from datetime import datetime, time as dt_time, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.autoblogger.models import (
    AutoBloggerBase,
    CreditBalance,
    CreditTransaction,
    TaskFrequency,
)
from app.autoblogger.credits import (
    FREE_TIER_CREDITS,
    calculate_credits_for_post,
    deduct_credits,
    get_or_create_credit_balance,
    validate_credits,
)
from app.autoblogger.scheduler import calculate_next_run_at

# Import model modules so Base.metadata is fully populated
import app.auth.models  # noqa: F401
import app.sites.models  # noqa: F401
import app.billing.models  # noqa: F401
import app.media.models  # noqa: F401
import app.tracking.models  # noqa: F401


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db():
    """Async session backed by in-memory SQLite with both schemas mapped."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        echo=False,
        execution_options={
            "schema_translate_map": {
                "easyprocess": None,
                "autoblogger": None,
            }
        },
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(AutoBloggerBase.metadata.create_all)

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False,
    )

    async with session_factory() as session:
        yield session

    await engine.dispose()


# ===========================================================================
# Scheduler tests (pure functions, no DB)
# ===========================================================================


class TestCalculateNextRunAt:
    """Tests for calculate_next_run_at with various frequencies."""

    def test_daily_returns_next_day_at_preferred_time(self):
        # "now" is 2026-04-25 15:00 UTC; preferred time already passed today
        now = datetime(2026, 4, 25, 15, 0, tzinfo=timezone.utc)
        result = calculate_next_run_at(
            frequency=TaskFrequency.DAILY,
            preferred_time="09:00",
            timezone_str="UTC",
            days_of_week=None,
            last_run_at=None,
            now=now,
        )
        # Should be next day 09:00 UTC
        assert result.date() == datetime(2026, 4, 26).date()
        assert result.hour == 9
        assert result.minute == 0

    def test_daily_today_if_time_not_passed(self):
        # "now" is 2026-04-25 07:00 UTC; preferred 09:00 hasn't passed
        now = datetime(2026, 4, 25, 7, 0, tzinfo=timezone.utc)
        result = calculate_next_run_at(
            frequency=TaskFrequency.DAILY,
            preferred_time="09:00",
            timezone_str="UTC",
            days_of_week=None,
            last_run_at=None,
            now=now,
        )
        assert result.date() == datetime(2026, 4, 25).date()
        assert result.hour == 9

    def test_weekly_specific_days(self):
        # 2026-04-25 is a Saturday. Ask for monday and friday.
        now = datetime(2026, 4, 25, 15, 0, tzinfo=timezone.utc)
        result = calculate_next_run_at(
            frequency=TaskFrequency.WEEKLY,
            preferred_time="10:00",
            timezone_str="UTC",
            days_of_week=["monday", "friday"],
            last_run_at=None,
            now=now,
        )
        # Next valid day after Saturday -> Monday 2026-04-27
        assert result.weekday() == 0  # Monday
        assert result.date() == datetime(2026, 4, 27).date()
        assert result.hour == 10

    def test_weekly_today_if_valid_and_not_passed(self):
        # 2026-04-27 is a Monday, ask for monday, time hasn't passed
        now = datetime(2026, 4, 27, 7, 0, tzinfo=timezone.utc)
        result = calculate_next_run_at(
            frequency=TaskFrequency.WEEKLY,
            preferred_time="10:00",
            timezone_str="UTC",
            days_of_week=["monday"],
            last_run_at=None,
            now=now,
        )
        assert result.date() == datetime(2026, 4, 27).date()
        assert result.hour == 10

    def test_biweekly_14_days_from_last_run(self):
        now = datetime(2026, 4, 25, 12, 0, tzinfo=timezone.utc)
        last_run = datetime(2026, 4, 20, 9, 0, tzinfo=timezone.utc)
        result = calculate_next_run_at(
            frequency=TaskFrequency.BIWEEKLY,
            preferred_time="09:00",
            timezone_str="UTC",
            days_of_week=None,
            last_run_at=last_run,
            now=now,
        )
        # 14 days after 2026-04-20 = 2026-05-04
        assert result.date() == datetime(2026, 5, 4).date()
        assert result.hour == 9

    def test_monthly_same_day_next_month(self):
        now = datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc)
        result = calculate_next_run_at(
            frequency=TaskFrequency.MONTHLY,
            preferred_time="08:00",
            timezone_str="UTC",
            days_of_week=None,
            last_run_at=None,
            now=now,
        )
        assert result.month == 5
        assert result.day == 15
        assert result.hour == 8

    def test_monthly_jan31_clamps_to_feb28(self):
        # 2026 is not a leap year
        now = datetime(2026, 1, 31, 12, 0, tzinfo=timezone.utc)
        result = calculate_next_run_at(
            frequency=TaskFrequency.MONTHLY,
            preferred_time="09:00",
            timezone_str="UTC",
            days_of_week=None,
            last_run_at=None,
            now=now,
        )
        assert result.month == 2
        assert result.day == 28
        assert result.hour == 9


# ===========================================================================
# Credit tests (need DB)
# ===========================================================================


class TestCreditSystem:
    """Tests for the credit validation, deduction, and cost calculation."""

    @pytest.mark.asyncio
    async def test_validate_credits_sufficient(self, db: AsyncSession):
        user_id = str(uuid.uuid4())
        # Pre-create a balance with 10 credits
        balance = CreditBalance(
            id=str(uuid.uuid4()),
            user_id=user_id,
            credits_remaining=10,
            credits_used_total=0,
            plan_credits_monthly=10,
        )
        db.add(balance)
        await db.flush()

        result = await validate_credits(db, user_id, required=5)
        assert result.credits_remaining == 10

    @pytest.mark.asyncio
    async def test_validate_credits_insufficient_raises_402(self, db: AsyncSession):
        user_id = str(uuid.uuid4())
        balance = CreditBalance(
            id=str(uuid.uuid4()),
            user_id=user_id,
            credits_remaining=1,
            credits_used_total=4,
            plan_credits_monthly=5,
        )
        db.add(balance)
        await db.flush()

        with pytest.raises(HTTPException) as exc_info:
            await validate_credits(db, user_id, required=5)
        assert exc_info.value.status_code == 402

    @pytest.mark.asyncio
    async def test_deduct_credits_decrements_and_logs(self, db: AsyncSession):
        user_id = str(uuid.uuid4())
        balance = CreditBalance(
            id=str(uuid.uuid4()),
            user_id=user_id,
            credits_remaining=10,
            credits_used_total=0,
            plan_credits_monthly=10,
        )
        db.add(balance)
        await db.flush()

        updated = await deduct_credits(
            db, user_id, amount=1, description="Standard post"
        )
        assert updated.credits_remaining == 9
        assert updated.credits_used_total == 1

        # Verify transaction was created
        result = await db.execute(
            select(CreditTransaction).where(
                CreditTransaction.user_id == user_id,
            )
        )
        txn = result.scalar_one()
        assert txn.amount == -1
        assert txn.balance_after == 9
        assert txn.description == "Standard post"

    @pytest.mark.asyncio
    async def test_deduct_credits_long_form_post(self, db: AsyncSession):
        user_id = str(uuid.uuid4())
        balance = CreditBalance(
            id=str(uuid.uuid4()),
            user_id=user_id,
            credits_remaining=10,
            credits_used_total=0,
            plan_credits_monthly=10,
        )
        db.add(balance)
        await db.flush()

        cost = calculate_credits_for_post(word_count=3000)
        assert cost == 2

        updated = await deduct_credits(
            db, user_id, amount=cost, description="Long-form post"
        )
        assert updated.credits_remaining == 8
        assert updated.credits_used_total == 2

    @pytest.mark.asyncio
    async def test_deduct_credits_to_zero(self, db: AsyncSession):
        user_id = str(uuid.uuid4())
        balance = CreditBalance(
            id=str(uuid.uuid4()),
            user_id=user_id,
            credits_remaining=1,
            credits_used_total=4,
            plan_credits_monthly=5,
        )
        db.add(balance)
        await db.flush()

        updated = await deduct_credits(
            db, user_id, amount=1, description="Last credit"
        )
        assert updated.credits_remaining == 0
        assert updated.credits_used_total == 5

        # Now validate should fail
        with pytest.raises(HTTPException) as exc_info:
            await validate_credits(db, user_id, required=1)
        assert exc_info.value.status_code == 402

    @pytest.mark.asyncio
    async def test_get_or_create_gives_free_tier(self, db: AsyncSession):
        user_id = str(uuid.uuid4())
        balance = await get_or_create_credit_balance(db, user_id)
        assert balance.credits_remaining == FREE_TIER_CREDITS
        assert balance.plan_credits_monthly == FREE_TIER_CREDITS

    def test_calculate_credits_standard_post(self):
        assert calculate_credits_for_post(500) == 1
        assert calculate_credits_for_post(2000) == 1

    def test_calculate_credits_long_form_post(self):
        assert calculate_credits_for_post(2001) == 2
        assert calculate_credits_for_post(5000) == 2
