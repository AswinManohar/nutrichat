"""_meal_label builds the human-facing dish-name snapshot from entities."""

from __future__ import annotations

from backend.agent.tools.meals import _meal_label


def _e(food_name: str, dish: str | None) -> dict:
    return {
        "food_name": food_name,
        "qty_g": 100,
        "unit": "g",
        "confidence": 1.0,
        "is_composite": False,
        "source_dish": dish,
    }


def test_label_dedups_dish_keeps_order() -> None:
    entities = [
        _e("basmati rice cooked", "chicken biryani"),
        _e("chicken thigh", "chicken biryani"),
        _e("apple", None),
    ]
    assert _meal_label(entities) == "chicken biryani, apple"


def test_label_atomic_only() -> None:
    assert _meal_label([_e("apple", None), _e("banana", None)]) == "apple, banana"


def test_label_empty() -> None:
    assert _meal_label([]) == ""
