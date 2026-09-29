"""Combine restores a dish's real grams after a breakdown, never 1 g (#57)."""

from __future__ import annotations

from unittest.mock import patch

from backend.agent.graph import (
    auto_decompose_node,
    combine_node,
    decompose_node,
)
from backend.agent.tools.meals import FoodEntity
from backend.config import get_tunables


def _entity(
    name: str, qty: float, composite: bool = True, dish: str | None = None
) -> dict:
    return {
        "food_name": name,
        "qty_g": qty,
        "unit": "g",
        "confidence": 1.0,
        "is_composite": composite,
        "source_dish": dish,
    }


_SUB = [
    FoodEntity(food_name="basmati rice cooked", qty_g=150, unit="g"),
    FoodEntity(food_name="mutton", qty_g=100, unit="g"),
]


def _sub() -> list[FoodEntity]:
    return [e.model_copy() for e in _SUB]


async def test_auto_decompose_then_combine_keeps_dish_grams() -> None:
    state = {"entities": [_entity("mutton biryani", 350), _entity("apple", 100, False)]}
    with (
        patch("backend.agent.graph._auto_decompose_enabled", return_value=True),
        patch("backend.agent.graph.decompose_to_entities", return_value=_sub()),
    ):
        out = await auto_decompose_node(state)
    assert out["pre_decompose_entities"][0]["qty_g"] == 350

    state = {"entities": out["entities"], **out}
    combined = await combine_node(state)
    by_name = {e["food_name"]: e for e in combined["entities"]}
    assert by_name["mutton biryani"]["qty_g"] == 350
    assert by_name["mutton biryani"]["is_composite"] is True
    assert by_name["mutton biryani"]["source_dish"] is None
    assert by_name["apple"]["qty_g"] == 100


async def test_manual_decompose_then_combine_round_trip_repeats() -> None:
    state: dict = {
        "entities": [_entity("mutton biryani", 350)],
        "decomposed_entities": [],
        "pre_decompose_entities": [],
        "messages": [],
    }
    for _ in range(2):  # toggle break/combine repeatedly
        with patch("backend.agent.graph.decompose_to_entities", return_value=_sub()):
            state.update(await decompose_node(state))
        assert all(e["source_dish"] == "mutton biryani" for e in state["entities"])
        assert len(state["entities"]) == 2
        state.update(await combine_node(state))
        assert len(state["entities"]) == 1
        assert state["entities"][0]["qty_g"] == 350
        assert state["entities"][0]["source_dish"] is None


async def test_combine_falls_back_to_ingredient_sum() -> None:
    state = {
        "entities": [
            _entity("rice", 150, False, "mutton biryani"),
            _entity("mutton", 100, False, "mutton biryani"),
        ],
        "pre_decompose_entities": [],
    }
    out = await combine_node(state)
    assert len(out["entities"]) == 1
    assert out["entities"][0]["food_name"] == "mutton biryani"
    assert out["entities"][0]["qty_g"] == 250
    assert out["entities"][0]["is_composite"] is True


async def test_combine_never_yields_placeholder_grams() -> None:
    state = {  # no pre_decompose_entities key at all (older checkpoint)
        "entities": [
            _entity("rice", 60, False, "dish"),
            _entity("dal", 40, False, "dish"),
        ]
    }
    out = await combine_node(state)
    assert out["entities"][0]["qty_g"] >= 5


def test_flag_off_by_default_on_android_branch() -> None:
    assert get_tunables().features.auto_decompose_enabled is False


async def test_flag_off_composite_arrives_as_one_item() -> None:
    state = {"entities": [_entity("mutton biryani", 350)]}
    with (
        patch("backend.agent.graph._auto_decompose_enabled", return_value=False),
        patch("backend.agent.graph.decompose_to_entities") as deco,
    ):
        out = await auto_decompose_node(state)
    deco.assert_not_called()
    assert len(out["entities"]) == 1
    assert out["entities"][0]["qty_g"] == 350
    assert out["entities"][0]["is_composite"] is True
