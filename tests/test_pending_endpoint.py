"""GET /meals/pending returns the paused card or paused=false."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from backend.agent import orchestrator

pytestmark = pytest.mark.asyncio


async def test_not_paused_returns_false():
    graph = AsyncMock()
    graph.aget_state.return_value = SimpleNamespace(next=(), values={})
    with patch.object(orchestrator, "_graph_for", return_value=graph):
        out = await orchestrator.get_pending_card("u1", "t1", checkpointer=object())
    assert out == {"paused": False}


async def test_paused_returns_card():
    # usda_results entries are dicts (see _serialize_items / _handle_meal_logging),
    # not attribute-bearing objects.
    fake_result = {
        "fdc_id": 123,
        "food_name": "banana, raw",
        "qty_g": 118.0,
        "kcal": 105.0,
        "protein_g": 1.3,
        "carbs_g": 27.0,
        "fat_g": 0.4,
        "fiber_g": 3.1,
        "match_confidence": 0.95,
        "estimated": False,
    }

    class Msg:
        type = "ai"
        content = "Here's your card"

    graph = AsyncMock()
    graph.aget_state.return_value = SimpleNamespace(
        next=("intent_router",),
        values={"usda_results": [fake_result], "messages": [Msg()]},
    )
    with patch.object(orchestrator, "_graph_for", return_value=graph):
        out = await orchestrator.get_pending_card("u1", "t1", checkpointer=object())
    assert out["paused"] is True
    assert out["items"][0]["food_name"] == "banana, raw"
    assert out["message"] == "Here's your card"
