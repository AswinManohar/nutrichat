"""decompose_node caches result in decomposed_entities after first LLM call."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.agent.graph import decompose_node
from backend.agent.tools.meals import FoodEntity


def _entity(name: str, qty: float = 200) -> dict:
    return {
        "food_name": name,
        "qty_g": qty,
        "unit": "g",
        "confidence": 1.0,
        "is_composite": True,
        "source_dish": None,
    }


def _state(entities: list[dict], decomposed_entities: list[dict] | None = None) -> dict:
    return {
        "entities": entities,
        "decomposed_entities": decomposed_entities if decomposed_entities is not None else [],
        "messages": [],
    }


_RICE = FoodEntity(food_name="basmati rice", qty_g=150, unit="g")
_CHICKEN = FoodEntity(food_name="chicken thigh", qty_g=120, unit="g")


async def test_cache_miss_calls_llm_and_warms_cache() -> None:
    """First decompose: LLM is called, result stored in decomposed_entities."""
    state = _state([_entity("chicken biryani")])
    with patch(
        "backend.agent.graph.decompose_to_entities",
        return_value=[_RICE, _CHICKEN],
    ) as mock_decompose:
        out = await decompose_node(state)

    mock_decompose.assert_called_once()
    assert [e["food_name"] for e in out["entities"]] == ["basmati rice", "chicken thigh"]
    assert [e["food_name"] for e in out["decomposed_entities"]] == [
        "basmati rice",
        "chicken thigh",
    ]
    assert out["action"] is None


async def test_cache_hit_skips_llm() -> None:
    """Second decompose: cache is warm, LLM must not be called."""
    cached = [_RICE.model_dump(), _CHICKEN.model_dump()]
    state = _state([_entity("chicken biryani")], decomposed_entities=cached)

    with patch("backend.agent.graph.decompose_to_entities") as mock_decompose:
        out = await decompose_node(state)

    mock_decompose.assert_not_called()
    assert [e["food_name"] for e in out["entities"]] == ["basmati rice", "chicken thigh"]
    assert out["action"] is None


async def test_failed_decompose_does_not_populate_cache() -> None:
    """If LLM returns empty, decomposed_entities stays unset (next press retries)."""
    state = _state([_entity("mystery stew")])
    with patch("backend.agent.graph.decompose_to_entities", return_value=[]):
        out = await decompose_node(state)

    assert out == {"action": None}
    assert "decomposed_entities" not in out


async def test_decomposed_entities_in_agent_state_type() -> None:
    """AgentState TypedDict must include decomposed_entities key."""
    from backend.agent.graph import AgentState
    assert "decomposed_entities" in AgentState.__annotations__
