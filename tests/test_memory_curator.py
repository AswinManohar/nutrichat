from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from backend.agent.memory import (
    AddFact,
    ApplyOutcome,
    MemoryFact,
    ProfileState,
    RemoveFact,
    ReplaceFact,
)
from backend.agent.memory_curator import (
    CuratorOp,
    CuratorOutput,
    HardDraft,
    LogHabit,
    LogHabitsOutput,
    RetireDraft,
    build_curator_input,
    build_log_habits_input,
    curate_turn,
    evidence_in,
    extract_turn,
    infer_log_habits,
    plan_log_habit_ops,
    to_hard_candidates,
    to_memory_ops,
)
from backend.agent.memory_judge import HardAdd, HardRetire
from backend.safety.profile import (
    AllergyValue,
    DietSettingValue,
    MedicationValue,
    NutrientLimitValue,
    PhysicalLimitationValue,
)
from backend.safety.tables import load_tables
from tests.profile_helpers import hard_entry


def _state() -> ProfileState:
    return ProfileState(
        facts=[
            MemoryFact(
                id="id-a", fact="Dislikes okra", kind="dislike", source="stated"
            ),
            MemoryFact(id="id-b", fact="Loves chicken", kind="like", source="stated"),
        ],
        tombstones=["Likes spicy food"],
    )


def test_build_curator_input_lists_handles_hard_profile_and_removed_facts() -> None:
    warfarin = hard_entry(MedicationValue(name="Warfarin"), entry_id="e-w")
    pending = hard_entry(
        AllergyValue(allergen_group="peanut"), "pending", entry_id="e-p"
    )

    text = build_curator_input(
        _state(), "I'm vegetarian now", "", [warfarin, pending], load_tables()
    )

    assert "m1 [dislike] Dislikes okra" in text
    assert "m2 [like] Loves chicken" in text
    assert "h1 [confirmed] Warfarin" in text
    assert "- [pending] Peanut allergy" in text  # no handle: cannot be retired
    assert "Known condition keys: ckd, hypertension, diabetes, prediabetes" in text
    assert "vegetarian" in text.split("Diet settings available:")[1].splitlines()[0]
    assert "- Likes spicy food" in text
    assert "User: I'm vegetarian now" in text
    assert "Assistant:" not in text
    assert "% full" in text


def test_build_curator_input_includes_the_reply_when_there_is_one() -> None:
    text = build_curator_input(ProfileState(), "hi", "hello")

    assert "Current profile (0% full):\n(empty)" in text
    assert "Removed by the user:\n(none)" in text
    assert "User: hi\nAssistant: hello" in text


def test_to_memory_ops_maps_handles_to_ids() -> None:
    ops = to_memory_ops(
        [
            CuratorOp(action="add", fact=" Dislikes okra ", kind="dislike"),
            CuratorOp(
                action="replace", ref="M2", fact="No longer eats meat", kind="habit"
            ),
            CuratorOp(action="remove", ref="m2"),
        ],
        _state(),
    )

    assert ops == [
        AddFact(fact="Dislikes okra", kind="dislike"),
        ReplaceFact(id="id-b", fact="No longer eats meat", kind="habit"),
        RemoveFact(id="id-b"),
    ]


def test_to_memory_ops_drops_malformed_proposals() -> None:
    ops = to_memory_ops(
        [
            CuratorOp(action="add", fact="No kind given"),
            CuratorOp(action="add", kind="like"),
            CuratorOp(action="replace", ref="m9", fact="Unknown handle", kind="like"),
            CuratorOp(action="remove"),
        ],
        _state(),
    )

    assert ops == []


def test_to_memory_ops_truncates_overlong_facts() -> None:
    (op,) = to_memory_ops(
        [CuratorOp(action="add", fact="x" * 500, kind="like")], ProfileState()
    )

    assert len(op.fact) == 200


# --- hard candidates: the evidence check (FR-023) -----------------------------

MESSAGE = "Oh and I found out I'm allergic to Shellfish and peanuts, ugh"


def _draft(**kwargs) -> HardDraft:
    base = {
        "type": "allergy",
        "label": "Shellfish allergy",
        "evidence": "I'm allergic to shellfish",
        "terms": ["shellfish"],
    }
    return HardDraft(**{**base, **kwargs})


def _candidates(output: CuratorOutput, message: str = MESSAGE, entries=()):
    return to_hard_candidates(output, message, list(entries), load_tables())


def test_evidence_is_a_case_insensitive_substring_of_the_message() -> None:
    assert evidence_in(MESSAGE, "i'm ALLERGIC to shellfish")
    assert evidence_in("line one\nI'm   allergic", "one i'm allergic")
    assert not evidence_in(MESSAGE, "allergic to prawns")
    assert not evidence_in(MESSAGE, "   ")


def test_a_hard_draft_with_evidence_becomes_a_typed_candidate() -> None:
    (candidate,) = _candidates(CuratorOutput(hard=[_draft()]))

    assert candidate == HardAdd(
        type="allergy",
        value=AllergyValue(allergen_group="shellfish"),
        label=None,
        evidence="I'm allergic to shellfish",
    )


def test_a_draft_whose_evidence_is_not_in_the_message_is_discarded() -> None:
    drafts = [
        _draft(evidence="I am allergic to shellfish"),  # paraphrase
        _draft(evidence="Noted, I've added a shellfish allergy"),  # assistant words
    ]

    assert _candidates(CuratorOutput(hard=drafts)) == []


def test_assistant_reply_and_logs_never_produce_a_hard_candidate() -> None:
    # The reply says it, the patient's message does not: nothing to quote.
    draft = _draft(evidence="you are allergic to shellfish")

    assert (
        _candidates(CuratorOutput(hard=[draft]), "log 2 eggs and a prawn curry") == []
    )


def test_several_allergens_become_one_candidate_each() -> None:
    draft = _draft(
        label="Shellfish and strawberry allergy",
        terms=["shellfish", "strawberries"],
        evidence="allergic to Shellfish and peanuts",
    )

    values = [c.value for c in _candidates(CuratorOutput(hard=[draft]))]

    assert values == [
        AllergyValue(allergen_group="shellfish"),
        AllergyValue(custom_terms=["strawberries"]),
    ]


def test_each_hard_type_builds_its_value() -> None:
    message = (
        "I take warfarin, I can't swallow solids, my doctor says 1500 mg of "
        "sodium a day, I'm vegan and I never eat pork"
    )
    drafts = [
        _draft(type="medication", medication="Warfarin", evidence="I take warfarin"),
        _draft(
            type="physical_limitation",
            limitation="swallowing",
            max_texture="pureed",
            evidence="I can't swallow solids",
        ),
        _draft(
            type="nutrient_limit",
            nutrient="Sodium",
            amount=1500,
            unit="mg",
            period="per_day",
            evidence="1500 mg of sodium a day",
        ),
        _draft(type="diet_setting", setting="vegan", evidence="I'm vegan"),
        _draft(
            type="food_exclusion",
            terms=["pork"],
            label="No pork",
            evidence="I never eat pork",
        ),
    ]

    candidates = _candidates(CuratorOutput(hard=drafts), message)

    assert [c.value for c in candidates] == [
        MedicationValue(name="Warfarin"),
        PhysicalLimitationValue(kind="swallowing", max_texture="pureed"),
        NutrientLimitValue(nutrient="sodium", amount=1500, unit="mg", period="per_day"),
        DietSettingValue(setting="vegan"),
        candidates[4].value,
    ]
    assert candidates[4].label == "No pork"


def test_a_draft_that_does_not_fit_its_type_is_discarded() -> None:
    drafts = [
        _draft(type="diet_setting", setting="carnivore", evidence="I'm allergic"),
        _draft(type="nutrient_limit", nutrient="sodium", evidence="I'm allergic"),
    ]

    assert _candidates(CuratorOutput(hard=drafts)) == []


def test_repeated_drafts_collapse_to_one_candidate() -> None:
    assert len(_candidates(CuratorOutput(hard=[_draft(), _draft()]))) == 1


def test_a_retirement_needs_a_confirmed_handle_and_evidence() -> None:
    warfarin = hard_entry(MedicationValue(name="Warfarin"), entry_id="e-w")
    pending = hard_entry(DietSettingValue(setting="vegan"), "pending", entry_id="e-v")
    message = "the doctor took me off warfarin last week"
    output = CuratorOutput(
        retire=[
            RetireDraft(ref="h1", evidence="took me off warfarin"),
            RetireDraft(ref="h1", evidence="stopped taking it"),  # not quoted
            RetireDraft(ref="h2", evidence="took me off warfarin"),  # no such handle
        ]
    )

    candidates = _candidates(output, message, [warfarin, pending])

    assert candidates == [HardRetire(entry_id="e-w", evidence="took me off warfarin")]


# --- extract_turn / curate_turn ---------------------------------------------------


def _llm_returning(output: CuratorOutput) -> MagicMock:
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=output)
    return llm


def _patched(llm, *, soft_scores=(), hard_scores=(), apply=None, entries=()):
    """Patch every collaborator of extract_turn; returns the mocks by name."""
    mocks = {
        "apply": apply or AsyncMock(return_value=ApplyOutcome()),
        "add_entry": AsyncMock(
            side_effect=lambda *a, **k: hard_entry(a[1], k["state"])
        ),
        "request": AsyncMock(
            side_effect=lambda uid, eid: hard_entry(
                MedicationValue(name="Warfarin"), entry_id=eid
            )
        ),
        "judge_hard": AsyncMock(return_value=list(hard_scores)),
    }
    patches = [
        patch(
            "backend.agent.memory_curator.load_state", AsyncMock(return_value=_state())
        ),
        patch(
            "backend.agent.memory_curator.profile.load_hard_profile",
            AsyncMock(return_value=list(entries)),
        ),
        patch("backend.agent.memory_curator._curator_llm", llm),
        patch(
            "backend.agent.memory_curator.judge_ops",
            AsyncMock(return_value=list(soft_scores)),
        ),
        patch("backend.agent.memory_curator.judge_hard", mocks["judge_hard"]),
        patch("backend.agent.memory_curator.apply_ops", mocks["apply"]),
        patch("backend.agent.memory_curator.profile.add_entry", mocks["add_entry"]),
        patch(
            "backend.agent.memory_curator.profile.request_retirement", mocks["request"]
        ),
    ]
    return mocks, patches


async def _extract(llm, message=MESSAGE, **kwargs):
    mocks, patches = _patched(llm, **kwargs)
    for p in patches:
        p.start()
    try:
        return mocks, await extract_turn("user-1", message)
    finally:
        for p in patches:
            p.stop()


async def test_soft_facts_are_scored_and_applied_as_curator() -> None:
    llm = _llm_returning(
        CuratorOutput(ops=[CuratorOp(action="add", fact="Likes salad", kind="like")])
    )

    mocks, result = await _extract(llm, soft_scores=[0.9])

    mocks["apply"].assert_awaited_once_with(
        "user-1", [AddFact(fact="Likes salad", kind="like", confidence=0.9)], "curator"
    )
    mocks["add_entry"].assert_not_awaited()
    assert not result.changed_hard
    system, human = llm.ainvoke.call_args.args[0]
    assert "long-term profile" in system.content
    assert MESSAGE in human.content
    assert "Assistant:" not in human.content


async def test_an_accepted_hard_fact_is_saved_confirmed_and_inferred() -> None:
    llm = _llm_returning(CuratorOutput(hard=[_draft()]))

    mocks, result = await _extract(llm, hard_scores=[0.97])

    (call,) = mocks["add_entry"].await_args_list
    assert call.args[1] == AllergyValue(allergen_group="shellfish")
    assert call.kwargs | {} == {
        "source": "inferred",
        "state": "confirmed",
        "created_by": "curator",
        "confirmed_by": "inference",
        "label": None,
        "evidence": "I'm allergic to shellfish",
        "inference_probability": 0.97,
        "replaces_id": None,
    }
    assert len(result.accepted) == 1 and not result.asked
    mocks["apply"].assert_not_awaited()


async def test_an_ask_band_hard_fact_is_saved_pending_with_its_probability() -> None:
    llm = _llm_returning(CuratorOutput(hard=[_draft()]))

    mocks, result = await _extract(llm, hard_scores=[0.7])

    (call,) = mocks["add_entry"].await_args_list
    assert call.kwargs["state"] == "pending"
    assert call.kwargs["confirmed_by"] is None
    assert call.kwargs["inference_probability"] == 0.7
    assert len(result.asked) == 1 and not result.accepted


async def test_an_unscored_hard_fact_is_saved_pending() -> None:
    llm = _llm_returning(CuratorOutput(hard=[_draft()]))

    mocks, result = await _extract(llm, hard_scores=[None])

    assert mocks["add_entry"].await_args.kwargs["state"] == "pending"
    assert mocks["add_entry"].await_args.kwargs["inference_probability"] is None


async def test_a_low_scored_hard_fact_is_not_saved() -> None:
    llm = _llm_returning(CuratorOutput(hard=[_draft()]))

    mocks, result = await _extract(llm, hard_scores=[0.1])

    mocks["add_entry"].assert_not_awaited()
    assert not result.changed_hard


async def test_a_retirement_only_requests_it() -> None:
    warfarin = hard_entry(MedicationValue(name="Warfarin"), entry_id="e-w")
    llm = _llm_returning(
        CuratorOutput(retire=[RetireDraft(ref="h1", evidence="took me off warfarin")])
    )

    mocks, result = await _extract(
        llm,
        "the doctor took me off warfarin",
        hard_scores=[0.99],
        entries=[warfarin],
    )

    mocks["request"].assert_awaited_once_with("user-1", "e-w")
    mocks["add_entry"].assert_not_awaited()
    assert len(result.retirements) == 1


async def test_a_hard_draft_with_bad_evidence_makes_no_judge_call() -> None:
    llm = _llm_returning(
        CuratorOutput(hard=[_draft(evidence="you told me you are allergic")])
    )

    mocks, _ = await _extract(llm, hard_scores=[])

    mocks["add_entry"].assert_not_awaited()


async def test_curate_turn_returns_the_soft_outcome_only() -> None:
    llm = _llm_returning(
        CuratorOutput(ops=[CuratorOp(action="add", fact="Likes salad", kind="like")])
    )
    outcome = ApplyOutcome()
    mocks, patches = _patched(
        llm, soft_scores=[0.9], apply=AsyncMock(return_value=outcome)
    )
    for p in patches:
        p.start()
    try:
        assert await curate_turn("user-1", "I like salad", "Logged.") is outcome
    finally:
        for p in patches:
            p.stop()
    human = llm.ainvoke.call_args.args[0][1]
    assert "Assistant: Logged." in human.content


async def test_a_turn_with_nothing_to_store_skips_judge_and_writes() -> None:
    llm = _llm_returning(CuratorOutput())

    mocks, result = await _extract(llm)

    mocks["apply"].assert_not_awaited()
    mocks["judge_hard"].assert_not_awaited()
    assert not result.changed_hard


async def test_blank_input_makes_no_calls() -> None:
    load = AsyncMock()
    llm = _llm_returning(CuratorOutput())

    with (
        patch("backend.agent.memory_curator.load_state", load),
        patch("backend.agent.memory_curator._curator_llm", llm),
    ):
        await curate_turn("user-1", "   ", "Logged.")

    load.assert_not_awaited()
    llm.ainvoke.assert_not_awaited()


# --- weekly log habits -------------------------------------------------------


def _log_state() -> ProfileState:
    return ProfileState(
        facts=[
            MemoryFact(
                id="id-s", fact="Dislikes okra", kind="dislike", source="stated"
            ),
            MemoryFact(
                id="id-old",
                fact="Rarely logs breakfast",
                kind="habit",
                source="inferred_from_logs",
            ),
            MemoryFact(
                id="id-keep",
                fact="Eats mostly South Indian food",
                kind="like",
                source="inferred_from_logs",
            ),
        ],
        tombstones=["Snacks most afternoons"],
    )


def test_plan_log_habit_ops_replaces_last_weeks_facts() -> None:
    ops = plan_log_habit_ops(
        [
            LogHabit(fact="eats mostly south indian food.", kind="like"),
            LogHabit(fact="Dinner is the largest meal", kind="habit"),
        ],
        _log_state(),
        max_facts=3,
    )

    # Stale log fact removed, repeated one untouched, new one added; the
    # stated fact is never touched.
    assert ops == [
        RemoveFact(id="id-old"),
        AddFact(fact="Dinner is the largest meal", kind="habit"),
    ]


def test_plan_log_habit_ops_caps_and_dedups_proposals() -> None:
    ops = plan_log_habit_ops(
        [
            LogHabit(fact="A", kind="habit"),
            LogHabit(fact="a", kind="habit"),
            LogHabit(fact="B", kind="habit"),
            LogHabit(fact="C", kind="habit"),
        ],
        ProfileState(),
        max_facts=2,
    )

    assert ops == [AddFact(fact="A", kind="habit"), AddFact(fact="B", kind="habit")]


def test_build_log_habits_input_shows_stats_profile_and_removed() -> None:
    text = build_log_habits_input(
        _log_state(),
        {"breakfast": ["Idli", "Dosa"]},
        [
            {
                "meal_type": "breakfast",
                "n_meals": 12,
                "days_logged": 11,
                "avg_kcal": 310.4,
                "avg_protein_g": 9.6,
            }
        ],
        days=30,
        max_facts=3,
    )

    assert "- breakfast: Idli, Dosa" in text
    assert "- breakfast: 12 meals on 11 of 30 days, avg 310 kcal, 10g protein" in text
    assert "- [dislike] Dislikes okra" in text
    assert "- Snacks most afternoons" in text
    assert text.endswith("Return at most 3 facts.")


async def test_infer_log_habits_applies_as_weekly_actor() -> None:
    llm = MagicMock()
    llm.ainvoke = AsyncMock(
        return_value=LogHabitsOutput(
            facts=[LogHabit(fact="Dinner is the largest meal", kind="habit")]
        )
    )
    apply = AsyncMock(return_value=ApplyOutcome())

    with (
        patch(
            "backend.agent.memory_curator.get_staple_foods",
            AsyncMock(return_value={"dinner": ["Dal"]}),
        ),
        patch(
            "backend.agent.memory_curator.get_category_breakdown",
            AsyncMock(return_value=[]),
        ),
        patch(
            "backend.agent.memory_curator.load_state",
            AsyncMock(return_value=ProfileState()),
        ),
        patch("backend.agent.memory_curator._log_habits_llm", llm),
        patch("backend.agent.memory_curator.apply_ops", apply),
    ):
        await infer_log_habits("user-1")

    apply.assert_awaited_once_with(
        "user-1", [AddFact(fact="Dinner is the largest meal", kind="habit")], "weekly"
    )


async def test_infer_log_habits_without_staples_makes_no_model_call() -> None:
    llm = MagicMock()
    llm.ainvoke = AsyncMock()

    with (
        patch(
            "backend.agent.memory_curator.get_staple_foods", AsyncMock(return_value={})
        ),
        patch("backend.agent.memory_curator._log_habits_llm", llm),
    ):
        outcome = await infer_log_habits("user-1")

    llm.ainvoke.assert_not_awaited()
    assert outcome.results == []


def test_the_weekly_log_job_cannot_produce_a_hard_candidate() -> None:
    # Spec 013 FR-023: nothing logged becomes a hard fact. The job's output
    # has no hard field, and its ops are soft facts applied as "weekly".
    assert set(LogHabitsOutput.model_fields) == {"facts"}
    ops = plan_log_habit_ops(
        [LogHabit(fact="Eats prawn curry often", kind="habit")], ProfileState(), 3
    )
    assert all(isinstance(op, AddFact | RemoveFact) for op in ops)


async def test_a_loosened_limit_is_saved_pending_replacing_the_confirmed_one() -> None:
    confirmed = hard_entry(
        NutrientLimitValue(nutrient="sodium", amount=1500, unit="mg", period="per_day"),
        entry_id="e-1500",
    )
    draft = _draft(
        type="nutrient_limit",
        nutrient="sodium",
        amount=2300,
        unit="mg",
        period="per_day",
        evidence="2300 mg of sodium",
    )
    llm = _llm_returning(CuratorOutput(hard=[draft]))

    mocks, result = await _extract(
        llm,
        "my new limit is 2300 mg of sodium a day",
        hard_scores=[0.99],
        entries=[confirmed],
    )

    kwargs = mocks["add_entry"].await_args.kwargs
    assert (kwargs["state"], kwargs["replaces_id"]) == ("pending", "e-1500")
    assert len(result.asked) == 1
