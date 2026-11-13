from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from backend.safety import profile
from backend.safety.checker import CheckResult, check
from backend.safety.render import constraint_sentence, render_recipe
from backend.safety.tables import ClinicalTables, load_tables
from tests.profile_helpers import hard_entry
from tests.recipe_helpers import make_recipe, progress, resolved

_SHIPPED = Path(__file__).resolve().parents[2] / "src/backend/config/clinical"


@pytest.fixture(scope="module")
def tables() -> ClinicalTables:
    return load_tables()


def run(
    tables: ClinicalTables,
    entries: list[profile.HardEntry],
    recipe_names: tuple[str, ...] = ("rice",),
    ingredients: list | None = None,
    today: dict | None = None,
    **recipe_fields: object,
) -> CheckResult:
    recipe = make_recipe(*recipe_names, **recipe_fields)
    found = ingredients or [resolved(n) for n in recipe_names]
    return check(recipe, found, entries, today or {}, tables, 1)


def rules(result: CheckResult) -> list[str]:
    return [f.rule for f in result.failures]


def allergy(group: str = "peanut", **kw: str) -> profile.HardEntry:
    return hard_entry(profile.AllergyValue(allergen_group=group), **kw)


def limit(nutrient: str, amount: float, unit: str, period: str = "per_meal", **kw):
    return hard_entry(
        profile.NutrientLimitValue(
            nutrient=nutrient, amount=amount, unit=unit, period=period
        ),
        **kw,
    )


def physical(kind: str, **fields: object) -> profile.HardEntry:
    return hard_entry(profile.PhysicalLimitationValue(kind=kind, **fields))


# --- acceptance scenarios US2-1 .. US2-8 -------------------------------------


def test_us2_1_peanut_oil_as_a_minor_ingredient_is_rejected(tables) -> None:
    result = run(tables, [allergy()], ("rice", "peanut oil"))

    assert not result.passed
    assert result.failures[0].rule == "allergen"
    assert "allergen: peanut" in result.failures[0].detail
    assert "peanut oil" in result.failures[0].detail


def test_us2_1_an_allergen_only_in_the_usda_description_is_caught(tables) -> None:
    ingredients = [resolved("noodle sauce", description="Sauce, satay, peanut")]

    result = run(tables, [allergy()], ("noodle sauce",), ingredients)

    assert rules(result) == ["allergen"]
    assert "USDA" in result.failures[0].detail


def test_us2_2_usda_sodium_over_the_limit_fails_whatever_the_model_claims(
    tables,
) -> None:
    entry = limit("sodium", 600, "mg")
    ingredients = [resolved("soy sauce", sodium=5000)]

    result = run(tables, [entry], ("soy sauce",), ingredients)

    failure = result.failures[0]
    assert failure.rule == "nutrient_limit" and failure.entry_id == entry.id
    assert (failure.value, failure.limit, failure.unit) == (5000, 600, "mg")


def test_us2_3_a_blood_thinner_and_vitamin_k_names_the_interaction(tables) -> None:
    entry = hard_entry(profile.MedicationValue(name="Coumadin"))
    ingredients = [resolved("kale", vitamin_k=480)]

    result = run(tables, [entry], ("kale",), ingredients)

    assert rules(result) == ["interaction"]
    assert "Coumadin" in result.failures[0].detail
    assert "vitamin K" in result.failures[0].detail


def test_us2_3_a_maoi_and_aged_cheese_is_rejected(tables) -> None:
    entry = hard_entry(profile.MedicationValue(name="Phenelzine"))
    ingredients = [resolved("parmesan", description="Cheese, parmesan, hard")]

    result = run(tables, [entry], ("parmesan",), ingredients)

    assert rules(result) == ["interaction"]
    assert "tyramine" in result.failures[0].detail


def test_us2_4_a_crunchy_recipe_fails_for_swallowing_difficulty(tables) -> None:
    result = run(tables, [physical("swallowing")], texture="puree", crunchy_or_dry=True)

    assert rules(result) == ["texture"]


def test_us2_4_a_crunchy_ingredient_counts_even_if_declared_soft(tables) -> None:
    result = run(
        tables, [physical("chewing")], ("granola", "milk"), texture="soft_bite_sized"
    )

    assert rules(result) == ["texture"]
    assert "granola" in result.failures[0].detail


def test_us2_4_a_texture_firmer_than_allowed_fails(tables) -> None:
    result = run(tables, [physical("swallowing")], texture="soft_bite_sized")
    allowed = run(tables, [physical("swallowing")], texture="puree")

    assert rules(result) == ["texture"] and allowed.passed


def test_us2_4_an_entry_max_texture_overrides_the_table_default(tables) -> None:
    entry = physical("chewing", max_texture="puree")

    assert rules(run(tables, [entry], texture="soft_bite_sized")) == ["texture"]


def test_us2_5_long_active_time_fails_a_standing_limit(tables) -> None:
    entry = physical("standing_time", max_active_minutes=15)

    result = run(tables, [entry], active_minutes=40, total_minutes=60)

    assert rules(result) == ["physical"]
    assert (result.failures[0].value, result.failures[0].limit) == (40, 15)


def test_us2_5_heavy_equipment_and_demanding_steps_fail_a_grip_limit(tables) -> None:
    result = run(
        tables,
        [physical("grip")],
        equipment=["stand mixer"],
        steps=["Knead the dough for ten minutes."],
    )

    assert rules(result) == ["physical", "physical"]


def test_us2_7_an_unresolved_ingredient_fails_a_potassium_limit(tables) -> None:
    ingredients = [resolved("rice"), resolved("wild herb", unresolved=True)]

    result = run(
        tables,
        [limit("potassium", 2000, "mg", "per_day")],
        ("rice", "wild herb"),
        ingredients,
    )

    assert rules(result) == ["nutrient_limit"]
    assert (
        "unknown" in result.failures[0].detail
        and "wild herb" in result.failures[0].detail
    )


def test_us2_7_an_unknown_nutrient_does_not_fail_an_unlimited_one(tables) -> None:
    ingredients = [resolved("rice", potassium=None)]

    assert run(tables, [limit("sodium", 600, "mg")], ingredients=ingredients).passed


def test_us2_8_a_table_edit_takes_effect_on_the_next_check(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "clinical"
    shutil.copytree(_SHIPPED, directory)
    ingredients = [resolved("pad thai", description="Noodles, rice")]
    before = load_tables(directory)

    assert run(before, [allergy()], ("pad thai",), ingredients).passed

    path = directory / "allergen_groups.yaml"
    path.write_text(path.read_text().replace('"satay"]', '"satay", "pad thai"]', 1))
    os.utime(path, ns=(1, path.stat().st_mtime_ns + 1_000_000))
    after = load_tables(directory)
    result = run(after, [allergy()], ("pad thai",), ingredients)

    assert rules(result) == ["allergen"]
    assert result.table_versions["allergen_groups"] != before.hashes["allergen_groups"]


# --- diet settings, exclusions, matching ------------------------------------


@pytest.mark.parametrize(
    ("setting", "food", "blocked"),
    [
        ("vegan", "chicken breast", True),
        ("vegan", "honey", True),
        ("vegan", "cheddar cheese", True),
        ("vegan", "lentils", False),
        ("vegetarian", "beef", True),
        ("vegetarian", "egg", False),
        ("pescatarian", "salmon", False),
        ("pescatarian", "pork", True),
        ("gluten_free", "wheat flour", True),
        ("dairy_free", "butter", True),
        ("dairy_free", "coconut milk", False),
        ("no_nuts", "peanut butter", True),
        ("no_nuts", "almonds", True),
    ],
)
def test_diet_settings_are_hard_constraints(tables, setting, food, blocked) -> None:
    entry = hard_entry(profile.DietSettingValue(setting=setting))

    result = run(tables, [entry], (food,))

    assert (rules(result) == ["diet_setting"]) is blocked
    assert result.passed is not blocked


@pytest.mark.parametrize(
    "setting", ["low_sodium", "low_sugar", "low_carb", "high_protein", "keto", "paleo"]
)
def test_preference_diets_are_applied_but_never_fail(tables, setting) -> None:
    entry = hard_entry(profile.DietSettingValue(setting=setting))

    result = run(tables, [entry], ("pasta", "sugar"))

    assert result.passed and [a.entry_id for a in result.applied] == [entry.id]


def test_a_food_exclusion_blocks_the_food_and_its_plural(tables) -> None:
    entry = hard_entry(profile.FoodExclusionValue(terms=["mushroom"]))

    result = run(tables, [entry], ("rice", "mushrooms"))

    assert rules(result) == ["food_exclusion"]


def test_a_custom_allergy_term_is_matched(tables) -> None:
    entry = hard_entry(profile.AllergyValue(custom_terms=["kiwi"]))

    assert rules(run(tables, [entry], ("kiwi fruit",))) == ["allergen"]


def test_nutmeg_is_not_a_tree_nut(tables) -> None:
    entry = allergy("tree_nut")

    assert run(tables, [entry], ("nutmeg", "butternut squash")).passed
    assert rules(run(tables, [entry], ("almond flour",))) == ["allergen"]


def test_a_pending_entry_never_binds(tables) -> None:
    result = run(tables, [allergy(state="pending")], ("peanut oil",))

    assert result.passed and result.applied == [] and result.entry_ids == []


# --- limits: per day, missing values, conflicts ------------------------------


def test_a_per_day_limit_counts_what_was_already_eaten(tables) -> None:
    entry = limit("sodium", 2000, "mg", "per_day")
    ingredients = [resolved("soup", sodium=500)]

    ok = run(
        tables, [entry], ("soup",), ingredients, {entry.id: progress(entry.id, 1400)}
    )
    over = run(
        tables, [entry], ("soup",), ingredients, {entry.id: progress(entry.id, 1600)}
    )

    assert ok.passed
    assert rules(over) == ["nutrient_limit"]
    assert (over.failures[0].value, over.failures[0].limit) == (2100, 2000)


def test_a_per_meal_limit_ignores_today_s_intake(tables) -> None:
    entry = limit("sodium", 600, "mg")
    ingredients = [resolved("soup", sodium=500)]

    result = run(
        tables, [entry], ("soup",), ingredients, {entry.id: progress(entry.id, 5000)}
    )

    assert result.passed


def test_unknown_items_logged_today_are_noted(tables) -> None:
    entry = limit("sodium", 2000, "mg", "per_day")

    result = run(
        tables, [entry], today={entry.id: progress(entry.id, 10, unknown_items=2)}
    )

    assert result.passed and "may be low" in result.notes[0]


def test_units_are_converted_before_comparing(tables) -> None:
    entry = limit("sodium", 1, "g")  # 1 g = 1000 mg

    assert run(tables, [entry], ingredients=[resolved("rice", sodium=1200)]).failures


def test_a_condition_without_its_expected_limit_is_reported(tables) -> None:
    entry = hard_entry(profile.DiagnosisValue(condition="ckd"))
    sodium = limit("sodium", 600, "mg")

    result = run(tables, [entry, sodium])

    assert result.passed
    assert "potassium limit for chronic kidney disease" in result.missing_values
    assert "sodium limit for chronic kidney disease" not in result.missing_values


def test_two_limits_on_one_nutrient_follow_the_stricter_and_say_so(tables) -> None:
    loose = limit("sodium", 800, "mg")
    strict = limit("sodium", 400, "mg")
    ingredients = [resolved("soup", sodium=500)]

    result = run(tables, [loose, strict], ("soup",), ingredients)

    assert [f.entry_id for f in result.failures] == [strict.id]
    assert set(result.conflicts[0].entry_ids) == {loose.id, strict.id}
    assert (
        "stricter" in result.conflicts[0].note and "400 mg" in result.conflicts[0].note
    )


def test_limits_in_different_periods_do_not_conflict(
    tables,
) -> None:
    meds = hard_entry(profile.MedicationValue(name="warfarin"))

    assert run(tables, [meds, limit("protein", 50, "g")]).conflicts == []


# --- malformed, applied and snapshot ----------------------------------------


def test_a_non_positive_quantity_is_malformed_and_skips_other_rules(tables) -> None:
    recipe = make_recipe("peanut oil")
    recipe.ingredients[0].qty_g = 0

    result = check(recipe, [resolved("peanut oil")], [allergy()], {}, tables, 2)

    assert rules(result) == ["malformed"] and result.attempt == 2


def test_applied_lists_every_evaluated_entry_with_a_phrase(tables) -> None:
    entries = [
        allergy(),
        limit("sodium", 600, "mg"),
        physical("chewing"),
        hard_entry(profile.DiagnosisValue(condition="hypertension")),
    ]

    result = run(tables, entries)

    assert [a.phrase for a in result.applied] == [
        "your peanut allergy",
        "your chewing difficulty",
        "your sodium limit of 600 mg per meal",
    ]
    assert result.entry_ids == [e.id for e in profile.confirmed(entries)]
    assert result.profile_version == profile.version_of(entries)
    assert result.table_versions == tables.hashes


def test_the_snapshot_round_trips_through_json(tables) -> None:
    result = run(tables, [allergy(), limit("sodium", 600, "mg")])

    assert CheckResult.model_validate(result.model_dump(mode="json")) == result


def test_the_check_is_deterministic(tables) -> None:
    entries = [allergy(), limit("sodium", 100, "mg")]
    ingredients = [resolved("peanut oil", sodium=300)]

    assert run(tables, entries, ("peanut oil",), ingredients) == run(
        tables, entries, ("peanut oil",), ingredients
    )


# --- rendering ---------------------------------------------------------------


def test_the_constraint_sentence_is_built_from_what_was_checked(tables) -> None:
    result = run(tables, [allergy(), limit("sodium", 600, "mg")])

    assert constraint_sentence(result.applied) == (
        "Kept this free of peanut and low in sodium because of your peanut allergy "
        "and your sodium limit of 600 mg per meal."
    )
    assert constraint_sentence([]) == ""


def test_the_rendered_recipe_has_the_sentence_and_the_notes(tables) -> None:
    entries = [
        allergy(),
        hard_entry(profile.DiagnosisValue(condition="ckd")),
    ]
    result = run(tables, entries)

    text = render_recipe(make_recipe("rice"), result)

    assert "- 100 g rice" in text and "1. Cook everything." in text
    assert "Kept this free of peanut because of your peanut allergy." in text
    assert (
        "No potassium limit is set for your chronic kidney disease; ask your dietitian."
        in text
    )
