"""Tests for quota degrade paths in orchestrator."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agent.orchestrator import _UPGRADE_MSG


@pytest.mark.asyncio
async def test_coaching_over_quota_returns_upgrade_message():
    from backend.agent.orchestrator import _handle_coaching

    with patch("backend.agent.orchestrator.consume_llm_credit", new=AsyncMock(return_value=False)):
        result = await _handle_coaching("user-1", "how much protein today?")

    assert result["status"] == "success"
    assert result["message"] == _UPGRADE_MSG
    assert result["paused"] is False
    assert result["items"] == []


@pytest.mark.asyncio
async def test_coaching_under_quota_calls_agent():
    from backend.agent.orchestrator import _handle_coaching

    with (
        patch("backend.agent.orchestrator.consume_llm_credit", new=AsyncMock(return_value=True)),
        patch("backend.agent.orchestrator._coaching_agent") as mock_coaching,
    ):
        mock_coaching.handle = AsyncMock(return_value="You had 120g protein today.")
        result = await _handle_coaching("user-1", "how much protein today?")

    assert result["message"] == "You had 120g protein today."


@pytest.mark.asyncio
async def test_classify_intent_over_quota_defaults_to_log_meal():
    from backend.agent.orchestrator import _classify_intent

    with patch("backend.agent.orchestrator.consume_llm_credit", new=AsyncMock(return_value=False)):
        intent = await _classify_intent("blah blah", "user-1")

    assert intent == "log_meal"


@pytest.mark.asyncio
async def test_classify_intent_keyword_match_skips_quota():
    from backend.agent.orchestrator import _classify_intent

    mock_credit = AsyncMock(return_value=False)
    with patch("backend.agent.orchestrator.consume_llm_credit", new=mock_credit):
        intent = await _classify_intent("I ate rice", "user-1")

    mock_credit.assert_not_called()
    assert intent == "log_meal"


@pytest.mark.asyncio
async def test_meal_logging_over_quota_returns_upgrade_message():
    from backend.agent.orchestrator import _handle_meal_logging

    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock()

    with patch("backend.agent.orchestrator.consume_llm_credit", new=AsyncMock(return_value=False)):
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
    assert result["message"] == _UPGRADE_MSG
    assert result["paused"] is False


@pytest.mark.asyncio
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
