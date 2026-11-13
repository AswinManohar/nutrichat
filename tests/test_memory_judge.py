from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest

from backend.agent import memory_judge
from backend.agent.memory import (
    AddFact,
    AddRestriction,
    MemoryFact,
    ProfileState,
    RemoveFact,
    ReplaceFact,
    SetDietChip,
)
from backend.agent.memory_judge import (
    HardAdd,
    HardRetire,
    adds_constraint,
    judge_hard,
    judge_ops,
    select_hard_ops,
    select_ops,
)
from backend.safety.profile import (
    AllergyValue,
    DiagnosisValue,
    DietSettingValue,
    FoodExclusionValue,
    MedicationValue,
    NutrientLimitValue,
)
from backend.safety.tables import load_tables
from tests.profile_helpers import hard_entry


def _state() -> ProfileState:
    return ProfileState(
        facts=[
            MemoryFact(id="id-b", fact="Loves chicken", kind="like", source="stated")
        ]
    )


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="https://glide.test", transport=httpx.MockTransport(handler)
    )


def _answer(question: str, probability: float, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        json={
            "model": "glide",
            "answers": {
                question: {"type": "noul", "noul": probability, "confidence": 0.5}
            },
            "usage": {"input_tokens": 300, "output_tokens": 1},
            "token_usage": 301,
        },
    )


# --- select_ops: the deterministic save decision -------------------------------


def test_select_ops_keeps_only_ops_at_or_above_the_threshold() -> None:
    ops = [
        AddRestriction(fact="Allergic to peanuts"),
        AddFact(fact="Likes salad", kind="like"),
        SetDietChip(chip="vegetarian", on=True),
        RemoveFact(id="id-b"),
    ]

    kept = select_ops(ops, [0.97, 0.12, 0.6, 0.59])

    assert kept == [
        AddRestriction(fact="Allergic to peanuts"),
        SetDietChip(chip="vegetarian", on=True),
    ]


def test_select_ops_stores_the_score_as_confidence_on_a_replacement() -> None:
    op = ReplaceFact(id="id-b", fact="Avoids chicken", kind="dislike")

    assert select_ops([op], [0.81]) == [op.model_copy(update={"confidence": 0.81})]


def _select_unjudged(ops, *, save_unjudged: bool):
    cfg = memory_judge._TUNABLES.memory.model_copy(
        update={"save_unjudged": save_unjudged}
    )
    with patch.object(memory_judge._TUNABLES, "memory", cfg):
        return select_ops(ops, [None] * len(ops))


@pytest.mark.parametrize(
    "op",
    [
        AddFact(fact="Likes salad", kind="like"),
        SetDietChip(chip="vegetarian", on=True),
    ],
)
@pytest.mark.parametrize(("save_unjudged", "n_kept"), [(True, 1), (False, 0)])
def test_select_ops_unjudged_soft_ops_follow_the_tunable(
    op, save_unjudged: bool, n_kept: int
) -> None:
    kept = _select_unjudged([op], save_unjudged=save_unjudged)

    assert len(kept) == n_kept
    assert all(getattr(k, "confidence", None) is None for k in kept)


@pytest.mark.parametrize("save_unjudged", [True, False])
def test_select_ops_unjudged_restriction_add_is_always_saved(
    save_unjudged: bool,
) -> None:
    # A missed allergy is silent; a wrong one is visible and removable.
    op = AddRestriction(fact="Allergic to peanuts")

    assert _select_unjudged([op], save_unjudged=save_unjudged) == [op]


@pytest.mark.parametrize(
    "op",
    [
        RemoveFact(id="id-b"),
        ReplaceFact(id="id-b", fact="Avoids chicken", kind="dislike"),
    ],
)
def test_select_ops_unjudged_remove_or_replace_is_held(op) -> None:
    # Unscored, these could erase a fact the user relies on.
    assert _select_unjudged([op], save_unjudged=True) == []


# --- judge_ops: one GLiDE question per candidate ------------------------------


async def test_judge_ops_without_an_api_key_scores_nothing(monkeypatch) -> None:
    monkeypatch.delenv("FASTINO_API_KEY", raising=False)

    scores = await judge_ops("x", [AddFact(fact="Likes dal", kind="like")], _state())

    assert scores == [None]


async def test_judge_ops_asks_the_right_question_per_op() -> None:
    sent: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        (question,) = body["questions"]
        sent.append((question, body["state"]))
        return _answer(question, 0.9 if question == "worth_remembering" else 0.7)

    ops = [
        AddFact(fact="Avoids chicken", kind="dislike"),
        SetDietChip(chip="gluten_free", on=True),
        RemoveFact(id="id-b"),
        RemoveFact(id="unknown"),
    ]

    with patch.object(
        memory_judge.glide, "make_client", return_value=_client(handler)
    ) as make:
        scores = await judge_ops("I've gone vegetarian", ops, _state())

    assert scores == [0.9, 0.9, 0.7, None]
    make.assert_called_once_with(5.0)
    message = "I've gone vegetarian"
    assert sorted(sent, key=lambda s: s[1]["candidate"]) == [
        ("worth_remembering", {"message": message, "candidate": "Avoids chicken"}),
        (
            "worth_remembering",
            {"message": message, "candidate": "Follows a gluten free diet"},
        ),
        ("no_longer_true", {"message": message, "candidate": "Loves chicken"}),
    ]


async def test_judge_ops_service_error_scores_none_for_that_op() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        candidate = json.loads(request.content)["state"]["candidate"]
        if candidate == "Likes dal":
            return _answer("worth_remembering", 0.0, status=503)
        return _answer("worth_remembering", 0.8)

    ops = [AddFact(fact="Likes dal", kind="like"), AddFact(fact="Vegan", kind="like")]

    with patch.object(memory_judge.glide, "make_client", return_value=_client(handler)):
        scores = await judge_ops("x", ops, _state())

    assert scores == [None, 0.8]


# --- hard facts: the three bands (spec 013 US4, T070) ---------------------------

ACCEPT = memory_judge._TUNABLES.memory.hard_accept_min_probability
ASK = memory_judge._TUNABLES.memory.hard_ask_min_probability


def _add(value, entry_type: str) -> HardAdd:
    return HardAdd(type=entry_type, value=value, evidence="quote")


def _sodium(amount: float, period: str = "per_day", unit: str = "mg"):
    return NutrientLimitValue(
        nutrient="sodium", amount=amount, unit=unit, period=period
    )


def _bands(candidates, scores, entries=()):
    return [
        (d.band, d.probability)
        for d in select_hard_ops(candidates, scores, list(entries))
    ]


@pytest.mark.parametrize(
    ("value", "entry_type"),
    [
        (AllergyValue(allergen_group="shellfish"), "allergy"),
        (DiagnosisValue(condition="diabetes"), "diagnosis"),
        (MedicationValue(name="Warfarin"), "medication"),
        (FoodExclusionValue(terms=["pork"]), "food_exclusion"),
        (DietSettingValue(setting="vegan"), "diet_setting"),
        (_sodium(1500), "nutrient_limit"),
    ],
)
def test_a_new_constraint_is_accepted_only_at_or_above_the_accept_threshold(
    value, entry_type
) -> None:
    candidate = _add(value, entry_type)

    assert _bands([candidate], [ACCEPT]) == [("accept", ACCEPT)]
    assert _bands([candidate], [ACCEPT - 0.01]) == [("ask", ACCEPT - 0.01)]
    assert _bands([candidate], [ASK]) == [("ask", ASK)]
    assert _bands([candidate], [ASK - 0.01]) == []


def test_an_unscored_candidate_is_asked_never_accepted() -> None:
    candidate = _add(AllergyValue(allergen_group="peanut"), "allergy")

    assert _bands([candidate], [None]) == [("ask", None)]


def test_a_stricter_limit_for_the_same_nutrient_and_period_is_accepted() -> None:
    confirmed = hard_entry(_sodium(2000))

    assert _bands([_add(_sodium(1500), "nutrient_limit")], [0.99], [confirmed]) == [
        ("accept", 0.99)
    ]
    # Grams against milligrams: 1.5 g is stricter than 2000 mg.
    assert _bands(
        [_add(_sodium(1.5, unit="g"), "nutrient_limit")], [0.99], [confirmed]
    ) == [("accept", 0.99)]


def test_a_looser_limit_asks_whatever_its_score() -> None:
    confirmed = hard_entry(_sodium(1500))

    assert _bands([_add(_sodium(2300), "nutrient_limit")], [0.99], [confirmed]) == [
        ("ask", 0.99)
    ]
    # Only a pending limit exists: it does not bind, so the new one adds.
    pending = hard_entry(_sodium(1500), "pending")
    assert _bands([_add(_sodium(2300), "nutrient_limit")], [0.99], [pending]) == [
        ("accept", 0.99)
    ]


def test_a_looser_limit_asks_even_at_a_low_score_and_replaces_the_one_it_loosens() -> (
    None
):
    strict = hard_entry(_sodium(1500), entry_id="e-1500")
    other = hard_entry(_sodium(2000), entry_id="e-2000")
    unrelated = hard_entry(_sodium(900, "per_meal"), entry_id="e-meal")
    candidate = _add(_sodium(2300), "nutrient_limit")

    decisions = select_hard_ops([candidate], [0.05], [other, strict, unrelated])

    assert [(d.band, d.replaces_id) for d in decisions] == [("ask", "e-1500")]


def test_a_new_addition_replaces_nothing() -> None:
    (decision,) = select_hard_ops([_add(_sodium(1500), "nutrient_limit")], [0.99], [])

    assert (decision.band, decision.replaces_id) == ("accept", None)


def test_a_limit_for_another_period_or_nutrient_is_new() -> None:
    confirmed = hard_entry(_sodium(1500))

    assert adds_constraint(
        _add(_sodium(900, "per_meal"), "nutrient_limit"), [confirmed]
    )
    other = NutrientLimitValue(
        nutrient="potassium", amount=2000, unit="mg", period="per_day"
    )
    assert adds_constraint(_add(other, "nutrient_limit"), [confirmed])


def test_a_limit_in_another_unit_family_cannot_be_compared_so_it_asks() -> None:
    fluid = hard_entry(
        NutrientLimitValue(nutrient="fluid", amount=1500, unit="ml", period="per_day")
    )
    grams = NutrientLimitValue(nutrient="fluid", amount=1, unit="g", period="per_day")

    assert adds_constraint(_add(grams, "nutrient_limit"), [fluid]) is False


def test_a_duplicate_of_a_live_entry_is_dropped_pending_or_confirmed() -> None:
    value = AllergyValue(allergen_group="peanut")

    for state in ("confirmed", "pending"):
        entry = hard_entry(value, state)
        assert _bands([_add(value, "allergy")], [0.99], [entry]) == []


def test_a_retired_twin_does_not_block_a_new_add() -> None:
    value = AllergyValue(allergen_group="peanut")
    # load_hard_profile returns live entries only; a retired one never appears.
    assert _bands([_add(value, "allergy")], [0.99], []) == [("accept", 0.99)]


def test_a_retirement_always_asks_whatever_its_score() -> None:
    warfarin = hard_entry(MedicationValue(name="Warfarin"), entry_id="e-w")
    retire = HardRetire(entry_id="e-w", evidence="off warfarin")

    assert _bands([retire], [0.99], [warfarin]) == [("ask", 0.99)]
    assert _bands([retire], [None], [warfarin]) == [("ask", None)]
    assert _bands([retire], [ASK - 0.01], [warfarin]) == [("ask", ASK - 0.01)]
    assert _bands([retire], [0.0], [warfarin]) == [("ask", 0.0)]


def test_a_retirement_already_requested_or_unknown_is_dropped() -> None:
    requested = hard_entry(MedicationValue(name="Warfarin"), entry_id="e-w").model_copy(
        update={
            "retire_requested_at": hard_entry(
                DietSettingValue(setting="vegan")
            ).created_at
        }
    )

    assert _bands([HardRetire(entry_id="e-w", evidence="x")], [0.99], [requested]) == []
    assert _bands([HardRetire(entry_id="nope", evidence="x")], [0.99], []) == []


def test_each_candidate_in_a_batch_gets_its_own_band_in_order() -> None:
    candidates = [
        _add(AllergyValue(allergen_group="shellfish"), "allergy"),
        _add(MedicationValue(name="Warfarin"), "medication"),
        _add(DietSettingValue(setting="vegan"), "diet_setting"),
    ]

    assert _bands(candidates, [0.95, 0.6, 0.2]) == [("accept", 0.95), ("ask", 0.6)]


def test_the_bands_come_from_tunables() -> None:
    cfg = memory_judge._TUNABLES.memory.model_copy(
        update={"hard_accept_min_probability": 0.8, "hard_ask_min_probability": 0.3}
    )
    candidate = _add(AllergyValue(allergen_group="peanut"), "allergy")

    with patch.object(memory_judge._TUNABLES, "memory", cfg):
        assert _bands(
            [candidate],
            [
                0.8,
            ],
        ) == [("accept", 0.8)]
        assert _bands([candidate], [0.3]) == [("ask", 0.3)]
        assert _bands([candidate], [0.29]) == []


async def test_judge_hard_asks_one_typed_question_per_candidate() -> None:
    sent: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        (question,) = body["questions"]
        sent.append((question, body["state"]))
        return _answer(question, 0.91)

    warfarin = hard_entry(MedicationValue(name="Warfarin"), entry_id="e-w")
    candidates = [
        _add(AllergyValue(allergen_group="shellfish"), "allergy"),
        _add(MedicationValue(name="Metformin"), "medication"),
        HardRetire(entry_id="e-w", evidence="off warfarin"),
        HardRetire(entry_id="unknown", evidence="x"),
    ]

    with patch.object(
        memory_judge.glide, "make_client", return_value=_client(handler)
    ) as make:
        scores = await judge_hard("msg", candidates, [warfarin], load_tables())

    assert scores == [0.91, 0.91, 0.91, None]
    make.assert_called_once_with(1.5)
    assert sorted(sent) == [
        ("no_longer_true", {"message": "msg", "candidate": "Warfarin"}),
        ("states_own_allergy", {"message": "msg", "candidate": "Shellfish allergy"}),
        ("takes_medication", {"message": "msg", "candidate": "Metformin"}),
    ]


async def test_judge_hard_without_a_key_or_on_error_scores_none(monkeypatch) -> None:
    candidate = _add(AllergyValue(allergen_group="peanut"), "allergy")
    monkeypatch.delenv("FASTINO_API_KEY", raising=False)
    assert await judge_hard("x", [candidate], [], load_tables()) == [None]

    def down(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    with patch.object(memory_judge.glide, "make_client", return_value=_client(down)):
        assert await judge_hard("x", [candidate], [], load_tables()) == [None]


def test_every_hard_question_rejects_third_person_and_hypotheticals() -> None:
    for key in memory_judge._HARD_QUESTION.values():
        question = memory_judge._ALL_QUESTIONS[key]
        assert question["type"] == "noul"
        false_case = question["criteria"]["false"]
        for word in ("someone else", "hypothetical", "question", "past", "negation"):
            assert word in false_case
