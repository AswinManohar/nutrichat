from __future__ import annotations

import pytest

from backend.safety import profile
from backend.safety.reply_guard import food_phrases, scan
from backend.safety.tables import ClinicalTables, load_tables
from tests.profile_helpers import hard_entry


class _Match:
    def __init__(self, description: str, confidence: float = 1.0) -> None:
        self.description = description
        self.match_confidence = confidence


@pytest.fixture(scope="module")
def tables() -> ClinicalTables:
    return load_tables()


def peanut(state: str = "confirmed") -> profile.HardEntry:
    return hard_entry(profile.AllergyValue(allergen_group="peanut"), state)


def database(foods: dict[str, str]):
    calls: list[str] = []

    def lookup(phrase: str) -> _Match | None:
        calls.append(phrase)
        return _Match(foods[phrase]) if phrase in foods else None

    lookup.calls = calls  # type: ignore[attr-defined]
    return lookup


async def test_a_named_allergen_is_a_lexical_violation(tables) -> None:
    lookup = database({})

    verdict = await scan(
        "Try pad thai with crushed Peanuts.", [peanut()], tables, lookup
    )

    assert verdict.layer == "lexical"
    assert verdict.violations[0].rule == "allergen"
    assert "peanut" in verdict.retry_reason
    assert lookup.calls == []  # layer 2 never ran


async def test_the_violation_detail_does_not_quote_the_reply(tables) -> None:
    verdict = await scan("Try peanut stew tonight.", [peanut()], tables, database({}))

    assert "stew" not in verdict.violations[0].detail


async def test_a_derived_ingredient_in_a_usda_description_is_caught(tables) -> None:
    lookup = database({"pad thai": "Noodles, pad thai, made with peanut sauce"})

    verdict = await scan("How about pad thai tonight?", [peanut()], tables, lookup)

    assert verdict.layer == "usda"
    assert "'pad thai' is Noodles" in verdict.violations[0].detail
    assert "pad thai" in verdict.food_phrases


async def test_a_safe_reply_with_foods_passes_and_reports_the_food_phrases(
    tables,
) -> None:
    lookup = database({"salmon": "Fish, salmon, raw", "rice": "Rice, white"})

    verdict = await scan("Salmon with rice works well.", [peanut()], tables, lookup)

    assert verdict.violations == [] and verdict.layer == "none"
    assert set(verdict.food_phrases) == {"salmon", "rice"}


async def test_a_low_confidence_match_is_not_a_food_phrase(tables) -> None:
    def lookup(_: str) -> _Match:
        return _Match("Peanut brittle", confidence=0.2)

    verdict = await scan("A glowing tip for you.", [peanut()], tables, lookup)

    assert verdict.food_phrases == [] and verdict.violations == []


async def test_a_pending_entry_does_not_bind(tables) -> None:
    lookup = database({})

    verdict = await scan("Peanut butter toast!", [peanut("pending")], tables, lookup)

    assert verdict.violations == [] and lookup.calls == []


async def test_diet_and_interaction_terms_are_guarded_too(tables) -> None:
    entries = [
        hard_entry(profile.DietSettingValue(setting="vegan")),
        hard_entry(profile.MedicationValue(name="simvastatin")),
    ]

    chicken = await scan(
        "Roast chicken is a good dinner.", entries, tables, database({})
    )
    grapefruit = await scan("Add a grapefruit.", entries, tables, database({}))

    assert chicken.violations[0].rule == "diet_setting"
    assert grapefruit.violations[0].rule == "interaction"


def test_food_phrases_are_runs_of_non_stopwords_longest_first() -> None:
    phrases = food_phrases("Try the satay sauce with rice.", limit=40)

    assert phrases[0] == "satay sauce"
    assert {"satay", "sauce", "rice"} <= set(phrases)
    assert "the" not in phrases and "with" not in phrases


def test_food_phrases_are_capped() -> None:
    assert len(food_phrases("one two three four five six seven", limit=3)) == 3


@pytest.mark.parametrize(
    ("reply", "violates"),
    [
        ("I kept it peanut-free.", False),
        ("No peanuts in this one.", False),
        ("Without peanut butter, it still works.", False),
        ("Try peanut butter toast.", True),
        ("Skip the peanut sauce, have hummus.", False),
        ("Peanut-free bars and a satay dip.", True),
        ("Avoid peanuts. Peanut stew is a great dinner.", True),
        ("Swap out the peanut oil for olive oil.", False),
        ("A bowl, no, a big bowl of peanut noodles.", True),
    ],
)
async def test_negated_mentions_are_not_suggestions(tables, reply, violates) -> None:
    verdict = await scan(reply, [peanut()], tables, database({}))

    assert bool(verdict.violations) is violates


async def test_a_negated_mention_is_not_looked_up_as_a_food(tables) -> None:
    lookup = database({"peanut": "Peanuts, raw", "salad": "Salad"})

    verdict = await scan("A peanut-free salad works.", [peanut()], tables, lookup)

    assert verdict.violations == [] and "peanut" not in lookup.calls
    assert "salad" in verdict.food_phrases


async def test_an_excluded_term_is_not_looked_up_as_its_parts(tables) -> None:
    milk = hard_entry(profile.AllergyValue(allergen_group="milk"))
    lookup = database({"milk": "Milk, NFS", "curry": "Curry"})

    verdict = await scan("Simmer the curry in coconut milk.", [milk], tables, lookup)

    assert verdict.violations == [] and "milk" not in lookup.calls


async def test_a_lone_word_must_name_the_food_not_just_appear_in_it(tables) -> None:
    vegan = hard_entry(profile.DietSettingValue(setting="vegan"))
    lookup = database({"curry": "Beef curry"})

    verdict = await scan("Lentil curry tonight.", [vegan], tables, lookup)

    assert verdict.violations == []
