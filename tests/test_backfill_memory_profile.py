from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agent.memory.facts import (
    AddRestriction,
    MemoryFact,
    RemoveFact,
    ReplaceFact,
)
from backend.db.models import UserMemory
from backend.scripts import backfill_memory_profile as backfill
from backend.scripts.backfill_memory_profile import (
    BackupRow,
    Decision,
    main,
    plan_backfill,
)


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
        # A restriction is a pending hard-profile entry; no rewrite given, so
        # the original wording is kept and the legacy row is left alone.
        AddRestriction(fact="avoids red meat"),
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
    # real profile (2026-11-10 dry run); the guard proposes them as restrictions.
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
        AddRestriction(fact="has a milk allergy"),
        AddRestriction(fact="allergic to milk"),
        AddRestriction(fact="Lactose intolerant"),
        AddRestriction(fact="Allergic to peanuts"),
    ]


def test_plan_backfill_keeps_the_original_when_a_rewrite_changes_meaning() -> None:
    # Seen on a real profile (2026-11-10): the rewrite lost the comparison.
    legacy = _legacy(
        "prefers tuna salad over standard or green goddess dressings",
        "prefers almond flour over regular flour",
        "has a milk allergy",
    )
    ops = plan_backfill(
        [
            Decision(
                ref="m1",
                action="keep",
                kind="like",
                fact="Prefers tuna salad dressings",
            ),
            Decision(
                ref="m2",
                action="keep",
                kind="like",
                fact="Prefers almond flour over regular flour",
            ),
            Decision(
                ref="m3", action="keep", kind="restriction", fact="Allergic to milk"
            ),
        ],
        legacy,
    )

    assert [op.fact for op in ops] == [
        "prefers tuna salad over standard or green goddess dressings",
        "Prefers almond flour over regular flour",
        # "allergy" is not in the rewrite, so the original wording stays.
        "has a milk allergy",
    ]


def test_apply_without_backup_is_refused() -> None:
    with pytest.raises(SystemExit):
        main(["--apply"])


async def test_backup_rows_writes_every_row_as_jsonl(tmp_path) -> None:
    now = datetime(2026, 11, 10, tzinfo=UTC)
    row = UserMemory(
        id="id-1",
        user_id="u1",
        fact="has a milk allergy",
        embedding=[0.5, 0.25],
        category="preference",
        confidence=0.8,
        source="inferred_from_chat",
        deleted_at=None,
        updated_at=now,
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [row]
    session = AsyncMock()
    session.execute.return_value = result
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = session
    path = tmp_path / "backup.jsonl"

    with patch.object(backfill, "get_session", return_value=factory):
        n = await backfill._backup_rows("u1", path)

    assert n == 1
    restored = BackupRow.model_validate_json(path.read_text().strip())
    assert restored.fact == "has a milk allergy"
    assert restored.embedding == [0.5, 0.25]
    assert restored.updated_at == now
