from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from backend.agent.memory import (
    AddFact,
    ApplyOutcome,
    MemoryFact,
    ProfileState,
    RemoveFact,
    ReplaceFact,
    SetDietChip,
)
from backend.agent.memory_curator import (
    CuratorOp,
    CuratorOutput,
    LogHabit,
    LogHabitsOutput,
    build_curator_input,
    build_log_habits_input,
    curate_turn,
    infer_log_habits,
    plan_log_habit_ops,
    to_memory_ops,
)


def _state() -> ProfileState:
    return ProfileState(
        facts=[
            MemoryFact(
                id="id-a",
                fact="Allergic to peanuts",
                kind="restriction",
                source="stated",
            ),
            MemoryFact(id="id-b", fact="Loves chicken", kind="like", source="stated"),
        ],
        tombstones=["Likes spicy food"],
        diet_chips=["high_protein"],
    )


def test_build_curator_input_lists_handles_settings_and_removed_facts() -> None:
    text = build_curator_input(_state(), "I'm vegetarian now", "Noted.")

    assert "m1 [restriction] Allergic to peanuts" in text
    assert "m2 [like] Loves chicken" in text
    assert "Diet settings on: high_protein" in text
    assert "vegetarian" in text.split("Diet settings available:")[1].splitlines()[0]
    assert (
        "high_protein" not in text.split("Diet settings available:")[1].splitlines()[0]
    )
    assert "- Likes spicy food" in text
    assert "User: I'm vegetarian now\nAssistant: Noted." in text
    assert "% full" in text


def test_build_curator_input_empty_profile() -> None:
    text = build_curator_input(ProfileState(), "hi", "hello")

    assert "Current profile (0% full):\n(empty)" in text
    assert "Removed by the user:\n(none)" in text


def test_to_memory_ops_maps_handles_to_ids() -> None:
    ops = to_memory_ops(
        [
            CuratorOp(action="add", fact=" Dislikes okra ", kind="dislike"),
            CuratorOp(
                action="replace", ref="M2", fact="No longer eats meat", kind="habit"
            ),
            CuratorOp(action="remove", ref="m2"),
            CuratorOp(action="set_diet", chip=" Vegetarian "),
        ],
        _state(),
    )

    assert ops == [
        AddFact(fact="Dislikes okra", kind="dislike"),
        ReplaceFact(id="id-b", fact="No longer eats meat", kind="habit"),
        RemoveFact(id="id-b"),
        SetDietChip(chip="vegetarian", on=True),
    ]


def test_to_memory_ops_drops_malformed_proposals() -> None:
    ops = to_memory_ops(
        [
            CuratorOp(action="add", fact="No kind given"),
            CuratorOp(action="add", kind="like"),
            CuratorOp(action="replace", ref="m9", fact="Unknown handle", kind="like"),
            CuratorOp(action="remove"),
            CuratorOp(action="set_diet"),
        ],
        _state(),
    )

    assert ops == []


def test_to_memory_ops_truncates_overlong_facts() -> None:
    (op,) = to_memory_ops(
        [CuratorOp(action="add", fact="x" * 500, kind="like")], ProfileState()
    )

    assert len(op.fact) == 200


def _llm_returning(output: CuratorOutput) -> MagicMock:
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=output)
    return llm


async def test_curate_turn_applies_ops_as_curator() -> None:
    llm = _llm_returning(
        CuratorOutput(ops=[CuratorOp(action="set_diet", chip="vegetarian")])
    )
    apply = AsyncMock(return_value=ApplyOutcome())
    judge = AsyncMock(return_value=[0.95])

    with (
        patch(
            "backend.agent.memory_curator.load_state", AsyncMock(return_value=_state())
        ),
        patch("backend.agent.memory_curator._curator_llm", llm),
        patch("backend.agent.memory_curator.judge_ops", judge),
        patch("backend.agent.memory_curator.apply_ops", apply),
    ):
        await curate_turn("user-1", "I'm vegetarian now", "Noted.")

    judge.assert_awaited_once_with(
        "I'm vegetarian now", [SetDietChip(chip="vegetarian", on=True)], _state()
    )

    apply.assert_awaited_once_with(
        "user-1", [SetDietChip(chip="vegetarian", on=True)], "curator"
    )
    system, human = llm.ainvoke.call_args.args[0]
    assert "long-term food profile" in system.content
    assert "I'm vegetarian now" in human.content


async def test_curate_turn_saves_only_what_jev_scores_high_enough() -> None:
    llm = _llm_returning(
        CuratorOutput(
            ops=[
                CuratorOp(action="add", fact="Allergic to peanuts", kind="restriction"),
                CuratorOp(action="add", fact="Likes salad", kind="like"),
            ]
        )
    )
    apply = AsyncMock(return_value=ApplyOutcome())

    with (
        patch(
            "backend.agent.memory_curator.load_state", AsyncMock(return_value=_state())
        ),
        patch("backend.agent.memory_curator._curator_llm", llm),
        patch(
            "backend.agent.memory_curator.judge_ops",
            AsyncMock(return_value=[0.97, 0.08]),
        ),
        patch("backend.agent.memory_curator.apply_ops", apply),
    ):
        await curate_turn("user-1", "salad, no peanuts, I'm allergic", "Logged.")

    apply.assert_awaited_once_with(
        "user-1",
        [AddFact(fact="Allergic to peanuts", kind="restriction", confidence=0.97)],
        "curator",
    )


async def test_curate_turn_all_candidates_scored_low_skips_the_write() -> None:
    llm = _llm_returning(
        CuratorOutput(ops=[CuratorOp(action="add", fact="Likes salad", kind="like")])
    )
    apply = AsyncMock()

    with (
        patch(
            "backend.agent.memory_curator.load_state", AsyncMock(return_value=_state())
        ),
        patch("backend.agent.memory_curator._curator_llm", llm),
        patch("backend.agent.memory_curator.judge_ops", AsyncMock(return_value=[0.1])),
        patch("backend.agent.memory_curator.apply_ops", apply),
    ):
        outcome = await curate_turn("user-1", "had a salad", "Logged.")

    apply.assert_not_awaited()
    assert outcome.results == []


async def test_curate_turn_nothing_to_store_skips_the_write() -> None:
    apply = AsyncMock()

    with (
        patch(
            "backend.agent.memory_curator.load_state", AsyncMock(return_value=_state())
        ),
        patch(
            "backend.agent.memory_curator._curator_llm", _llm_returning(CuratorOutput())
        ),
        patch("backend.agent.memory_curator.apply_ops", apply),
    ):
        outcome = await curate_turn("user-1", "log 2 eggs", "Logged 140 kcal")

    apply.assert_not_awaited()
    assert outcome.results == []


async def test_curate_turn_blank_input_makes_no_calls() -> None:
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
