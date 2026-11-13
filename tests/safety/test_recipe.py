from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.safety.recipe import (
    Ingredient,
    Recipe,
    malformed_reasons,
    resolve,
    totals_for,
)
from tests.recipe_helpers import make_recipe, resolved


class _Match:
    def __init__(self, description: str, confidence: float, **nutrients: dict) -> None:
        self.fdc_id = 7
        self.description = description
        self.match_confidence = confidence
        self.macros_per_100g = {"kcal": 100.0, "protein_g": 10.0}
        self.nutrients_per_100g = nutrients


def _salty(description: str = "Soy sauce") -> _Match:
    return _Match(
        description,
        0.9,
        **{
            "Sodium, Na": {"amount": 5000.0, "unit": "mg"},
            "Water": {"amount": 70.0, "unit": "g"},
            "Vitamin K (phylloquinone)": {"amount": 100.0, "unit": "ug"},
        },
    )


def _recipe_fields(**changes: object) -> dict:
    fields: dict = make_recipe().model_dump()
    return {**fields, **changes}


@pytest.mark.parametrize(
    "changes",
    [
        {"ingredients": []},
        {"ingredients": [{"name": "x", "qty_g": 1}] * 21},
        {"steps": []},
        {"steps": ["a"] * 13},
        {"steps": ["a" * 201]},
        {"intro": "a" * 201},
        {"texture": "chewy"},
        {"active_minutes": -1},
        {"active_minutes": 30, "total_minutes": 10},
        {"servings": 0},
    ],
)
def test_recipe_limits_follow_the_contract(changes: dict) -> None:
    with pytest.raises(ValidationError):
        Recipe(**_recipe_fields(**changes))


def test_a_recipe_with_a_non_positive_quantity_is_malformed() -> None:
    recipe = make_recipe(
        ingredients=[Ingredient(name="rice", qty_g=0), Ingredient(name="oil", qty_g=5)]
    )

    assert malformed_reasons(recipe) == ["rice: quantity must be above 0 g"]


async def test_resolve_matches_every_ingredient_in_recipe_order() -> None:
    seen: list[str] = []

    def lookup(name: str) -> _Match | None:
        seen.append(name)
        return _salty(name.title())

    found = await resolve(make_recipe("soy sauce", "rice"), lookup)

    assert [r.name for r in found] == ["soy sauce", "rice"]
    assert sorted(seen) == ["rice", "soy sauce"]
    assert found[0].per_100g["sodium"] == 5000.0
    assert found[0].per_100g["vitamin_k"] == pytest.approx(100.0)  # ug -> mcg


async def test_a_match_below_the_confidence_floor_is_unresolved() -> None:
    found = await resolve(make_recipe("mystery"), lambda _: _Match("Mist", 0.3))

    assert found[0].fdc_id is None and found[0].per_100g == {}


async def test_resolve_lets_a_food_database_failure_propagate() -> None:
    def lookup(_: str) -> None:
        raise OSError("database is locked")

    with pytest.raises(OSError):
        await resolve(make_recipe("rice"), lookup)


def test_totals_are_per_serving_and_fluid_is_approximate() -> None:
    recipe = make_recipe("broth", servings=2)

    totals = {
        t.nutrient: t
        for t in totals_for(recipe, [resolved("broth", sodium=400, fluid=90)])
    }

    assert totals["sodium"].amount == 200.0
    assert totals["fluid"].amount == 45.0 and totals["fluid"].approximate
    assert not totals["sodium"].approximate


def test_an_unresolved_ingredient_makes_every_nutrient_unknown() -> None:
    recipe = make_recipe("rice", "mystery")

    totals = totals_for(
        recipe, [resolved("rice", sodium=1), resolved("mystery", unresolved=True)]
    )

    assert all(t.amount is None and t.unknown_from == ["mystery"] for t in totals)


def test_a_missing_value_makes_only_that_nutrient_unknown() -> None:
    recipe = make_recipe("rice", "oil")

    totals = {
        t.nutrient: t
        for t in totals_for(
            recipe, [resolved("rice", protein=3), resolved("oil", protein=None)]
        )
    }

    assert totals["protein"].amount is None and totals["protein"].unknown_from == [
        "oil"
    ]
    assert totals["sodium"].amount == 0.0


# --- mass balance for missing macros -----------------------------------------


def _food(**amounts: float) -> _Match:
    match = _Match(
        "Food", 1.0, **{k: {"amount": v, "unit": "g"} for k, v in amounts.items()}
    )
    match.macros_per_100g = {"kcal": 884.0, "protein_g": None}
    return match


async def test_a_missing_macro_is_zero_when_the_proximates_add_up() -> None:
    oil = _food(**{"Total lipid (fat)": 100.0, "Water": 0.0})

    [found] = await resolve(make_recipe("olive oil"), lambda _: oil)
    [total] = [
        t
        for t in totals_for(make_recipe("olive oil"), [found])
        if t.nutrient == "protein"
    ]

    assert found.per_100g["protein"] == 0.0 and found.inferred_zero == [
        "protein",
        "carbohydrate",
    ]
    assert total.amount == 0.0 and total.inferred_zero_from == ["olive oil"]


async def test_a_missing_macro_stays_unknown_when_the_proximates_fall_short() -> None:
    odd = _food(**{"Total lipid (fat)": 60.0, "Water": 30.0})

    [found] = await resolve(make_recipe("odd"), lambda _: odd)

    assert found.per_100g["protein"] is None and found.inferred_zero == []


async def test_minerals_are_never_inferred() -> None:
    oil = _food(**{"Total lipid (fat)": 100.0})

    [found] = await resolve(make_recipe("oil"), lambda _: oil)

    assert found.per_100g["sodium"] is None and found.per_100g["vitamin_k"] is None


async def test_an_unresolved_ingredient_gets_no_inferred_zero() -> None:
    [found] = await resolve(make_recipe("oil"), lambda _: _Match("Oil", 0.1))
    total = {t.nutrient: t for t in totals_for(make_recipe("oil"), [found])}["protein"]

    assert total.amount is None and total.inferred_zero_from == []


async def _protein_check(match: _Match | None, **recipe_fields: object):
    from backend.safety import profile
    from backend.safety.checker import check
    from backend.safety.tables import load_tables
    from tests.profile_helpers import hard_entry

    entry = hard_entry(
        profile.NutrientLimitValue(
            nutrient="protein", amount=60, unit="g", period="per_meal"
        )
    )
    recipe = make_recipe("olive oil")
    found = await resolve(recipe, lambda _: match)
    return check(recipe, found, [entry], {}, load_tables(), 1)


async def test_olive_oil_passes_a_protein_limit_by_mass_balance() -> None:
    oil = _food(**{"Total lipid (fat)": 100.0})

    assert (await _protein_check(oil)).passed


async def test_missing_protein_still_fails_without_mass_balance_or_a_match() -> None:
    odd = _food(**{"Total lipid (fat)": 60.0})

    assert not (await _protein_check(odd)).passed
    assert not (await _protein_check(None)).passed
