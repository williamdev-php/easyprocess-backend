"""AutoBlogger credit system — service functions for managing generation credits.

Pure service module: no router/endpoint logic. All async functions flush
but do NOT commit; the caller's session manages transaction boundaries.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.autoblogger.models import (
    AutoBloggerSubscription,
    CreditBalance,
    CreditTransaction,
)

FREE_TIER_CREDITS = 5
LONG_FORM_WORD_COUNT = 2000

# Plan credit allocations (canonical source — billing.py imports from here)
PLAN_CREDITS = {
    "pro": 50,
    "business": 9999,
}


# ---------------------------------------------------------------------------
# 1. Get or create
# ---------------------------------------------------------------------------

async def get_or_create_credit_balance(
    db: AsyncSession, user_id: str
) -> CreditBalance:
    """Return the user's CreditBalance, creating one with free-tier defaults
    if it doesn't exist yet."""
    result = await db.execute(
        select(CreditBalance).where(CreditBalance.user_id == user_id)
    )
    balance = result.scalar_one_or_none()

    if balance is None:
        balance = CreditBalance(
            id=str(uuid.uuid4()),
            user_id=user_id,
            credits_remaining=FREE_TIER_CREDITS,
            credits_used_total=0,
            plan_credits_monthly=FREE_TIER_CREDITS,
        )
        db.add(balance)
        await db.flush()

    return balance


# ---------------------------------------------------------------------------
# 2. Validate
# ---------------------------------------------------------------------------

async def validate_credits(
    db: AsyncSession, user_id: str, required: int = 1
) -> CreditBalance:
    """Validate user has sufficient credits. Returns the balance.

    Uses SELECT FOR UPDATE to prevent concurrent overdraw.
    Raises ``HTTPException(402)`` if insufficient.
    """
    result = await db.execute(
        select(CreditBalance)
        .where(CreditBalance.user_id == user_id)
        .with_for_update()
    )
    balance = result.scalar_one_or_none()

    if balance is None:
        # Create with lock — use get_or_create then re-lock
        balance = await get_or_create_credit_balance(db, user_id)
        # Re-fetch with lock
        result = await db.execute(
            select(CreditBalance)
            .where(CreditBalance.user_id == user_id)
            .with_for_update()
        )
        balance = result.scalar_one()

    if balance.credits_remaining < required:
        raise HTTPException(
            status_code=402,
            detail=(
                f"Insufficient credits: {balance.credits_remaining} remaining, "
                f"{required} required. Please upgrade your plan or wait for "
                "your monthly reset."
            ),
        )

    return balance


# ---------------------------------------------------------------------------
# 3. Deduct
# ---------------------------------------------------------------------------

async def deduct_credits(
    db: AsyncSession,
    user_id: str,
    amount: int,
    description: str,
    post_id: str | None = None,
) -> CreditBalance:
    """Deduct credits and create a transaction log entry.

    Uses SELECT FOR UPDATE for atomic deduction.
    Does **not** validate — caller must call :func:`validate_credits` first.
    """
    result = await db.execute(
        select(CreditBalance)
        .where(CreditBalance.user_id == user_id)
        .with_for_update()
    )
    balance = result.scalar_one_or_none()

    if balance is None:
        balance = await get_or_create_credit_balance(db, user_id)

    balance.credits_remaining -= amount
    balance.credits_used_total += amount

    transaction = CreditTransaction(
        id=str(uuid.uuid4()),
        user_id=user_id,
        amount=-amount,
        balance_after=balance.credits_remaining,
        description=description,
        post_id=post_id,
    )
    db.add(transaction)
    await db.flush()

    return balance


# ---------------------------------------------------------------------------
# 4. Calculate cost
# ---------------------------------------------------------------------------

def calculate_credits_for_post(word_count: int) -> int:
    """1 credit for standard posts, 2 for long-form (>LONG_FORM_WORD_COUNT words)."""
    return 2 if word_count > LONG_FORM_WORD_COUNT else 1


# ---------------------------------------------------------------------------
# 5. Monthly reset (background task)
# ---------------------------------------------------------------------------

async def reset_monthly_credits(db: AsyncSession) -> int:
    """Reset credits for all users whose ``last_reset_at`` is NULL or >30 days ago.

    Processes in batches of 500 to avoid memory issues at scale.
    Returns the count of users reset.
    """
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    reset_count = 0
    batch_size = 500
    offset = 0

    while True:
        result = await db.execute(
            select(CreditBalance).where(
                (CreditBalance.last_reset_at.is_(None))
                | (CreditBalance.last_reset_at <= thirty_days_ago)
            ).limit(batch_size).offset(offset)
        )
        balances: list[CreditBalance] = list(result.scalars().all())

        if not balances:
            break

        for balance in balances:
            # Determine plan allocation from active subscription
            sub_result = await db.execute(
                select(AutoBloggerSubscription).where(
                    AutoBloggerSubscription.user_id == balance.user_id,
                    AutoBloggerSubscription.status.in_(("active", "trialing")),
                )
            )
            subscription = sub_result.scalar_one_or_none()

            if subscription and subscription.plan in PLAN_CREDITS:
                monthly_credits = PLAN_CREDITS[subscription.plan]
            else:
                monthly_credits = FREE_TIER_CREDITS

            balance.plan_credits_monthly = monthly_credits
            balance.credits_remaining = monthly_credits
            balance.last_reset_at = datetime.now(timezone.utc)

            transaction = CreditTransaction(
                id=str(uuid.uuid4()),
                user_id=balance.user_id,
                amount=monthly_credits,
                balance_after=monthly_credits,
                description=f"Monthly credit reset ({monthly_credits} credits)",
            )
            db.add(transaction)
            reset_count += 1

        await db.flush()
        logger.info("Monthly credit reset: processed batch of %d (total: %d)", len(balances), reset_count)

        if len(balances) < batch_size:
            break
        offset += batch_size

    return reset_count


# ---------------------------------------------------------------------------
# 6. Single-user reset (webhook use)
# ---------------------------------------------------------------------------

async def reset_credits_for_user(
    db: AsyncSession, user_id: str, plan: str
) -> None:
    """Reset credits when a subscription payment succeeds.

    Sets ``credits_remaining`` to the plan allocation and logs a transaction.
    """
    balance = await get_or_create_credit_balance(db, user_id)

    monthly_credits = PLAN_CREDITS.get(plan, FREE_TIER_CREDITS)

    balance.plan_credits_monthly = monthly_credits
    balance.credits_remaining = monthly_credits
    balance.last_reset_at = datetime.now(timezone.utc)

    transaction = CreditTransaction(
        id=str(uuid.uuid4()),
        user_id=user_id,
        amount=monthly_credits,
        balance_after=monthly_credits,
        description=f"Credits reset — {plan} plan ({monthly_credits} credits)",
    )
    db.add(transaction)
    await db.flush()
