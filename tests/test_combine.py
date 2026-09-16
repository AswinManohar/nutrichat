"""combine_node collapses decomposed ingredients back to their dish."""

from __future__ import annotations

from backend.agent.graph import _route_response, combine_node


def _ing(name: str, dish: str | None, qty: float = 100) -> dict:
    return {
        "food_name": name,
        "qty_g": qty,
        "unit": "g",
        "confidence": 1.0,
        "is_composite": False,
        "source_dish": dish,
    }


def test_route_response_combine() -> None:
    assert _route_response({"action": "combine", "messages": []}) == "combine"


async def test_combine_collapses_group_keeps_standalone() -> None:
    state = {
        "entities": [
            _ing("basmati rice cooked", "chicken biryani"),
            _ing("chicken thigh", "chicken biryani"),
            _ing("apple", None),
        ]
    }
    out = await combine_node(state)
    names = [e["food_name"] for e in out["entities"]]
    assert names == ["chicken biryani", "apple"]
    assert all(e["source_dish"] is None for e in out["entities"])
    assert out["action"] is None


async def test_combine_noop_when_nothing_tagged() -> None:
    state = {"entities": [_ing("apple", None), _ing("banana", None)]}
    out = await combine_node(state)
    assert [e["food_name"] for e in out["entities"]] == ["apple", "banana"]
