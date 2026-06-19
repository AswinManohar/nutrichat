"""FoodEntity carries composite classification + decomposition provenance."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.agent.tools.meals import FoodEntity


def test_defaults_are_atomic_and_unsourced() -> None:
    e = FoodEntity(food_name="apple", qty_g=150, unit="piece")
    assert e.is_composite is False
    assert e.source_dish is None


def test_composite_and_source_dish_round_trip() -> None:
    e = FoodEntity(
        food_name="basmati rice cooked",
        qty_g=150,
        unit="g",
        is_composite=False,
        source_dish="chicken biryani",
    )
    assert e.source_dish == "chicken biryani"
    assert e.model_dump()["source_dish"] == "chicken biryani"


def test_unknown_field_still_rejected() -> None:
    with pytest.raises(ValidationError):
        FoodEntity(food_name="apple", qty_g=1, unit="g", bogus=True)
