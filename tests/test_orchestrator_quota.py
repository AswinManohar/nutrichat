"""Tests for quota degrade paths in orchestrator."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agent.coaching import CoachingResult, QueryParsed
from backend.quota import UPGRADE_MSG


async def test_coaching_over_quota_returns_upgrade_message():
    from backend.agent.orchestrator import _handle_coaching

    with patch(
        "backend.agent.orchestrator.consume_llm_credit",
        new=AsyncMock(return_value=False),
    ):
        result = await _handle_coaching("user-1", "how much protein today?")

    assert result["status"] == "success"
    assert result["message"] == UPGRADE_MSG
    assert result["paused"] is False
    assert result["items"] == []


async def test_coaching_under_quota_calls_agent():
    from backend.agent.orchestrator import _handle_coaching

    with (
        patch(
            "backend.agent.orchestrator.consume_llm_credit",
            new=AsyncMock(return_value=True),
        ),
        patch("backend.agent.orchestrator._coaching_agent") as mock_coaching,
        patch(
            "backend.agent.orchestrator.save_coaching_response",
            new=AsyncMock(return_value=None),
        ),
    ):
        mock_coaching.handle = AsyncMock(
            return_value=CoachingResult(
                message="You had 120g protein today.",
                parsed=QueryParsed(time_range="today"),
            )
        )
        result = await _handle_coaching("user-1", "how much protein today?")

    assert result["message"] == "You had 120g protein today."


@pytest.mark.parametrize(
    "judgment_result",
    [
        # judgment path
        "confident",
        # second opinion because unsure
        "unsure",
        # second opinion because unavailable
        "unavailable",
    ],
)
async def test_routing_never_spends_a_credit(judgment_result):
    """Spec FR-005: no routing path touches usage credits."""
    from backend.agent import orchestrator
    from backend.agent.orchestrator import _IntentResult, _route
    from backend.agent.system_one import RoutingJudgment

    judgment = {
        "confident": RoutingJudgment(
            intent="coaching",
            certainty=0.99,
            raw_choice="coaching",
            reports_food=0.0,
            needs_guidance=0.0,
            latency_ms=1.0,
            model="glide",
            input_tokens=700,
        ),
        "unsure": RoutingJudgment(
            intent="coaching",
            certainty=0.6,
            raw_choice="coaching",
            reports_food=0.0,
            needs_guidance=0.0,
            latency_ms=1.0,
            model="glide",
            input_tokens=700,
        ),
        "unavailable": None,
    }[judgment_result]

    async def finished():
        return judgment, None if judgment else "not_configured"

    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=_IntentResult(type="coaching"))
    credit = AsyncMock(return_value=False)
    with (
        patch("backend.agent.orchestrator.consume_llm_credit", new=credit),
        patch.object(orchestrator, "_intent_llm", llm),
    ):
        decision = await _route("is rice ok?", asyncio.ensure_future(finished()))

    credit.assert_not_called()
    assert decision.intent == "coaching"


async def test_out_of_credit_question_reaches_coach_and_gets_upgrade_message():
    """A question is never turned into a meal card by the user's balance."""
    from backend.agent.orchestrator import handle_message
    from backend.agent.system_one import RoutingJudgment

    graph = MagicMock()
    graph.aget_state = AsyncMock(return_value=MagicMock(next=()))
    graph.ainvoke = AsyncMock()
    judgment = RoutingJudgment(
        intent="coaching",
        certainty=0.99,
        raw_choice="coaching",
        reports_food=0.0,
        needs_guidance=0.0,
        latency_ms=1.0,
        model="glide",
        input_tokens=700,
    )
    with (
        patch("backend.agent.orchestrator.build_graph", return_value=graph),
        patch(
            "backend.agent.orchestrator.judge_message",
            new=AsyncMock(return_value=(judgment, None)),
        ),
        patch(
            "backend.agent.orchestrator.consume_llm_credit",
            new=AsyncMock(return_value=False),
        ),
        patch("backend.agent.orchestrator.append_coaching_turns", new=AsyncMock()),
        patch("backend.agent.orchestrator.extract_and_store_facts"),
    ):
        result = await handle_message("user-1", "how am I doing?", "thread-1", None)

    assert result["message"] == UPGRADE_MSG
    graph.ainvoke.assert_not_called()


def _coaching_result(text: str) -> CoachingResult:
    return CoachingResult(message=text, parsed=QueryParsed(time_range="today"))


async def test_coaching_persists_and_returns_response_id():
    from backend.agent.orchestrator import _handle_coaching

    with (
        patch(
            "backend.agent.orchestrator.consume_llm_credit",
            new=AsyncMock(return_value=True),
        ),
        patch("backend.agent.orchestrator._coaching_agent") as mock_coaching,
        patch(
            "backend.agent.orchestrator.save_coaching_response",
            new_callable=AsyncMock,
            return_value="resp-123",
        ) as save_mock,
    ):
        mock_coaching.handle = AsyncMock(return_value=_coaching_result("120g today."))
        result = await _handle_coaching(
            "user-1", "protein today?", conversation_id="t-1"
        )

    assert result == {
        "status": "success",
        "message": "120g today.",
        "paused": False,
        "items": [],
        "response_id": "resp-123",
    }
    kwargs = save_mock.await_args.kwargs
    assert kwargs["user_id"] == "user-1"
    assert kwargs["conversation_id"] == "t-1"
    assert kwargs["query"] == "protein today?"
    assert kwargs["result"].message == "120g today."
    assert kwargs["model"]  # COACHING_MODEL value
    assert kwargs["trace_id"] is None or len(kwargs["trace_id"]) == 32


async def test_coaching_omits_response_id_when_persistence_fails():
    from backend.agent.orchestrator import _handle_coaching

    with (
        patch(
            "backend.agent.orchestrator.consume_llm_credit",
            new=AsyncMock(return_value=True),
        ),
        patch("backend.agent.orchestrator._coaching_agent") as mock_coaching,
        patch(
            "backend.agent.orchestrator.save_coaching_response",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        mock_coaching.handle = AsyncMock(return_value=_coaching_result("120g today."))
        result = await _handle_coaching("user-1", "protein today?")

    assert "response_id" not in result
    assert result["message"] == "120g today."


async def test_meal_logging_over_quota_returns_upgrade_message():
    from backend.agent.orchestrator import _handle_meal_logging

    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock()

    with patch(
        "backend.agent.orchestrator.consume_llm_credit",
        new=AsyncMock(return_value=False),
    ):
        result = await _handle_meal_logging(
            graph=mock_graph,
            config={"configurable": {"thread_id": "t1", "user_id": "user-1"}},
            user_input="I had rice",
            user_id="user-1",
            image_b64=None,
            is_paused=False,
        )

    mock_graph.ainvoke.assert_not_called()
    assert result["status"] == "success"
    assert result["message"] == UPGRADE_MSG
    assert result["paused"] is False


async def test_meal_logging_paused_resume_skips_quota():
    from backend.agent.orchestrator import _handle_meal_logging

    mock_state = MagicMock()
    mock_state.next = []
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value={"messages": [], "usda_results": []})
    mock_graph.aget_state = AsyncMock(return_value=mock_state)
    mock_graph.aupdate_state = AsyncMock()

    mock_credit = AsyncMock(return_value=False)
    with patch("backend.agent.orchestrator.consume_llm_credit", new=mock_credit):
        await _handle_meal_logging(
            graph=mock_graph,
            config={"configurable": {"thread_id": "t1", "user_id": "user-1"}},
            user_input="yes confirm",
            user_id="user-1",
            image_b64=None,
            is_paused=True,
        )

    mock_credit.assert_not_called()
