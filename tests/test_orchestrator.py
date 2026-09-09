from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from backend.agent.coaching import CoachingResult, QueryParsed
from backend.agent.orchestrator import _classify_intent, _IntentResult, handle_message
from backend.db.redis_client import CoachingTurn


@pytest.fixture(autouse=True)
def _mock_fact_task():
    """Keep extract_and_store_facts.delay() off the real Redis broker."""
    with patch("backend.agent.orchestrator.extract_and_store_facts") as task_mock:
        yield task_mock


@pytest.fixture(autouse=True)
def _mock_history_store():
    """Keep the coaching history writes off the real Redis."""
    with patch(
        "backend.agent.orchestrator.append_coaching_turns", new_callable=AsyncMock
    ) as append_mock:
        yield append_mock


@pytest.mark.asyncio
async def test_classify_intent_log_signal_no_llm():
    mock_llm = MagicMock()
    with patch("backend.agent.orchestrator._intent_llm", mock_llm):
        intent = await _classify_intent(
            "I had 2 scrambled eggs for breakfast", "user-1"
        )

    assert intent == "log_meal"
    mock_llm.ainvoke.assert_not_called()


@pytest.mark.asyncio
async def test_classify_intent_query_signal_no_llm():
    mock_llm = MagicMock()
    with patch("backend.agent.orchestrator._intent_llm", mock_llm):
        intent = await _classify_intent("how much protein have I had today?", "user-1")

    assert intent == "coaching"
    mock_llm.ainvoke.assert_not_called()


@pytest.mark.asyncio
async def test_classify_intent_food_report_naming_a_macro_is_log():
    # Regression: a food report that happens to name a macro/ingredient
    # ("3.8% fat milk", "high protein yogurt") used to match the bare "fat"/
    # "protein" query signal and misroute to coaching, so the meal never logged.
    # An explicit "i had"/"i ate" report must win over a bare macro noun (no LLM).
    mock_llm = MagicMock()
    with patch("backend.agent.orchestrator._intent_llm", mock_llm):
        for msg in (
            "I had a bannana smoothie, with 4 almonds, 4 walnuts and half a "
            "glass of 3.8% fat milk",
            "I had a high protein yogurt",
            "i ate low carbs bread",
            "I had eggs today",
        ):
            assert await _classify_intent(msg, "user-1") == "log_meal", msg
    mock_llm.ainvoke.assert_not_called()


@pytest.mark.asyncio
async def test_classify_intent_meal_plan_suggestion_is_coaching():
    # Regression: "suggest a meal plan for dinner" used to match the "for dinner"
    # log signal and short-circuit to the meal logger ("I didn't catch any food
    # items"). It must route to coaching, deterministically (no LLM).
    mock_llm = MagicMock()
    with patch("backend.agent.orchestrator._intent_llm", mock_llm):
        intent = await _classify_intent("suggest a meal plan for dinner", "user-1")

    assert intent == "coaching"
    mock_llm.ainvoke.assert_not_called()


@pytest.mark.asyncio
async def test_classify_intent_what_should_i_eat_is_coaching():
    mock_llm = MagicMock()
    with patch("backend.agent.orchestrator._intent_llm", mock_llm):
        intent = await _classify_intent("what should I eat for dinner?", "user-1")

    assert intent == "coaching"
    mock_llm.ainvoke.assert_not_called()


@pytest.mark.asyncio
async def test_classify_intent_ambiguous_uses_llm_fallback():
    mock_llm = MagicMock()
    mock_llm.ainvoke = AsyncMock(return_value=_IntentResult(type="log_meal"))
    with (
        patch("backend.agent.orchestrator._intent_llm", mock_llm),
        patch(
            "backend.agent.orchestrator.consume_llm_credit",
            new=AsyncMock(return_value=True),
        ),
    ):
        intent = await _classify_intent("coffee", "user-1")

    mock_llm.ainvoke.assert_called_once()
    assert intent == "log_meal"


def _mock_graph(*, is_paused: bool, still_paused: bool = False, usda_results=None):
    graph = MagicMock()
    paused_state = MagicMock(next=("present",) if is_paused else ())
    resumed_state = MagicMock(next=("present",) if still_paused else ())
    graph.aget_state = AsyncMock(side_effect=[paused_state, resumed_state])
    graph.aupdate_state = AsyncMock()
    graph.ainvoke = AsyncMock(
        return_value={
            "messages": [AIMessage(content="ok")],
            "usda_results": usda_results or [],
        }
    )
    return graph


@pytest.mark.asyncio
async def test_handle_message_paused_graph_always_resumes_meal_logging():
    graph = _mock_graph(is_paused=True)

    with (
        patch("backend.agent.orchestrator.build_graph", return_value=graph),
        patch("backend.agent.orchestrator._classify_intent") as classify_mock,
        patch(
            "backend.agent.orchestrator._handle_coaching", new_callable=AsyncMock
        ) as coaching_mock,
    ):
        result = await handle_message(
            "user-1", "how much protein is that", "thread-1", None
        )

    classify_mock.assert_not_called()
    coaching_mock.assert_not_called()
    graph.aupdate_state.assert_awaited_once()
    assert result["status"] == "success"
    assert result["paused"] is False


@pytest.mark.asyncio
async def test_handle_message_image_always_meal_logging():
    graph = _mock_graph(is_paused=False)

    with (
        patch("backend.agent.orchestrator.build_graph", return_value=graph),
        patch("backend.agent.orchestrator._classify_intent") as classify_mock,
        patch(
            "backend.agent.orchestrator._handle_coaching", new_callable=AsyncMock
        ) as coaching_mock,
        patch(
            "backend.agent.orchestrator.consume_llm_credit",
            new=AsyncMock(return_value=True),
        ),
    ):
        result = await handle_message(
            "user-1", "what's this?", "thread-1", None, image_b64="abc123"
        )

    classify_mock.assert_not_called()
    coaching_mock.assert_not_called()
    graph.ainvoke.assert_awaited_once()
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_handle_message_fresh_coaching_intent_routes_to_coaching():
    graph = _mock_graph(is_paused=False)

    with (
        patch("backend.agent.orchestrator.build_graph", return_value=graph),
        patch(
            "backend.agent.orchestrator._classify_intent",
            new_callable=AsyncMock,
            return_value="coaching",
        ),
        patch(
            "backend.agent.orchestrator.consume_llm_credit",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "backend.agent.orchestrator._coaching_agent.handle",
            new_callable=AsyncMock,
            return_value=CoachingResult(
                message="You've had 1,240 kcal today.",
                parsed=QueryParsed(time_range="today"),
            ),
        ) as handle_mock,
    ):
        result = await handle_message(
            "user-1", "how many calories today?", "thread-1", None
        )

    handle_mock.assert_awaited_once_with("user-1", "how many calories today?")
    graph.ainvoke.assert_not_called()
    assert result == {
        "status": "success",
        "message": "You've had 1,240 kcal today.",
        "paused": False,
        "items": [],
    }


@pytest.mark.asyncio
async def test_handle_message_fresh_log_meal_intent_runs_graph():
    graph = _mock_graph(is_paused=False)

    with (
        patch("backend.agent.orchestrator.build_graph", return_value=graph),
        patch(
            "backend.agent.orchestrator._classify_intent",
            new_callable=AsyncMock,
            return_value="log_meal",
        ),
        patch(
            "backend.agent.orchestrator.consume_llm_credit",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "backend.agent.orchestrator._coaching_agent.handle", new_callable=AsyncMock
        ) as handle_mock,
    ):
        result = await handle_message("user-1", "I had 2 eggs", "thread-1", None)

    handle_mock.assert_not_called()
    graph.ainvoke.assert_awaited_once()
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_handle_message_enqueues_fact_extraction(_mock_fact_task):
    graph = _mock_graph(is_paused=False)

    with (
        patch("backend.agent.orchestrator.build_graph", return_value=graph),
        patch(
            "backend.agent.orchestrator._classify_intent",
            new_callable=AsyncMock,
            return_value="log_meal",
        ),
        patch(
            "backend.agent.orchestrator.consume_llm_credit",
            new=AsyncMock(return_value=True),
        ),
    ):
        await handle_message("user-1", "I had 2 eggs", "thread-1", None)

    _mock_fact_task.delay.assert_called_once_with("user-1", "I had 2 eggs", "ok")


# ---------------------------------------------------------------------------
# Coaching history recording (both intents)
# ---------------------------------------------------------------------------


_EGG_ITEM = {
    "food_name": "Egg, whole, cooked, fried",
    "qty_g": 100.0,
    "match_confidence": 0.9,
    "kcal": 196.0,
    "protein_g": 13.6,
    "carbs_g": 0.8,
    "fat_g": 15.0,
    "fiber_g": 0.0,
    "fdc_id": 1,
}
_TOAST_ITEM = {
    "food_name": "Bread, white, toasted",
    "qty_g": 30.0,
    "match_confidence": 0.8,
    "kcal": 80.0,
    "protein_g": 2.4,
    "carbs_g": 15.0,
    "fat_g": 1.0,
    "fiber_g": 0.8,
    "fdc_id": 2,
}


@pytest.mark.asyncio
async def test_coaching_turn_is_recorded_verbatim(_mock_history_store):
    graph = _mock_graph(is_paused=False)

    with (
        patch("backend.agent.orchestrator.build_graph", return_value=graph),
        patch(
            "backend.agent.orchestrator._classify_intent",
            new_callable=AsyncMock,
            return_value="coaching",
        ),
        patch(
            "backend.agent.orchestrator.consume_llm_credit",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "backend.agent.orchestrator._coaching_agent.handle",
            new_callable=AsyncMock,
            return_value=CoachingResult(
                message="You've had 1,240 kcal today.",
                parsed=QueryParsed(time_range="today"),
            ),
        ),
    ):
        await handle_message("user-1", "how many calories today?", "thread-1", None)

    _mock_history_store.assert_awaited_once_with(
        "user-1",
        [
            CoachingTurn(role="user", content="how many calories today?"),
            CoachingTurn(role="assistant", content="You've had 1,240 kcal today."),
        ],
    )


@pytest.mark.asyncio
async def test_paused_logging_turn_is_recorded_as_card_summary(_mock_history_store):
    graph = _mock_graph(
        is_paused=False, still_paused=True, usda_results=[_EGG_ITEM, _TOAST_ITEM]
    )

    with (
        patch("backend.agent.orchestrator.build_graph", return_value=graph),
        patch(
            "backend.agent.orchestrator._classify_intent",
            new_callable=AsyncMock,
            return_value="log_meal",
        ),
        patch(
            "backend.agent.orchestrator.consume_llm_credit",
            new=AsyncMock(return_value=True),
        ),
    ):
        await handle_message("user-1", "fried egg and toast", "thread-1", None)

    user_id, turns = _mock_history_store.await_args.args
    assert user_id == "user-1"
    assert turns[0] == CoachingTurn(role="user", content="fried egg and toast")
    summary = turns[1].content
    assert turns[1].role == "assistant"
    assert "Egg, whole, cooked, fried 100g" in summary
    assert "Bread, white, toasted 30g" in summary
    assert "276 kcal" in summary
    assert "16g protein" in summary
    assert "awaiting confirmation" in summary


@pytest.mark.asyncio
async def test_completed_logging_turn_is_recorded_with_reply(_mock_history_store):
    graph = _mock_graph(is_paused=True, still_paused=False)
    graph.ainvoke.return_value = {
        "messages": [
            AIMessage(content="Fried egg and toast logged. Solid protein hit.")
        ],
        "usda_results": [_EGG_ITEM, _TOAST_ITEM],
        "meal_id": "m-1",
    }

    with patch("backend.agent.orchestrator.build_graph", return_value=graph):
        await handle_message("user-1", "confirm", "thread-1", None)

    _, turns = _mock_history_store.await_args.args
    assert turns == [
        CoachingTurn(role="user", content="confirm"),
        CoachingTurn(
            role="assistant", content="Fried egg and toast logged. Solid protein hit."
        ),
    ]


@pytest.mark.asyncio
async def test_image_turn_without_text_is_recorded_as_photo(_mock_history_store):
    graph = _mock_graph(is_paused=False, still_paused=True, usda_results=[_EGG_ITEM])

    with (
        patch("backend.agent.orchestrator.build_graph", return_value=graph),
        patch(
            "backend.agent.orchestrator.consume_llm_credit",
            new=AsyncMock(return_value=True),
        ),
    ):
        await handle_message("user-1", "", "thread-1", None, image_b64="abc")

    _, turns = _mock_history_store.await_args.args
    assert turns[0] == CoachingTurn(role="user", content="[sent a meal photo]")


@pytest.mark.asyncio
async def test_history_write_failure_does_not_fail_the_turn(_mock_history_store):
    _mock_history_store.side_effect = RuntimeError("boom")
    graph = _mock_graph(is_paused=False)

    with (
        patch("backend.agent.orchestrator.build_graph", return_value=graph),
        patch(
            "backend.agent.orchestrator._classify_intent",
            new_callable=AsyncMock,
            return_value="coaching",
        ),
        patch(
            "backend.agent.orchestrator.consume_llm_credit",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "backend.agent.orchestrator._coaching_agent.handle",
            new_callable=AsyncMock,
            return_value=CoachingResult(
                message="ok", parsed=QueryParsed(time_range="today")
            ),
        ),
    ):
        result = await handle_message("user-1", "how am I doing?", "thread-1", None)

    assert result["message"] == "ok"
