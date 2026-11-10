from __future__ import annotations

from backend.agent.memory import MemoryFact, RemoveFact, ReplaceFact
from backend.scripts.backfill_memory_profile import Decision, plan_backfill


def _legacy(*facts: str) -> list[MemoryFact]:
    return [
        MemoryFact(id=f"id-{f}", fact=f, kind="preference", source="inferred_from_chat")
        for f in facts
    ]


def test_plan_backfill_retypes_and_drops() -> None:
    legacy = _legacy("prefers oat milk", "had pizza on friday", "avoids red meat")
    ops = plan_backfill(
        [
            Decision(ref="m1", action="keep", kind="like", fact="Prefers oat milk"),
            Decision(ref="M2", action="drop"),
            Decision(ref="m3", action="keep", kind="restriction"),
        ],
        legacy,
    )

    assert ops == [
        ReplaceFact(id="id-prefers oat milk", fact="Prefers oat milk", kind="like"),
        RemoveFact(id="id-had pizza on friday"),
        # No rewrite given: the original wording is kept.
        ReplaceFact(
            id="id-avoids red meat", fact="avoids red meat", kind="restriction"
        ),
    ]


def test_plan_backfill_ignores_unknown_duplicate_and_incomplete_decisions() -> None:
    ops = plan_backfill(
        [
            Decision(ref="m9", action="drop"),
            Decision(ref="m1", action="keep"),
            Decision(ref="m1", action="drop"),
        ],
        _legacy("prefers oat milk"),
    )

    # m9 is unknown; the first m1 decision has no kind so it changes nothing,
    # and it still claims the handle, so the later drop is not applied.
    assert ops == []


def test_plan_backfill_never_drops_or_softens_an_allergy() -> None:
    # The model treated both allergies as duplicates of "avoids dairy" on a
    # real profile (2026-11-10 dry run); the guard keeps them as restrictions.
    legacy = _legacy(
        "has a milk allergy",
        "allergic to milk",
        "Lactose intolerant",
        "allergic to peanuts",
    )
    ops = plan_backfill(
        [
            Decision(ref="m1", action="drop"),
            Decision(ref="m2", action="keep", kind="dislike", fact="Avoids dairy"),
            Decision(ref="m3", action="keep", kind="restriction"),
            Decision(
                ref="m4", action="keep", kind="restriction", fact="Allergic to peanuts"
            ),
        ],
        legacy,
    )

    assert ops == [
        ReplaceFact(
            id="id-has a milk allergy", fact="has a milk allergy", kind="restriction"
        ),
        ReplaceFact(
            id="id-allergic to milk", fact="allergic to milk", kind="restriction"
        ),
        ReplaceFact(
            id="id-Lactose intolerant", fact="Lactose intolerant", kind="restriction"
        ),
        ReplaceFact(
            id="id-allergic to peanuts", fact="Allergic to peanuts", kind="restriction"
        ),
    ]
