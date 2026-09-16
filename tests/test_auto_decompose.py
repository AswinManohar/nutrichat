"""auto_decompose_node breaks only composite entities, in parallel, order-kept."""

from __future__ import annotations

from unittest.mock import patch

from backend.agent.graph import auto_decompose_node
from backend.agent.tools.meals import FoodEntity


def _state(entities: list[dict]) -> dict:
    return {"entities": entities}


def _entity(name: str, composite: bool, qty: float = 200) -> dict:
    return {
        "food_name": name,
        "qty_g": qty,
        "unit": "g",
        "confidence": 1.0,
        "is_composite": composite,
        "source_dish": None,
    }


async def test_only_composite_decomposes_order_preserved() -> None:
    state = _state([_entity("chicken biryani", True), _entity("apple", False)])
    sub = [
        FoodEntity(food_name="basmati rice cooked", qty_g=150, unit="g"),
        FoodEntity(food_name="chicken thigh", qty_g=120, unit="g"),
    ]
    # Only the composite entity triggers a decompose call; the atomic one skips it.
    with patch("backend.agent.graph.decompose_to_entities", return_value=sub):
        out = await auto_decompose_node(state)

    names = [e["food_name"] for e in out["entities"]]
    assert names == ["basmati rice cooked", "chicken thigh", "apple"]
    assert out["entities"][0]["source_dish"] == "chicken biryani"
    assert out["entities"][1]["source_dish"] == "chicken biryani"
    assert out["entities"][2]["source_dish"] is None  # apple untouched


async def test_empty_decompose_keeps_dish() -> None:
    state = _state([_entity("mystery stew", True)])
    with patch("backend.agent.graph.decompose_to_entities", return_value=[]):
        out = await auto_decompose_node(state)
    assert [e["food_name"] for e in out["entities"]] == ["mystery stew"]


async def test_flag_off_is_passthrough() -> None:
    state = _state([_entity("chicken biryani", True)])
    with (
        patch("backend.agent.graph._auto_decompose_enabled", return_value=False),
        patch("backend.agent.graph.decompose_to_entities") as deco,
    ):
        out = await auto_decompose_node(state)
    deco.assert_not_called()
    assert [e["food_name"] for e in out["entities"]] == ["chicken biryani"]
