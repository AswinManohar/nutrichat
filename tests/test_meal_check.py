"""The meal-logging profile check (safety/meal_check.py) and its save gate."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.agent import orchestrator
from backend.agent.meal_logging.meals import MealLogResult
from backend.api import meals
from backend.safety import meal_check, profile
from backend.safety.meal_check import MealCheck, MealNeedsAck, check_meal, gate_log
from backend.safety.tables import ClinicalTables, load_tables
from tests.profile_helpers import hard_entry
from tests.recipe_helpers import progress


@pytest.fixture(scope="module")
def tables() -> ClinicalTables:
    return load_tables()


def item(name: str, phrase: str | None = None, **nutrients: float) -> dict:
    """A card item as the graph stores it; nutrients keyed by USDA name."""
    keys = {"sodium": "Sodium, Na", "vitamin_k": "Vitamin K (phylloquinone)"}
    units = {"sodium": "mg", "vitamin_k": "µg"}
    return {
        "food_name": name,
        "input_phrase": phrase,
        "qty_g": 100,
        "protein_g": 5.0,
        "carbs_g": 10.0,
        "nutrients": {
            keys[k]: {"amount": v, "unit": units[k]} for k, v in nutrients.items()
        },
    }


def allergy(group: str = "peanut") -> profile.HardEntry:
    return hard_entry(profile.AllergyValue(allergen_group=group))


def sodium_limit(amount: float, period: str = "per_day") -> profile.HardEntry:
    return hard_entry(
        profile.NutrientLimitValue(
            nutrient="sodium", amount=amount, unit="mg", period=period
        )
    )


def rules(check: MealCheck) -> list[str]:
    return [w.rule for w in check.warnings]


def test_an_allergen_needs_log_anyway_and_names_the_food(tables) -> None:
    check = check_meal(
        [item("Peanut butter, smooth", "pb toast")], [allergy()], {}, tables
    )

    assert check.needs_ack
    assert rules(check) == ["allergen"]
    assert check.warnings[0].text.startswith("Pb toast may contain")
    assert "allergy list" in check.text


def test_the_users_words_are_checked_as_well_as_the_usda_match(tables) -> None:
    check = check_meal(
        [item("Sauce, ready-to-serve", "satay peanut sauce")], [allergy()], {}, tables
    )

    assert rules(check) == ["allergen"]


def test_a_meal_without_profile_hits_logs_without_asking(tables) -> None:
    check = check_meal([item("Rice, white, cooked", "rice")], [allergy()], {}, tables)

    assert check == MealCheck(warnings=[], needs_ack=False)
    assert check.text == ""


def test_a_pending_allergy_never_warns(tables) -> None:
    pending = hard_entry(profile.AllergyValue(allergen_group="peanut"), state="pending")

    assert check_meal([item("Peanuts, raw")], [pending], {}, tables).warnings == []


def test_a_medication_food_interaction_needs_log_anyway(tables) -> None:
    maoi = hard_entry(profile.MedicationValue(name="Phenelzine"))

    check = check_meal([item("Cheese, parmesan, grated")], [maoi], {}, tables)

    assert check.needs_ack
    assert rules(check) == ["interaction"]
    assert "Phenelzine" in check.warnings[0].text


def test_a_diet_setting_hit_is_a_reminder_only(tables) -> None:
    vegetarian = hard_entry(profile.DietSettingValue(setting="vegetarian"))

    check = check_meal(
        [item("Chicken, breast, roasted", "chicken")], [vegetarian], {}, tables
    )

    assert rules(check) == ["diet_setting"]
    assert not check.needs_ack


def test_a_per_day_limit_adds_today_and_warns_without_asking(tables) -> None:
    entry = sodium_limit(2000)
    today = {entry.id: progress(entry.id, 1500)}

    check = check_meal([item("Soup", sodium=800)], [entry], today, tables)

    assert rules(check) == ["nutrient_limit"]
    assert not check.needs_ack
    assert "2,300 mg" in check.warnings[0].text
    assert "2,000 mg" in check.warnings[0].text


def test_a_meal_under_the_limit_says_nothing(tables) -> None:
    entry = sodium_limit(2000)
    today = {entry.id: progress(entry.id, 100)}

    assert check_meal([item("Soup", sodium=800)], [entry], today, tables).warnings == []


def test_a_meal_with_none_of_the_nutrient_never_warns_on_an_over_day(tables) -> None:
    entry = sodium_limit(2000)
    today = {entry.id: progress(entry.id, 2500)}

    assert check_meal([item("Apple", sodium=0)], [entry], today, tables).warnings == []


def test_a_per_meal_limit_ignores_today(tables) -> None:
    entry = sodium_limit(600, period="per_meal")
    today = {entry.id: progress(entry.id, 5000)}

    assert check_meal([item("Soup", sodium=500)], [entry], today, tables).warnings == []


def test_an_unknown_value_for_a_limited_nutrient_is_named(tables) -> None:
    check = check_meal([item("Mystery stew", "stew")], [sodium_limit(2000)], {}, tables)

    assert rules(check) == ["unknown"]
    assert "stew" in check.warnings[0].text


def test_a_vitamin_k_ceiling_warns_in_micrograms(tables) -> None:
    warfarin = hard_entry(profile.MedicationValue(name="warfarin"))

    check = check_meal([item("Kale, raw", vitamin_k=390)], [warfarin], {}, tables)

    assert rules(check) == ["interaction_ceiling"]
    assert not check.needs_ack
    assert "390 mcg" in check.warnings[0].text


def test_an_unknown_vitamin_k_value_is_not_a_reminder(tables) -> None:
    warfarin = hard_entry(profile.MedicationValue(name="warfarin"))

    assert check_meal([item("Rice")], [warfarin], {}, tables).warnings == []


def test_warnings_that_need_log_anyway_come_first(tables) -> None:
    entry = sodium_limit(100)

    check = check_meal(
        [item("Peanuts, salted", sodium=400)], [entry, allergy()], {}, tables
    )

    assert rules(check) == ["allergen", "nutrient_limit"]


async def test_a_failed_check_needs_log_anyway() -> None:
    with patch.object(meal_check, "load_hard_profile", AsyncMock(side_effect=OSError)):
        check = await meal_check.check_meal_for("u1", [item("Rice")])

    assert check.needs_ack
    assert rules(check) == ["unavailable"]


async def test_the_gate_refuses_an_unacknowledged_allergen() -> None:
    with (
        patch.object(
            meal_check, "load_hard_profile", AsyncMock(return_value=[allergy()])
        ),
        pytest.raises(MealNeedsAck) as raised,
    ):
        await gate_log("u1", [item("Peanuts, raw")], acknowledged=False)

    assert raised.value.check.needs_ack


async def test_the_gate_records_what_was_acknowledged() -> None:
    entry = allergy()
    with patch.object(meal_check, "load_hard_profile", AsyncMock(return_value=[entry])):
        flags = await gate_log("u1", [item("Peanuts, raw")], acknowledged=True)

    assert flags == {"safety_ack": [{"rule": "allergen", "entry_id": entry.id}]}


async def test_reminders_alone_record_nothing() -> None:
    vegetarian = hard_entry(profile.DietSettingValue(setting="vegetarian"))
    with patch.object(
        meal_check, "load_hard_profile", AsyncMock(return_value=[vegetarian])
    ):
        flags = await gate_log("u1", [item("Chicken, roasted")], acknowledged=False)

    assert flags == {}


# --- POST /meals/log-items ---------------------------------------------------


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(meals.router)
    app.dependency_overrides[meals.get_current_user_id] = lambda: "u1"
    return TestClient(app)


_BODY = {
    "meal_type": "lunch",
    "items": [
        {
            "food_name": "Peanuts, raw",
            "fdc_id": 1,
            "qty_g": 50,
            "target_qty_g": 50,
            "match_confidence": 1.0,
            "candidates": [],
            "kcal": 280,
            "nutrients": {},
        }
    ],
}


def test_log_items_answers_409_with_the_warnings_to_show() -> None:
    persist = AsyncMock()
    with (
        patch.object(
            meal_check, "load_hard_profile", AsyncMock(return_value=[allergy()])
        ),
        patch.object(meals, "persist_meal", persist),
    ):
        response = _client().post("/meals/log-items", json=_BODY)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "meal_needs_ack"
    assert detail["safety"]["warnings"][0]["rule"] == "allergen"
    persist.assert_not_awaited()


def test_log_anyway_saves_the_meal_with_the_acknowledgement() -> None:
    entry = allergy()
    persist = AsyncMock(
        return_value=MealLogResult(
            meal_id="m1",
            meal_type="lunch",
            n_items=1,
            kcal=0,
            protein_g=0,
            carbs_g=0,
            fat_g=0,
            fiber_g=0,
            message="Logged",
        )
    )
    with (
        patch.object(meal_check, "load_hard_profile", AsyncMock(return_value=[entry])),
        patch.object(meals, "persist_meal", persist),
    ):
        response = _client().post(
            "/meals/log-items", json={**_BODY, "acknowledged_warnings": True}
        )

    assert response.status_code == 200
    flags = persist.await_args.kwargs["extra_flags"]
    assert flags == {"safety_ack": [{"rule": "allergen", "entry_id": entry.id}]}


async def test_the_card_carries_the_check_and_its_text(monkeypatch) -> None:
    async def _check(user_id, items):
        return check_meal(items, [allergy()], {}, load_tables())

    monkeypatch.setattr(orchestrator, "check_meal_for", _check)
    values = {"usda_results": [_BODY["items"][0] | {"input_phrase": "peanuts"}]}
    monkeypatch.setattr(orchestrator, "_serialize_items", lambda r: r)
    monkeypatch.setattr(orchestrator, "_saved_meal_payload", lambda v: None)

    fields = await orchestrator._card_fields("u1", values, "Here's your card.")

    assert fields["safety"]["needs_ack"] is True
    assert fields["message"].startswith("Here's your card.\n\nBefore you log this:")
    assert fields["items"] == values["usda_results"]
