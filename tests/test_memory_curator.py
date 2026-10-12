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
    build_curator_input,
    curate_turn,
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

    with (
        patch(
            "backend.agent.memory_curator.load_state", AsyncMock(return_value=_state())
        ),
        patch("backend.agent.memory_curator._curator_llm", llm),
        patch("backend.agent.memory_curator.apply_ops", apply),
    ):
        await curate_turn("user-1", "I'm vegetarian now", "Noted.")

    apply.assert_awaited_once_with(
        "user-1", [SetDietChip(chip="vegetarian", on=True)], "curator"
    )
    system, human = llm.ainvoke.call_args.args[0]
    assert "long-term food profile" in system.content
    assert "I'm vegetarian now" in human.content


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
