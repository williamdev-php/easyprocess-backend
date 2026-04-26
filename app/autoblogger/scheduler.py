"""Schedule execution time calculator.

Pure utility module — no database operations, no async.
Calculates next run times for content schedules based on frequency,
preferred time, timezone, and day-of-week constraints.
"""

import calendar
from datetime import datetime, time as dt_time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.autoblogger.models import TaskFrequency

# Day name (lowercase) → weekday index (Monday=0 … Sunday=6)
_DAY_NAME_TO_INDEX: dict[str, int] = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

_DEFAULT_TIME = "09:00"
_DEFAULT_DAYS_OF_WEEK = ["monday"]


def _parse_preferred_time(preferred_time: str | None) -> dt_time:
    """Parse an "HH:MM" string into a time object, falling back to 09:00."""
    if not preferred_time:
        preferred_time = _DEFAULT_TIME
    try:
        hour, minute = preferred_time.split(":")
        return dt_time(int(hour), int(minute))
    except (ValueError, AttributeError):
        return dt_time(9, 0)


def _local_to_utc(local_dt: datetime, tz: ZoneInfo) -> datetime:
    """Convert a naive-or-local datetime in *tz* to a UTC-aware datetime."""
    if local_dt.tzinfo is None:
        local_dt = local_dt.replace(tzinfo=tz)
    return local_dt.astimezone(timezone.utc)


def _clamp_day(year: int, month: int, day: int) -> int:
    """Clamp *day* to the maximum number of days in *month*."""
    max_day = calendar.monthrange(year, month)[1]
    return min(day, max_day)


def calculate_next_run_at(
    frequency: TaskFrequency,
    preferred_time: str | None,
    timezone_str: str,
    days_of_week: list[str] | None,
    last_run_at: datetime | None,
    now: datetime | None = None,
) -> datetime:
    """Calculate the next run time in UTC.

    Parameters
    ----------
    frequency:
        How often the schedule should run.
    preferred_time:
        "HH:MM" in the user's timezone, or *None* (defaults to "09:00").
    timezone_str:
        IANA timezone string, e.g. "Europe/Stockholm".
    days_of_week:
        Lowercase day names for WEEKLY frequency, e.g. ["monday", "friday"].
    last_run_at:
        UTC datetime of the last execution, or *None* if never run.
    now:
        Override "now" for testing. Defaults to ``datetime.now(timezone.utc)``.

    Returns
    -------
    datetime
        Next execution time as a UTC-aware datetime.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    tz = ZoneInfo(timezone_str)
    local_now = now.astimezone(tz)
    ptime = _parse_preferred_time(preferred_time)

    if frequency == TaskFrequency.DAILY:
        return _next_daily(local_now, ptime, last_run_at, tz)

    if frequency == TaskFrequency.WEEKLY:
        return _next_weekly(local_now, ptime, days_of_week, last_run_at, tz)

    if frequency == TaskFrequency.BIWEEKLY:
        return _next_biweekly(local_now, ptime, last_run_at, tz)

    # MONTHLY
    return _next_monthly(local_now, ptime, tz)


# ── Frequency helpers ────────────────────────────────────────────────────────


def _next_daily(
    local_now: datetime,
    ptime: dt_time,
    last_run_at: datetime | None,
    tz: ZoneInfo,
) -> datetime:
    today_at_ptime = local_now.replace(
        hour=ptime.hour, minute=ptime.minute, second=0, microsecond=0,
    )

    # If today's preferred time hasn't passed yet and we haven't already run
    # today, use today.
    already_ran_today = False
    if last_run_at is not None:
        last_local = last_run_at.astimezone(tz) if last_run_at.tzinfo else last_run_at.replace(tzinfo=timezone.utc).astimezone(tz)
        already_ran_today = last_local.date() == local_now.date()

    if local_now < today_at_ptime and not already_ran_today:
        return _local_to_utc(today_at_ptime, tz)

    # Otherwise, next day at preferred time.
    next_day = today_at_ptime + timedelta(days=1)
    return _local_to_utc(next_day, tz)


def _next_weekly(
    local_now: datetime,
    ptime: dt_time,
    days_of_week: list[str] | None,
    last_run_at: datetime | None,
    tz: ZoneInfo,
) -> datetime:
    if not days_of_week:
        days_of_week = _DEFAULT_DAYS_OF_WEEK

    target_indices = sorted(
        {_DAY_NAME_TO_INDEX[d.lower()] for d in days_of_week if d.lower() in _DAY_NAME_TO_INDEX}
    )
    if not target_indices:
        target_indices = [0]  # fallback to Monday

    current_weekday = local_now.weekday()
    today_at_ptime = local_now.replace(
        hour=ptime.hour, minute=ptime.minute, second=0, microsecond=0,
    )

    already_ran_today = False
    if last_run_at is not None:
        last_local = last_run_at.astimezone(tz) if last_run_at.tzinfo else last_run_at.replace(tzinfo=timezone.utc).astimezone(tz)
        already_ran_today = last_local.date() == local_now.date()

    # Check if today is a valid day and the time hasn't passed yet.
    if (
        current_weekday in target_indices
        and local_now < today_at_ptime
        and not already_ran_today
    ):
        return _local_to_utc(today_at_ptime, tz)

    # Find the next valid day of week.
    for offset in range(1, 8):
        candidate_weekday = (current_weekday + offset) % 7
        if candidate_weekday in target_indices:
            candidate = today_at_ptime + timedelta(days=offset)
            return _local_to_utc(candidate, tz)

    # Should never reach here, but safeguard: next week same day.
    return _local_to_utc(today_at_ptime + timedelta(weeks=1), tz)


def _next_biweekly(
    local_now: datetime,
    ptime: dt_time,
    last_run_at: datetime | None,
    tz: ZoneInfo,
) -> datetime:
    base_local: datetime
    if last_run_at is not None:
        if last_run_at.tzinfo is None:
            last_run_at = last_run_at.replace(tzinfo=timezone.utc)
        base_local = last_run_at.astimezone(tz)
    else:
        base_local = local_now

    candidate = base_local.replace(
        hour=ptime.hour, minute=ptime.minute, second=0, microsecond=0,
    ) + timedelta(days=14)

    # If the candidate is in the past (e.g. schedule was inactive), advance
    # in 14-day increments until it's in the future.
    while candidate <= local_now:
        candidate += timedelta(days=14)

    return _local_to_utc(candidate, tz)


def _next_monthly(
    local_now: datetime,
    ptime: dt_time,
    tz: ZoneInfo,
) -> datetime:
    current_day = local_now.day
    current_year = local_now.year
    current_month = local_now.month

    # Try same day next month.
    if current_month == 12:
        next_year, next_month = current_year + 1, 1
    else:
        next_year, next_month = current_year, current_month + 1

    clamped_day = _clamp_day(next_year, next_month, current_day)

    candidate = local_now.replace(
        year=next_year,
        month=next_month,
        day=clamped_day,
        hour=ptime.hour,
        minute=ptime.minute,
        second=0,
        microsecond=0,
    )

    return _local_to_utc(candidate, tz)


# ── Public convenience helper ────────────────────────────────────────────────


def calculate_initial_next_run_at(
    frequency: TaskFrequency,
    preferred_time: str | None,
    timezone_str: str,
    days_of_week: list[str] | None,
) -> datetime:
    """Calculate the first ``next_run_at`` when a schedule is created."""
    return calculate_next_run_at(
        frequency=frequency,
        preferred_time=preferred_time,
        timezone_str=timezone_str,
        days_of_week=days_of_week,
        last_run_at=None,
    )
