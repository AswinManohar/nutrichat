from __future__ import annotations

from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agent.tools.history import (
    get_food_breakdown_for_range,
    get_history,
    get_macros_for_range,
    get_micronutrients_for_range,
)
from backend.db.models import MealLog


def _mock_session_factory(session: MagicMock) -> MagicMock:
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=session)


@pytest.mark.asyncio
async def test_get_macros_for_range_sums_columns():
    row = MagicMock(
        kcal=1240.0, protein_g=85.0, carbs_g=120.0, fat_g=40.0, fiber_g=22.0, n_meals=3
    )
    session = MagicMock()
    exec_result = MagicMock()
    exec_result.one.return_value = row
    session.execute = AsyncMock(return_value=exec_result)
    factory = _mock_session_factory(session)

    with patch("backend.agent.tools.history.get_session", return_value=factory):
        totals = await get_macros_for_range(
            "user-1", date(2026, 6, 1), date(2026, 6, 7)
        )

    assert totals == {
        "kcal": 1240.0,
        "protein_g": 85.0,
        "carbs_g": 120.0,
        "fat_g": 40.0,
        "fiber_g": 22.0,
        "n_meals": 3,
    }


@pytest.mark.asyncio
async def test_get_macros_for_range_empty_returns_zeros():
    row = MagicMock(kcal=0, protein_g=0, carbs_g=0, fat_g=0, fiber_g=0, n_meals=0)
    session = MagicMock()
    exec_result = MagicMock()
    exec_result.one.return_value = row
    session.execute = AsyncMock(return_value=exec_result)
    factory = _mock_session_factory(session)

    with patch("backend.agent.tools.history.get_session", return_value=factory):
        totals = await get_macros_for_range(
            "user-1", date(2026, 6, 1), date(2026, 6, 7)
        )

    assert totals["kcal"] == 0.0
    assert totals["n_meals"] == 0


@pytest.mark.asyncio
async def test_get_micronutrients_for_range_returns_amount_and_unit():
    row = MagicMock(total=2.1, unit="mcg")
    session = MagicMock()
    exec_result = MagicMock()
    exec_result.one.return_value = row
    session.execute = AsyncMock(return_value=exec_result)
    factory = _mock_session_factory(session)

    with patch("backend.agent.tools.history.get_session", return_value=factory):
        result = await get_micronutrients_for_range(
            "user-1", date(2026, 6, 11), date(2026, 6, 11), ["Vitamin B-12"]
        )

    assert result == {"Vitamin B-12": {"amount": 2.1, "unit": "mcg"}}


@pytest.mark.asyncio
async def test_get_micronutrients_for_range_omits_missing_nutrients():
    row = MagicMock(total=None, unit=None)
    session = MagicMock()
    exec_result = MagicMock()
    exec_result.one.return_value = row
    session.execute = AsyncMock(return_value=exec_result)
    factory = _mock_session_factory(session)

    with patch("backend.agent.tools.history.get_session", return_value=factory):
        result = await get_micronutrients_for_range(
            "user-1", date(2026, 6, 11), date(2026, 6, 11), ["Vitamin B-12"]
        )

    assert result == {}


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_get_food_breakdown_for_range_returns_expected_shape():
    freq_rows = [
        MagicMock(food_name="Chicken breast, grilled", count=9, total_kcal=2250.0),
        MagicMock(food_name="Whey protein shake", count=7, total_kcal=1400.0),
    ]
    junk_rows = [
        MagicMock(food_name="Cheeseburger", count=5),
        MagicMock(food_name="French fries", count=4),
    ]
    high_kcal_rows = [
        MagicMock(food_name="Cheeseburger", kcal=550.0),
        MagicMock(food_name="French fries", kcal=300.0),
    ]

    freq_result = MagicMock()
    freq_result.__iter__.return_value = iter(freq_rows)
    junk_result = MagicMock()
    junk_result.__iter__.return_value = iter(junk_rows)
    high_kcal_result = MagicMock()
    high_kcal_result.__iter__.return_value = iter(high_kcal_rows)

    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=[freq_result, junk_result, high_kcal_result]
    )
    factory = _mock_session_factory(session)

    with patch("backend.agent.tools.history.get_session", return_value=factory):
        result = await get_food_breakdown_for_range(
            "user-1", date(2026, 5, 13), date(2026, 6, 11)
        )

    assert result["top_foods_by_frequency"] == [
        {"food_name": "Chicken breast, grilled", "count": 9, "total_kcal": 2250.0},
        {"food_name": "Whey protein shake", "count": 7, "total_kcal": 1400.0},
    ]
    assert result["flagged_junk_foods"] == [
        {"food_name": "Cheeseburger", "count": 5},
        {"food_name": "French fries", "count": 4},
    ]
    assert result["highest_calorie_foods"] == [
        {"food_name": "Cheeseburger", "kcal": 550.0},
        {"food_name": "French fries", "kcal": 300.0},
    ]
    assert session.execute.await_count == 3
    # All three queries are parameterized and date-range filtered.
    for call in session.execute.call_args_list:
        stmt = str(call[0][0])
        assert "logged_at::date BETWEEN :date_from AND :date_to" in stmt
        assert "deleted_at IS NULL" in stmt


@pytest.mark.asyncio
async def test_get_history_falls_back_to_recency_without_embedding():
    meal = MealLog(
        meal_id="m1",
        user_id="user-1",
        logged_at=datetime(2026, 6, 11, 8, 0),
        meal_type="breakfast",
        kcal=640,
        protein_g=17,
        carbs_g=21,
        fat_g=15,
        fiber_g=2,
        entities=[],
    )
    session = MagicMock()
    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = [meal]
    session.execute = AsyncMock(return_value=exec_result)
    factory = _mock_session_factory(session)

    with patch("backend.agent.tools.history.get_session", return_value=factory):
        results = await get_history("user-1")

    assert len(results) == 1
    assert results[0]["meal_id"] == "m1"
    # No embedding -> ordered by recency, not ANN.
    stmt = session.execute.call_args[0][0]
    assert "ORDER BY meal_log.logged_at DESC" in str(stmt)


@pytest.mark.asyncio
async def test_get_history_uses_ann_with_embedding():
    session = MagicMock()
    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=exec_result)
    factory = _mock_session_factory(session)

    with patch("backend.agent.tools.history.get_session", return_value=factory):
        await get_history("user-1", query_embedding=[0.1] * 768)

    stmt = session.execute.call_args[0][0]
    assert "<=>" in str(stmt)


@pytest.mark.asyncio
async def test_get_history_applies_meal_type_and_date_filters():
    session = MagicMock()
    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=exec_result)
    factory = _mock_session_factory(session)

    with patch("backend.agent.tools.history.get_session", return_value=factory):
        await get_history(
            "user-1",
            meal_type="breakfast",
            date_from=date(2026, 6, 1),
            date_to=date(2026, 6, 7),
        )

    stmt = str(session.execute.call_args[0][0])
    assert "meal_type" in stmt
    assert "logged_at" in stmt
