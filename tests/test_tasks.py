from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_session_factory(session: MagicMock) -> MagicMock:
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=session)


@pytest.mark.asyncio
async def test_build_nutrient_checkup_persists_summary_fields():
    from backend.workers.tasks import _build_nutrient_checkup

    user_row = MagicMock(user_id="user-1")
    users_result = MagicMock()
    users_result.all.return_value = [user_row]

    session = MagicMock()
    session.execute = AsyncMock(return_value=users_result)
    session.commit = AsyncMock()
    factory = _mock_session_factory(session)

    nutrients = {
        "Protein": {
            "avg": 20.0,
            "prev_avg": 20.0,
            "unit": "g",
            "trend_pct": 0.0,
            "direction": "flat",
            "rda_pct": 40.0,
        },
    }
    notable = [{"name": "Protein", "rda_pct": 40.0, "status": "under"}]
    summary_text = (
        "This week, your Protein intake is at 40% of the daily target — "
        "consider eating more lean meat, eggs, beans, or dairy."
    )

    with (
        patch("backend.workers.tasks.get_session", return_value=factory),
        patch(
            "backend.workers.tasks.get_nutrient_checkup_aggregates",
            new_callable=AsyncMock,
            return_value=nutrients,
        ),
        patch(
            "backend.workers.tasks.summarize_nutrient_checkup",
            return_value=(notable, summary_text),
        ),
    ):
        await _build_nutrient_checkup(date(2026, 6, 14))

    # Second execute call is the upsert; inspect its compiled parameters.
    upsert_call = session.execute.call_args_list[1]
    stmt = upsert_call[0][0]
    compiled = stmt.compile()
    params = compiled.params
    assert params["notable_nutrients"] == notable
    assert params["summary_text"] == summary_text
