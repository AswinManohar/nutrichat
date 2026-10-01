"""Single source of truth for the nutrition day.

A nutrition day runs from ``day.reset_hour`` to ``day.reset_hour`` in the
configured ``day.timezone`` (tunables). Anything logged before the reset hour
belongs to the previous calendar date. Python code should use
``nutrition_today`` / ``day_bounds``; SQL that buckets rows by day should use
``nutrition_date_sql`` plus ``sql_day_params`` instead of ``logged_at::date``.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from backend.config import get_tunables

_TUNABLES = get_tunables()
_DAY_TZ = ZoneInfo(_TUNABLES.day.timezone)
_DAY_RESET_HOUR = _TUNABLES.day.reset_hour
_UTC = ZoneInfo("UTC")


def nutrition_today(now: datetime | None = None) -> date:
    """Return the nutrition date that owns ``now``.

    Args:
        now: Instant to evaluate. Defaults to the current time. A naive
            datetime is assumed to be UTC.

    Returns:
        The calendar date (in the configured timezone) of the active
        nutrition day.
    """
    if now is None:
        now = datetime.now(_DAY_TZ)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=_UTC)
    now_local = now.astimezone(_DAY_TZ)
    return (now_local - timedelta(hours=_DAY_RESET_HOUR)).date()


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """Return the nutrition-day ``[start, end)`` UTC window for ``day``."""
    start_local = datetime.combine(day, time(hour=_DAY_RESET_HOUR), tzinfo=_DAY_TZ)
    end_local = datetime.combine(
        day + timedelta(days=1), time(hour=_DAY_RESET_HOUR), tzinfo=_DAY_TZ
    )
    return start_local.astimezone(_UTC), end_local.astimezone(_UTC)


def current_day_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Return the ``[start, end)`` UTC bounds of the nutrition day owning ``now``."""
    return day_bounds(nutrition_today(now))


def nutrition_date_sql(column: str = "logged_at") -> str:
    """Return a SQL expression bucketing a timestamptz column by nutrition date.

    ``AT TIME ZONE`` on a timestamptz yields the local wall-clock timestamp;
    subtracting the reset hours before casting to date puts pre-reset rows on
    the previous day. Requires the binds from ``sql_day_params``.
    """
    return (
        f"(({column} AT TIME ZONE CAST(:day_tz AS text)) "
        "- make_interval(hours => CAST(:day_reset_h AS int)))::date"
    )


NUTRITION_DATE_SQL = nutrition_date_sql()


def sql_day_params() -> dict[str, str | int]:
    """Bind params required by ``NUTRITION_DATE_SQL``."""
    return {"day_tz": _TUNABLES.day.timezone, "day_reset_h": _DAY_RESET_HOUR}
