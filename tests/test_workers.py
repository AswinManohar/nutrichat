from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from backend.db.models import MealLog
from backend.workers.tasks import (
    _ExtractedFacts,
    aggregate_daily_summary,
    build_weekly_summary,
    embed_meal_summary,
    extract_and_store_facts,
    reset_day_keys,
)


def _mock_session_factory(session: MagicMock) -> MagicMock:
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=session)


def test_embed_meal_summary_writes_embedding():
    meal = MealLog(
        meal_id="m1",
        user_id="user-1",
        meal_type="breakfast",
        kcal=300,
        protein_g=20,
        carbs_g=10,
        fat_g=5,
        fiber_g=3,
        entities=[{"food_name": "Bananas, raw"}, {"food_name": "Yogurt, Greek"}],
    )
    session = MagicMock()
    session.get = AsyncMock(return_value=meal)
    session.commit = AsyncMock()
    factory = _mock_session_factory(session)

    with (
        patch("backend.workers.tasks.get_session", return_value=factory),
        patch(
            "backend.workers.tasks.embed_text",
            new_callable=AsyncMock,
            return_value=[0.1] * 768,
        ) as embed_mock,
    ):
        embed_meal_summary(meal_id="m1")

    embed_mock.assert_awaited_once()
    assert "Bananas, raw" in embed_mock.call_args[0][0]
    assert meal.embedding == [0.1] * 768
    session.commit.assert_awaited_once()


def test_extract_and_store_facts_inserts_new_fact():
    session = MagicMock()
    no_match = MagicMock()
    no_match.first.return_value = None
    session.execute = AsyncMock(return_value=no_match)
    session.commit = AsyncMock()
    session.add = MagicMock()
    factory = _mock_session_factory(session)

    parser_mock = MagicMock()
    parser_mock.ainvoke = AsyncMock(
        return_value=_ExtractedFacts(facts=["prefers oat milk"])
    )

    with (
        patch("backend.workers.tasks.get_session", return_value=factory),
        patch("backend.workers.tasks._fact_extraction_llm", parser_mock),
        patch(
            "backend.workers.tasks.embed_text",
            new_callable=AsyncMock,
            return_value=[0.1] * 768,
        ),
    ):
        extract_and_store_facts("user-1", "I only drink oat milk", "Got it!")

    session.add.assert_called_once()
    added = session.add.call_args[0][0]
    assert added.fact == "prefers oat milk"
    session.commit.assert_awaited_once()


def test_extract_and_store_facts_skips_near_duplicate():
    session = MagicMock()
    near_match = MagicMock()
    near_match.first.return_value = MagicMock(distance=0.01)
    session.execute = AsyncMock(return_value=near_match)
    session.commit = AsyncMock()
    session.add = MagicMock()
    factory = _mock_session_factory(session)

    parser_mock = MagicMock()
    parser_mock.ainvoke = AsyncMock(
        return_value=_ExtractedFacts(facts=["prefers oat milk"])
    )

    with (
        patch("backend.workers.tasks.get_session", return_value=factory),
        patch("backend.workers.tasks._fact_extraction_llm", parser_mock),
        patch(
            "backend.workers.tasks.embed_text",
            new_callable=AsyncMock,
            return_value=[0.1] * 768,
        ),
    ):
        extract_and_store_facts("user-1", "I only drink oat milk", "Got it!")

    session.add.assert_not_called()


def test_extract_and_store_facts_no_facts_skips_db():
    session = MagicMock()
    factory = _mock_session_factory(session)

    parser_mock = MagicMock()
    parser_mock.ainvoke = AsyncMock(return_value=_ExtractedFacts(facts=[]))

    with (
        patch("backend.workers.tasks.get_session", return_value=factory),
        patch("backend.workers.tasks._fact_extraction_llm", parser_mock),
    ):
        extract_and_store_facts("user-1", "I had 2 eggs", "Logged 140 kcal")

    factory.assert_not_called()


def test_aggregate_daily_summary_upserts_per_user():
    select_result = MagicMock()
    select_result.all.return_value = [
        MagicMock(user_id="user-1", kcal=2100.0, protein_g=160.0, fiber_g=8.0),
    ]
    goal = MagicMock(protein_goal=150.0)

    session = MagicMock()
    session.execute = AsyncMock(side_effect=[select_result, MagicMock()])
    session.get = AsyncMock(return_value=goal)
    session.commit = AsyncMock()
    factory = _mock_session_factory(session)

    with patch("backend.workers.tasks.get_session", return_value=factory):
        aggregate_daily_summary(target_date="2026-06-10")

    assert session.execute.await_count == 2
    upsert_call = session.execute.call_args_list[1]
    params = upsert_call[0][1]
    assert params["protein_goal_hit"] is True
    assert params["has_veg_day"] is True
    assert params["date"] == date(2026, 6, 10)


def test_build_weekly_summary_computes_weak_spots_and_missed_meals():
    daily_result = MagicMock()
    daily_result.all.return_value = [
        MagicMock(
            user_id="user-1", avg_protein_g=90.0, avg_fiber_g=10.0, days_hit_protein=2
        ),
    ]
    meal_type_result = MagicMock()
    meal_type_result.all.return_value = [
        MagicMock(user_id="user-1", meal_type="lunch", n_days=6),
    ]
    goal = MagicMock(fiber_goal=30.0)

    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=[daily_result, meal_type_result, MagicMock()]
    )
    session.get = AsyncMock(return_value=goal)
    session.commit = AsyncMock()
    factory = _mock_session_factory(session)

    with patch("backend.workers.tasks.get_session", return_value=factory):
        build_weekly_summary(week_start="2026-06-01")

    upsert_call = session.execute.call_args_list[2]
    params = upsert_call[0][1]
    assert "protein" in params["weak_spots"]
    assert "fiber" in params["weak_spots"]
    assert set(params["missed_meals"]) == {"breakfast", "dinner"}


def test_reset_day_keys_resets_all_users():
    scalars_result = MagicMock()
    scalars_result.scalars.return_value.all.return_value = ["user-1", "user-2"]

    session = MagicMock()
    session.execute = AsyncMock(return_value=scalars_result)
    factory = _mock_session_factory(session)

    with (
        patch("backend.workers.tasks.get_session", return_value=factory),
        patch(
            "backend.workers.tasks.reset_day_key", new_callable=AsyncMock
        ) as reset_mock,
    ):
        reset_day_keys()

    assert reset_mock.await_count == 2
    reset_mock.assert_any_await("user-1")
    reset_mock.assert_any_await("user-2")
