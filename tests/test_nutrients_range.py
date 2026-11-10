"""Tests for GET /nutrients/daily range resolution (no database needed)."""

from __future__ import annotations

from datetime import date

import pytest

from backend.nutrients.daily import resolve_range

TODAY = date(2026, 11, 10)


def test_days_counts_back_from_today_inclusive() -> None:
    assert resolve_range(None, None, 1, TODAY) == (TODAY, TODAY)
    assert resolve_range(None, None, 7, TODAY) == (date(2026, 11, 4), TODAY)
    assert resolve_range(None, None, 30, TODAY) == (date(2026, 10, 12), TODAY)


def test_explicit_range_passes_through() -> None:
    assert resolve_range(date(2026, 9, 1), date(2026, 9, 2), None, TODAY) == (
        date(2026, 9, 1),
        date(2026, 9, 2),
    )


@pytest.mark.parametrize(
    ("date_from", "date_to", "days"),
    [
        (None, None, None),
        (date(2026, 9, 1), None, None),
        (date(2026, 9, 1), date(2026, 9, 2), 7),
        (None, None, 0),
    ],
)
def test_rejects_missing_doubled_or_empty_range(
    date_from: date | None, date_to: date | None, days: int | None
) -> None:
    with pytest.raises(ValueError):
        resolve_range(date_from, date_to, days, TODAY)
