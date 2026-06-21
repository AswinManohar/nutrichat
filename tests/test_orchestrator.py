from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from backend.agent.orchestrator import _IntentResult, _classify_intent, handle_message


@pytest.fixture(autouse=True)
def _mock_fact_task():
    """Keep extract_and_store_facts.delay() off the real Redis broker."""
    with patch("backend.agent.orchestrator.extract_and_store_facts") as task_mock:
        yield task_mock


@pytest.mark.asyncio
async def test_classify_intent_log_signal_no_llm():
    mock_llm = MagicMock()
    with patch("backend.agent.orchestrator._intent_llm", mock_llm):
        intent = await _classify_intent("I had 2 scrambled eggs for breakfast", "user-1")

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
            "backend.agent.orchestrator.consume_llm_credit", new=AsyncMock(return_value=True)
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
            "backend.agent.orchestrator.consume_llm_credit", new=AsyncMock(return_value=True)
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
            "backend.agent.orchestrator.consume_llm_credit", new=AsyncMock(return_value=True)
        ),
        patch(
            "backend.agent.orchestrator._coaching_agent.handle",
            new_callable=AsyncMock,
            return_value="You've had 1,240 kcal today.",
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
            "backend.agent.orchestrator.consume_llm_credit", new=AsyncMock(return_value=True)
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
            "backend.agent.orchestrator.consume_llm_credit", new=AsyncMock(return_value=True)
        ),
    ):
        await handle_message("user-1", "I had 2 eggs", "thread-1", None)

    _mock_fact_task.delay.assert_called_once_with("user-1", "I had 2 eggs", "ok")
