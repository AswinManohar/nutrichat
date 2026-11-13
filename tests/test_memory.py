from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import TypeAdapter, ValidationError

from backend.agent.memory import (
    PENDING_ADD,
    PENDING_REMOVAL,
    AddFact,
    AddRestriction,
    MemoryFact,
    MemoryOp,
    ProfileLimits,
    RemoveFact,
    ReplaceFact,
    SetDietChip,
    label_facts,
    plan_ops,
    render_profile_block,
)
from backend.db.models import UserMemory

USER = "11111111-1111-1111-1111-111111111111"
NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
LIMITS = ProfileLimits(max_facts=40, max_chars=1500, max_tombstones=50)


def _row(
    fact: str,
    kind: str = "like",
    source: str = "inferred_from_chat",
    *,
    age_days: int = 1,
    deleted: bool = False,
) -> UserMemory:
    return UserMemory(
        id=f"id-{fact}",
        user_id=USER,
        fact=fact,
        category=kind,
        source=source,
        confidence=0.8,
        updated_at=NOW - timedelta(days=age_days),
        deleted_at=NOW - timedelta(days=age_days) if deleted else None,
    )


def _plan(rows, ops, actor, *, limits=LIMITS):
    return plan_ops(USER, rows, ops, actor, now=NOW, limits=limits)


def _live(rows) -> list[str]:
    return [r.fact for r in rows if r.deleted_at is None]


# --- add ---------------------------------------------------------------------


def test_add_creates_row_with_actor_source() -> None:
    rows: list[UserMemory] = []
    plan = _plan(rows, [AddFact(fact="Prefers oat milk. ", kind="like")], "curator")

    assert plan.results[0].applied
    (row,) = plan.added
    assert row.fact == "Prefers oat milk"
    assert (row.category, row.source, row.user_id) == (
        "like",
        "inferred_from_chat",
        USER,
    )


def test_add_duplicate_is_rejected_ignoring_case_and_punctuation() -> None:
    rows = [_row("Hates mushrooms", "dislike")]
    plan = _plan(rows, [AddFact(fact="hates  mushrooms!", kind="dislike")], "curator")

    assert not plan.results[0].applied
    assert plan.added == []


def test_user_restating_inferred_fact_marks_it_stated() -> None:
    rows = [_row("Hates mushrooms", "dislike")]
    plan = _plan(rows, [AddFact(fact="hates mushrooms", kind="dislike")], "user")

    assert plan.results[0].applied
    assert rows[0].source == "stated"
    assert plan.added == []


# --- tighten-only ------------------------------------------------------------


def test_curator_can_replace_a_contradicted_soft_fact() -> None:
    rows = [_row("Loves chicken", "like", "stated")]
    plan = _plan(
        rows,
        [ReplaceFact(id="id-Loves chicken", fact="No longer eats meat", kind="habit")],
        "curator",
    )

    assert plan.results[0].applied
    assert (rows[0].fact, rows[0].category) == ("No longer eats meat", "habit")
    # A fact the user stated keeps that standing when the curator rewrites it.
    assert rows[0].source == "stated"


# --- remove and tombstones ---------------------------------------------------


def test_user_remove_leaves_a_tombstone() -> None:
    rows = [_row("Likes spicy food")]
    plan = _plan(rows, [RemoveFact(id="id-Likes spicy food")], "user")

    assert plan.results[0].applied
    assert rows[0].deleted_at == NOW
    assert plan.deleted == []


def test_curator_remove_is_a_hard_delete() -> None:
    rows = [_row("Likes spicy food")]
    plan = _plan(rows, [RemoveFact(id="id-Likes spicy food")], "curator")

    assert plan.results[0].applied
    assert rows == []
    assert [r.fact for r in plan.deleted] == ["Likes spicy food"]


@pytest.mark.parametrize("actor", ["curator", "weekly"])
def test_tombstoned_fact_is_not_learned_again(actor) -> None:
    rows = [_row("Likes spicy food", deleted=True)]
    plan = _plan(rows, [AddFact(fact="likes spicy food", kind="like")], actor)

    assert not plan.results[0].applied
    assert _live(rows) == []


def test_user_restating_a_tombstoned_fact_revives_it() -> None:
    rows = [_row("Likes spicy food", deleted=True)]
    plan = _plan(rows, [AddFact(fact="Likes spicy food", kind="like")], "user")

    assert plan.results[0].applied
    assert _live(rows) == ["Likes spicy food"]
    assert rows[0].source == "stated"
    # Revived in place: no second row for the same fact.
    assert plan.added == []


def test_old_tombstones_are_purged_beyond_the_limit() -> None:
    rows = [_row(f"t{i}", age_days=i + 1, deleted=True) for i in range(4)]
    limits = ProfileLimits(max_facts=40, max_chars=1500, max_tombstones=2)
    plan = _plan(
        rows, [AddFact(fact="Likes dal", kind="like")], "curator", limits=limits
    )

    assert sorted(r.fact for r in plan.deleted) == ["t2", "t3"]


def test_weekly_job_only_touches_its_own_facts() -> None:
    rows = [
        _row("From chat", source="inferred_from_chat"),
        _row("From logs", source="inferred_from_logs"),
    ]
    plan = _plan(
        rows, [RemoveFact(id="id-From chat"), RemoveFact(id="id-From logs")], "weekly"
    )

    assert [r.applied for r in plan.results] == [False, True]
    assert _live(rows) == ["From chat"]


def test_unknown_id_is_rejected() -> None:
    plan = _plan([], [RemoveFact(id="nope")], "user")

    assert not plan.results[0].applied


# --- cap ---------------------------------------------------------------------


def test_overflow_evicts_oldest_inferred_soft_fact_only() -> None:
    rows = [
        _row("Hates peanuts", "dislike", "inferred_from_chat", age_days=90),
        _row("Stated like", "like", "stated", age_days=80),
        _row("Old habit", "habit", age_days=70),
        _row("Newer habit", "habit", age_days=5),
    ]
    limits = ProfileLimits(max_facts=4, max_chars=1500, max_tombstones=50)
    plan = _plan(
        rows, [AddFact(fact="Likes dal", kind="like")], "curator", limits=limits
    )

    assert plan.results[0].applied
    assert plan.evicted == ["Old habit"]
    assert sorted(_live(rows)) == [
        "Hates peanuts",
        "Likes dal",
        "Newer habit",
        "Stated like",
    ]


def test_curator_add_is_rejected_when_nothing_can_be_evicted() -> None:
    rows = [
        _row("Hates peanuts", "dislike", "stated"),
        _row("Stated like", "like", "stated"),
    ]
    limits = ProfileLimits(max_facts=2, max_chars=1500, max_tombstones=50)
    plan = _plan(
        rows, [AddFact(fact="Likes dal", kind="like")], "curator", limits=limits
    )

    assert not plan.results[0].applied
    assert plan.added == [] and plan.evicted == [] and plan.deleted == []
    assert len(rows) == 2


def test_explicit_remember_succeeds_even_when_full() -> None:
    rows = [
        _row("Hates peanuts", "dislike", "stated"),
        _row("Stated like", "like", "stated"),
    ]
    limits = ProfileLimits(max_facts=2, max_chars=1500, max_tombstones=50)
    plan = _plan(
        rows, [AddFact(fact="Hates okra", kind="dislike")], "user", limits=limits
    )

    assert plan.results[0].applied
    assert len(plan.added) == 1


def test_char_cap_triggers_eviction() -> None:
    rows = [_row("x" * 60, "habit", age_days=9), _row("y" * 60, "habit", age_days=2)]
    limits = ProfileLimits(max_facts=40, max_chars=150, max_tombstones=50)
    plan = _plan(rows, [AddFact(fact="z" * 60, kind="like")], "curator", limits=limits)

    assert plan.results[0].applied
    assert plan.evicted == ["x" * 60]


# --- replace -----------------------------------------------------------------


def test_replace_into_existing_fact_merges() -> None:
    rows = [_row("Likes dal"), _row("Enjoys lentils")]
    plan = _plan(
        rows,
        [ReplaceFact(id="id-Enjoys lentils", fact="likes dal", kind="like")],
        "curator",
    )

    assert plan.results[0].applied
    assert _live(rows) == ["Likes dal"]


def test_ops_in_one_batch_see_each_other() -> None:
    rows: list[UserMemory] = []
    plan = _plan(
        rows,
        [
            AddFact(fact="Likes dal", kind="like"),
            AddFact(fact="likes dal", kind="like"),
        ],
        "curator",
    )

    assert [r.applied for r in plan.results] == [True, False]
    assert len(plan.added) == 1


# --- schema ------------------------------------------------------------------


def test_memory_op_union_parses_by_discriminator() -> None:
    adapter = TypeAdapter(list[MemoryOp])
    ops = adapter.validate_python(
        [
            {"op": "add", "fact": "Likes dal", "kind": "like"},
            {"op": "remove", "id": "abc"},
            {"op": "set_diet_chip", "chip": "vegan", "on": True},
        ]
    )

    assert [type(o) for o in ops] == [AddFact, RemoveFact, SetDietChip]
    with pytest.raises(ValidationError):
        adapter.validate_python([{"op": "add", "fact": "x", "kind": "preference"}])


# --- render ------------------------------------------------------------------


def _fact(text: str, kind: str) -> MemoryFact:
    return MemoryFact(id=text, fact=text, kind=kind, source="stated")


def test_render_empty_profile_is_empty_string() -> None:
    assert render_profile_block([], None) == ""


def test_render_orders_soft_kinds_and_adds_staples() -> None:
    block = render_profile_block(
        [
            _fact("Usually skips breakfast", "habit"),
            _fact("Mushrooms", "dislike"),
        ],
        {"breakfast": ["oats", "banana"], "dinner": []},
    )
    lines = block.splitlines()

    assert lines[1] == "- Dislikes (avoid): Mushrooms"
    assert lines[2] == "- Habits: Usually skips breakfast"
    assert lines[3].endswith("breakfast: oats, banana")
    assert "Diet settings" not in block


def test_render_truncates_soft_facts_to_the_budget() -> None:
    facts = [_fact(f"like {i} " + "l" * 40, "like") for i in range(10)]
    block = render_profile_block(facts, None, max_chars=350)

    assert "like 0 " in block
    assert "like 9 " not in block


def test_label_facts() -> None:
    facts = [_fact("a", "like"), _fact("b", "like")]

    assert [label for label, _ in label_facts(facts)] == ["m1", "m2"]


def test_memory_op_union_parses_restriction() -> None:
    op = TypeAdapter(MemoryOp).validate_python(
        {"op": "add_restriction", "fact": "Peanut allergy"}
    )

    assert isinstance(op, AddRestriction)


def test_restriction_is_no_longer_a_soft_kind() -> None:
    with pytest.raises(ValidationError):
        AddFact(fact="Peanut allergy", kind="restriction")


# --- against Postgres --------------------------------------------------------


async def test_apply_ops_round_trip_against_live_postgres() -> None:
    """Requires DATABASE_URL with migration 019 applied."""
    from tests.conftest import DATABASE_URL_PRESET

    if not DATABASE_URL_PRESET:
        pytest.skip("DATABASE_URL not set")

    import asyncio
    import uuid

    from sqlalchemy import delete

    from backend.agent.memory import apply_ops, load_profile, load_state
    from backend.db.models import UserGoal
    from backend.db.session import dispose_engine, get_session
    from backend.safety import profile

    user_id = str(uuid.uuid4())
    session_factory = get_session()
    async with session_factory() as session:
        session.add(UserGoal(user_id=user_id))
        await session.commit()
    await profile.add_entry(
        user_id,
        profile.DietSettingValue(setting="high_protein"),
        source="patient",
        state="confirmed",
        created_by="patient",
    )
    try:
        # No user_goal row: nothing is written, nothing raises.
        orphan = await apply_ops(
            str(uuid.uuid4()),
            [AddFact(fact="Likes dal", kind="like"), AddRestriction(fact="No pork")],
            "curator",
        )
        assert orphan.n_applied == 0

        # Two concurrent batches for one user serialize on the advisory lock.
        first, second = await asyncio.gather(
            apply_ops(
                user_id,
                [
                    AddRestriction(fact="Peanut allergy"),
                    AddFact(fact="Likes spicy food", kind="like"),
                    SetDietChip(chip="vegetarian", on=True),
                ],
                "curator",
            ),
            apply_ops(
                user_id, [AddFact(fact="Hates mushrooms", kind="dislike")], "user"
            ),
        )
        assert first.n_applied == 3 and second.n_applied == 1
        assert first.results[0].reason == PENDING_ADD

        # Hard facts are pending entries: they do not bind and the soft
        # profile does not carry them.
        state = await load_state(user_id)
        assert [f.fact for f in state.facts] == ["Hates mushrooms", "Likes spicy food"]
        assert state.diet_chips == ["high_protein"]
        live = await profile.load_hard_profile(user_id)
        pending = {
            (e.type, e.source, e.created_by) for e in live if e.state == "pending"
        }
        assert pending == {
            ("allergy", "inferred", "curator"),
            ("diet_setting", "inferred", "curator"),
        }
        peanut = next(e for e in live if e.type == "allergy")
        assert peanut.value == profile.AllergyValue(allergen_group="peanut")

        # Restating a pending hard fact adds nothing.
        again = await apply_ops(user_id, [AddRestriction(fact="peanuts")], "curator")
        assert again.results[0].reason == PENDING_ADD
        assert len(await profile.load_hard_profile(user_id)) == len(live)

        # The curator cannot re-learn a deleted soft fact or switch a diet
        # setting off; the weekly job cannot touch the hard profile at all.
        spicy = next(f for f in state.facts if f.fact == "Likes spicy food")
        await apply_ops(user_id, [RemoveFact(id=spicy.id)], "user")
        blocked = await apply_ops(
            user_id,
            [
                AddFact(fact="likes spicy food", kind="like"),
                SetDietChip(chip="high_protein", on=False),
            ],
            "curator",
        )
        assert blocked.n_applied == 0
        weekly = await apply_ops(user_id, [AddRestriction(fact="No pork")], "weekly")
        assert weekly.n_applied == 0

        # The user asking to switch a confirmed diet setting off only requests
        # retirement: it keeps binding.
        off = await apply_ops(
            user_id, [SetDietChip(chip="high_protein", on=False)], "user"
        )
        assert off.results[0].reason == PENDING_REMOVAL
        assert (await load_state(user_id)).diet_chips == ["high_protein"]
        requested = next(
            e
            for e in await profile.load_hard_profile(user_id)
            if e.type == "diet_setting" and e.state == "confirmed"
        )
        assert requested.retire_requested_at is not None

        # Legacy restriction rows are ignored everywhere.
        async with session_factory() as session:
            session.add(
                UserMemory(
                    user_id=user_id,
                    fact="Old allergy",
                    category="restriction",
                    source="stated",
                    confidence=1.0,
                )
            )
            await session.commit()
        assert [f.fact for f in await load_profile(user_id)] == ["Hates mushrooms"]
        assert (await load_state(user_id)).tombstones == ["Likes spicy food"]
    finally:
        async with session_factory() as session:
            # user_memory and profile_entry rows go with the user_goal row.
            await session.execute(delete(UserGoal).where(UserGoal.user_id == user_id))
            await session.commit()
        await dispose_engine()


def test_curator_add_stores_the_judged_confidence() -> None:
    rows: list[UserMemory] = []
    _plan(rows, [AddFact(fact="Likes dal", kind="like", confidence=0.91)], "curator")
    assert rows[0].confidence == 0.91


def test_user_add_ignores_a_supplied_confidence() -> None:
    rows: list[UserMemory] = []
    _plan(rows, [AddFact(fact="Likes dal", kind="like", confidence=0.2)], "user")
    assert rows[0].confidence == 1.0
