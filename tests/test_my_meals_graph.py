"""Routing + rebuild tests for the My Meals graph integration."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from langchain_core.messages import HumanMessage

from backend.agent.graph import (
    _route_after_saved_lookup,
    _route_input,
    _route_response,
    log_node,
    saved_lookup_node,
)
from backend.agent.orchestrator import _saved_meal_payload, get_pending_card
from backend.agent.tools.saved_meals import saved_meal_to_results

_UPDATED = datetime(2026, 10, 1, 12, 0, 0, 123456, tzinfo=UTC)


def test_route_input_text_goes_to_saved_lookup() -> None:
    assert _route_input({"image_b64": ""}) == "saved_lookup"
    assert _route_input({"image_b64": "base64..."}) == "classify"


def test_route_after_saved_lookup() -> None:
    assert _route_after_saved_lookup({"from_saved": True}) == "present"
    assert _route_after_saved_lookup({"from_saved": False}) == "extract"
    assert _route_after_saved_lookup({}) == "extract"


def test_route_response_decompose_takes_priority() -> None:
    # action=decompose routes to the decompose branch regardless of message text.
    state = {"action": "decompose", "messages": []}
    assert _route_response(state) == "decompose"


def test_route_response_new_meal_goes_to_saved_lookup() -> None:
    # A fresh meal statement typed over the pending card supersedes it.
    state = {"messages": [HumanMessage(content="i had mutton curry")]}
    assert _route_response(state) == "saved_lookup"


def test_route_response_correction_still_applies() -> None:
    # A genuine correction still routes to the correction branch.
    state = {"messages": [HumanMessage(content="actually 3 eggs")]}
    assert _route_response(state) == "apply_correction"


async def test_saved_lookup_node_uses_last_human_message(monkeypatch) -> None:
    # On a resumed thread the first human message belongs to the earlier turn;
    # saved_lookup_node must key off the LAST human message.
    captured: dict[str, str] = {}

    async def fake_find_saved_meal(user_id: str, text: str):
        captured["text"] = text
        return None

    monkeypatch.setattr("backend.agent.graph.find_saved_meal", fake_find_saved_meal)
    state = {
        "user_id": "u1",
        "messages": [
            HumanMessage(content="biryani and coffee"),
            HumanMessage(content="i had mutton curry"),
        ],
    }
    out = await saved_lookup_node(state)
    assert captured["text"] == "i had mutton curry"
    assert out["from_saved"] is False
    assert out["decomposed_entities"] == []


async def test_saved_lookup_node_hit_clears_decomposed(monkeypatch) -> None:
    meal = SimpleNamespace(
        id="sm1",
        name="my usual",
        updated_at=_UPDATED,
        ingredients=[
            {
                "food_name": "rice",
                "qty_g": 150,
                "kcal": 195,
                "protein_g": 4,
                "carbs_g": 44,
                "fat_g": 0.4,
                "fiber_g": 1.2,
                "fdc_id": 123,
                "nutrients": {},
            }
        ],
    )

    async def fake_find_saved_meal(user_id: str, text: str):
        return meal

    monkeypatch.setattr("backend.agent.graph.find_saved_meal", fake_find_saved_meal)
    state = {"user_id": "u1", "messages": [HumanMessage(content="my usual")]}
    out = await saved_lookup_node(state)
    assert out["from_saved"] is True
    assert out["decomposed_entities"] == []
    assert len(out["usda_results"]) == 1
    assert out["saved_meal_id"] == "sm1"
    assert out["saved_meal_name"] == "my usual"
    assert out["saved_meal_updated_at"] == _UPDATED.isoformat()


async def test_saved_lookup_node_miss_clears_saved_meal(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.agent.graph.find_saved_meal", AsyncMock(return_value=None)
    )
    state = {
        "user_id": "u1",
        "saved_meal_id": "stale",
        "messages": [HumanMessage(content="two eggs")],
    }
    out = await saved_lookup_node(state)
    assert out["saved_meal_id"] is None
    assert out["saved_meal_name"] is None
    assert out["saved_meal_updated_at"] is None


def test_saved_meal_payload_hit_and_miss() -> None:
    assert _saved_meal_payload(
        {
            "saved_meal_id": "sm1",
            "saved_meal_name": "my usual",
            "saved_meal_updated_at": "2026-10-01T12:00:00+00:00",
        }
    ) == {
        "id": "sm1",
        "name": "my usual",
        "updated_at": "2026-10-01T12:00:00+00:00",
    }
    assert _saved_meal_payload({"saved_meal_id": None}) is None
    # Thread checkpointed before the field existed.
    assert _saved_meal_payload({}) is None


def _pending_checkpoint(values: dict) -> tuple[MagicMock, AsyncMock]:
    graph = MagicMock()
    graph.aget_state = AsyncMock(
        return_value=SimpleNamespace(next=("await_response",), values=values)
    )
    return graph


async def test_pending_card_includes_saved_meal(monkeypatch) -> None:
    graph = _pending_checkpoint(
        {
            "messages": [],
            "usda_results": [],
            "saved_meal_id": "sm1",
            "saved_meal_name": "my usual",
            "saved_meal_updated_at": "ts",
        }
    )
    monkeypatch.setattr("backend.agent.orchestrator._graph_for", lambda cp: graph)
    out = await get_pending_card("u1", "t1", object())
    assert out["saved_meal"] == {"id": "sm1", "name": "my usual", "updated_at": "ts"}


async def test_pending_card_saved_meal_null_for_old_thread(monkeypatch) -> None:
    graph = _pending_checkpoint({"messages": [], "usda_results": []})
    monkeypatch.setattr("backend.agent.orchestrator._graph_for", lambda cp: graph)
    out = await get_pending_card("u1", "t1", object())
    assert out["saved_meal"] is None


def _log_state(**extra) -> dict:
    return {
        "user_id": "u1",
        "meal_type": "lunch",
        "entities": [{"food_name": "rice", "qty_g": 150}],
        "usda_results": [],
        **extra,
    }


async def test_log_node_stamps_saved_meal_flag_and_label(monkeypatch) -> None:
    logged = AsyncMock(return_value=SimpleNamespace(meal_id="m1", message="ok"))
    monkeypatch.setattr("backend.agent.graph.log_meal", logged)
    await log_node(_log_state(saved_meal_id="sm1", saved_meal_name="My Usual"))
    assert logged.call_args.kwargs["label"] == "My Usual"
    assert logged.call_args.kwargs["extra_flags"] == {"saved_meal_id": "sm1"}


async def test_log_node_without_saved_meal_has_no_flag(monkeypatch) -> None:
    logged = AsyncMock(return_value=SimpleNamespace(meal_id="m1", message="ok"))
    monkeypatch.setattr("backend.agent.graph.log_meal", logged)
    await log_node(_log_state())
    assert logged.call_args.kwargs["label"] == "rice"
    assert logged.call_args.kwargs["extra_flags"] is None


def test_saved_meal_to_results_rebuilds_state() -> None:
    meal = SimpleNamespace(
        ingredients=[
            {
                "food_name": "basmati rice cooked",
                "qty_g": 150,
                "kcal": 195,
                "protein_g": 4,
                "carbs_g": 44,
                "fat_g": 0.4,
                "fiber_g": 1.2,
                "fdc_id": 123,
                "nutrients": {"Sodium, Na": {"amount": 1.0, "unit": "mg"}},
            }
        ]
    )
    usda_results, entities = saved_meal_to_results(meal)
    assert len(usda_results) == 1 and len(entities) == 1
    r = usda_results[0]
    assert r["food_name"] == "basmati rice cooked"
    assert r["qty_g"] == 150 and r["kcal"] == 195 and r["fdc_id"] == 123
    assert r["match_confidence"] == 1.0 and r["source"] == "USDA"
    assert "Sodium, Na" in r["nutrients"]
    # entities are the FoodEntity-shaped subset for correction re-resolution
    assert entities[0] == {
        "food_name": "basmati rice cooked",
        "qty_g": 150,
        "unit": "g",
        "confidence": 1.0,
    }
