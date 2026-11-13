"""Builders for hard-profile entries used across the test suite."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta

from backend.safety import profile
from backend.safety.profile import HardEntry

_BASE = datetime(2026, 11, 1, tzinfo=UTC)
_counter = itertools.count()


def hard_entry(
    value: profile.EntryValue,
    state: str = "confirmed",
    *,
    entry_id: str | None = None,
    source: str = "patient",
) -> HardEntry:
    """A hard entry with sequential timestamps, for tests that bypass the DB."""
    n = next(_counter)
    at = _BASE + timedelta(seconds=n)
    return HardEntry(
        id=entry_id or f"entry-{n}",
        type=profile._TYPE_OF[type(value)],
        value=value,
        source=source,
        state=state,
        created_at=at,
        created_by="patient",
        confirmed_at=at if state == "confirmed" else None,
    )
