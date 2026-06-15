from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from backend.db.redis_client import current_day_bounds

_OSLO = ZoneInfo("Europe/Oslo")
_UTC = ZoneInfo("UTC")


@pytest.mark.parametrize(
    "now_local, expected_start_local",
    [
        # Just before the 01:00 reset -> still the previous nutrition day.
        ((2026, 6, 15, 0, 30), (2026, 6, 14, 1, 0)),
        # Exactly at the reset -> a new nutrition day begins.
        ((2026, 6, 15, 1, 0), (2026, 6, 15, 1, 0)),
        # After the reset -> current day.
        ((2026, 6, 15, 1, 30), (2026, 6, 15, 1, 0)),
        # Late evening -> same day that started at 01:00.
        ((2026, 6, 15, 23, 59), (2026, 6, 15, 1, 0)),
    ],
)
def test_day_starts_at_reset_hour(now_local, expected_start_local):
    now = datetime(*now_local, tzinfo=_OSLO)
    start, end = current_day_bounds(now)

    assert start.astimezone(_OSLO) == datetime(*expected_start_local, tzinfo=_OSLO)
    # The window is exactly 24h and ends at the next reset.
    assert (end - start).total_seconds() == 24 * 3600
    assert start.tzinfo == _UTC and end.tzinfo == _UTC


def test_naive_now_treated_as_utc():
    naive = datetime(2026, 6, 15, 12, 0)  # noon UTC
    start, end = current_day_bounds(naive)
    # Noon UTC on 2026-06-15 falls inside the 2026-06-15 nutrition day.
    assert start < naive.replace(tzinfo=_UTC) < end
