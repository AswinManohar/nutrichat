from __future__ import annotations

from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agent.tools.history import (
    get_category_breakdown,
    get_food_breakdown_for_range,
    get_history,
    get_macros_for_range,
    get_micronutrients_for_range,
    get_nutrient_checkup_aggregates,
    summarize_nutrient_checkup,
)
from backend.core.nutrition_day import NUTRITION_DATE_SQL, sql_day_params
from backend.db.models import MealLog


def _mock_session_factory(session: MagicMock) -> MagicMock:
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=session)


async def test_get_category_breakdown_computes_share():
    rows = [
        MagicMock(
            meal_type="dinner",
            n_meals=10,
            days_logged=8,
            avg_kcal=700.0,
            avg_protein_g=35.0,
            avg_carbs_g=60.0,
            avg_fat_g=25.0,
            avg_fiber_g=8.0,
            total_kcal=7000.0,
        ),
        MagicMock(
            meal_type="breakfast",
            n_meals=10,
            days_logged=9,
            avg_kcal=300.0,
            avg_protein_g=15.0,
            avg_carbs_g=40.0,
            avg_fat_g=8.0,
            avg_fiber_g=5.0,
            total_kcal=3000.0,
        ),
    ]
    session = MagicMock()
    exec_result = MagicMock()
    exec_result.all.return_value = rows
    session.execute = AsyncMock(return_value=exec_result)
    factory = _mock_session_factory(session)

    with patch("backend.agent.tools.history.get_session", return_value=factory):
        out = await get_category_breakdown("user-1", days=30)

    assert [c["meal_type"] for c in out] == ["dinner", "breakfast"]
    # 7000 / (7000+3000) = 70%, 3000/10000 = 30%
    assert out[0]["share_kcal_pct"] == 70.0
    assert out[1]["share_kcal_pct"] == 30.0
    assert out[0]["n_meals"] == 10
    assert out[0]["days_logged"] == 8


async def test_get_category_breakdown_empty_no_div_zero():
    session = MagicMock()
    exec_result = MagicMock()
    exec_result.all.return_value = []
    session.execute = AsyncMock(return_value=exec_result)
    factory = _mock_session_factory(session)

    with patch("backend.agent.tools.history.get_session", return_value=factory):
        out = await get_category_breakdown("user-1", days=30)

    assert out == []


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
        assert f"{NUTRITION_DATE_SQL} BETWEEN :date_from AND :date_to" in stmt
        assert "deleted_at IS NULL" in stmt
        assert call[0][1]["day_tz"] == sql_day_params()["day_tz"]
        assert call[0][1]["day_reset_h"] == sql_day_params()["day_reset_h"]


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


# ---------------------------------------------------------------------------
# get_nutrient_checkup_aggregates
# ---------------------------------------------------------------------------


def _macros(protein_g: float, fiber_g: float) -> dict[str, float]:
    return {
        "kcal": 0.0,
        "protein_g": protein_g,
        "carbs_g": 0.0,
        "fat_g": 0.0,
        "fiber_g": fiber_g,
        "n_meals": 0,
    }


async def test_nutrient_checkup_computes_averages_and_trend():
    # Current week: 700g protein / 7 = 100/day. Prior week: 350g / 7 = 50/day
    # -> +100% trend, direction "up".
    cur_macros = _macros(protein_g=700.0, fiber_g=140.0)
    prev_macros = _macros(protein_g=350.0, fiber_g=140.0)

    cur_micro = {"Total Sugars": {"amount": 700.0, "unit": "g"}}
    prev_micro = {"Total Sugars": {"amount": 700.0, "unit": "g"}}

    with (
        patch(
            "backend.agent.tools.history.get_macros_for_range",
            new_callable=AsyncMock,
            side_effect=[cur_macros, prev_macros],
        ),
        patch(
            "backend.agent.tools.history.get_micronutrients_for_range",
            new_callable=AsyncMock,
            side_effect=[cur_micro, prev_micro],
        ),
    ):
        result = await get_nutrient_checkup_aggregates("user-1", date(2026, 6, 14))

    assert result["Protein"]["avg"] == pytest.approx(100.0)
    assert result["Protein"]["prev_avg"] == pytest.approx(50.0)
    assert result["Protein"]["trend_pct"] == pytest.approx(1.0)
    assert result["Protein"]["direction"] == "up"
    assert result["Protein"]["unit"] == "g"

    # Fiber unchanged -> flat.
    assert result["Fiber"]["trend_pct"] == pytest.approx(0.0)
    assert result["Fiber"]["direction"] == "flat"

    # Sugar unchanged -> flat, unit taken from the micronutrient result.
    assert result["Sugar"]["avg"] == pytest.approx(100.0)
    assert result["Sugar"]["direction"] == "flat"
    assert result["Sugar"]["unit"] == "g"

    # rda_pct = avg / RDA * 100. Protein avg=100, RDA=50 -> 200%.
    assert result["Protein"]["rda_pct"] == pytest.approx(200.0)
    # Fiber avg=20, RDA=28 -> ~71.4%.
    assert result["Fiber"]["rda_pct"] == pytest.approx(100.0 * 20.0 / 28.0)
    # Sugar avg=100, RDA=50 -> 200%.
    assert result["Sugar"]["rda_pct"] == pytest.approx(200.0)


async def test_nutrient_checkup_handles_missing_data():
    cur_macros = _macros(protein_g=0.0, fiber_g=0.0)
    prev_macros = _macros(protein_g=0.0, fiber_g=0.0)

    with (
        patch(
            "backend.agent.tools.history.get_macros_for_range",
            new_callable=AsyncMock,
            side_effect=[cur_macros, prev_macros],
        ),
        patch(
            "backend.agent.tools.history.get_micronutrients_for_range",
            new_callable=AsyncMock,
            side_effect=[{}, {}],
        ),
    ):
        result = await get_nutrient_checkup_aggregates("user-1", date(2026, 6, 14))

    # No data at all -> zero averages, no trend, "flat".
    assert result["Protein"]["avg"] == 0.0
    assert result["Protein"]["trend_pct"] is None
    assert result["Protein"]["direction"] == "flat"

    # Vitamins absent from the micronutrient result -> zero avg, fall back
    # to the configured unit.
    assert result["Vitamin C"]["avg"] == 0.0
    assert result["Vitamin C"]["unit"] == "mg"

    # Zero avg -> rda_pct is 0, not None (RDA itself is never 0).
    assert result["Protein"]["rda_pct"] == pytest.approx(0.0)


async def test_nutrient_checkup_no_prior_baseline_is_up_not_division_error():
    cur_macros = _macros(protein_g=70.0, fiber_g=0.0)
    prev_macros = _macros(protein_g=0.0, fiber_g=0.0)

    with (
        patch(
            "backend.agent.tools.history.get_macros_for_range",
            new_callable=AsyncMock,
            side_effect=[cur_macros, prev_macros],
        ),
        patch(
            "backend.agent.tools.history.get_micronutrients_for_range",
            new_callable=AsyncMock,
            side_effect=[{}, {}],
        ),
    ):
        result = await get_nutrient_checkup_aggregates("user-1", date(2026, 6, 14))

    assert result["Protein"]["avg"] == pytest.approx(10.0)
    assert result["Protein"]["prev_avg"] == 0.0
    assert result["Protein"]["trend_pct"] is None
    assert result["Protein"]["direction"] == "up"


# ---------------------------------------------------------------------------
# summarize_nutrient_checkup
# ---------------------------------------------------------------------------


def _item(rda_pct: float | None) -> dict[str, float | str | None]:
    return {
        "avg": 0.0,
        "prev_avg": 0.0,
        "unit": "g",
        "trend_pct": None,
        "direction": "flat",
        "rda_pct": rda_pct,
    }


def test_summarize_nutrient_checkup_returns_none_when_nothing_notable():
    nutrients = {"Protein": _item(100.0), "Fiber": _item(120.0)}

    notable, summary_text = summarize_nutrient_checkup(nutrients)

    assert notable == []
    assert summary_text is None


def test_summarize_nutrient_checkup_single_under_target():
    nutrients = {"Protein": _item(100.0), "Fiber": _item(50.0)}

    notable, summary_text = summarize_nutrient_checkup(nutrients)

    assert notable == [{"name": "Fiber", "rda_pct": 50.0, "status": "under"}]
    assert summary_text == (
        "This week, your Fiber intake is at 50% of the daily target — "
        "consider eating more whole grains, legumes, or vegetables."
    )


def test_summarize_nutrient_checkup_single_over_target():
    nutrients = {"Protein": _item(100.0), "Sugar": _item(220.0)}

    notable, summary_text = summarize_nutrient_checkup(nutrients)

    assert notable == [{"name": "Sugar", "rda_pct": 220.0, "status": "over"}]
    assert summary_text == (
        "This week, your Sugar intake is at 220% of the daily target — "
        "you're well above the daily target."
    )


def test_summarize_nutrient_checkup_top_two_by_distance_from_100():
    # Distances from 100: Fiber=50, Iron=10, Sugar=70. Top 2 -> Sugar, Fiber.
    nutrients = {
        "Fiber": _item(50.0),
        "Iron": _item(110.0),
        "Sugar": _item(170.0),
    }

    notable, summary_text = summarize_nutrient_checkup(nutrients)

    assert [item["name"] for item in notable] == ["Sugar", "Fiber"]
    assert summary_text == (
        "This week: Sugar is at 170% and Fiber is at 50% of their daily "
        "targets — let's bring these closer to your daily targets."
    )


def test_summarize_nutrient_checkup_two_under_target_combines_hints():
    nutrients = {"Fiber": _item(50.0), "Protein": _item(40.0)}

    notable, summary_text = summarize_nutrient_checkup(nutrients)

    assert [item["name"] for item in notable] == ["Protein", "Fiber"]
    assert summary_text == (
        "This week: Protein is at 40% and Fiber is at 50% of their daily "
        "targets — consider eating more lean meat, eggs, beans, or dairy "
        "and whole grains, legumes, or vegetables."
    )


def test_summarize_nutrient_checkup_ignores_none_rda_pct():
    nutrients = {"Protein": _item(None), "Fiber": _item(50.0)}

    notable, summary_text = summarize_nutrient_checkup(nutrients)

    assert [item["name"] for item in notable] == ["Fiber"]
    assert summary_text is not None
