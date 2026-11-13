"""Curated per-user preference profile: the single owner of ``user_memory``.

The profile is a small, capped set of typed facts that is rendered in full
into every coaching prompt. Everything that changes it (the background
curator, the weekly log-habits job, the coach's remember/forget tools and
the /memory API) goes through :func:`apply_ops`, so the write rules live in
one place:

* Hard facts (restrictions and diet settings) are not stored here: they are
  entries of the hard profile (safety/profile.py). A write that adds one
  creates a *pending* entry that binds only once the patient confirms it; a
  write that would remove one only requests its retirement. The weekly job
  cannot touch them and the curator cannot switch a diet setting off.
  Legacy ``user_memory`` rows of kind ``restriction`` are ignored.
* A fact the user removed is kept as a tombstone and is not learned again
  until the user states it again.
* The profile is capped. On overflow the oldest inferred soft fact is
  evicted; facts the user stated are never evicted.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Literal

import logfire
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from backend.config import get_tunables
from backend.db.models import UserGoal, UserMemory
from backend.db.session import get_session
from backend.safety import profile
from backend.safety.matching import restriction_value
from backend.safety.profile import DIET_CHIPS
from backend.safety.tables import TablesUnavailable, load_tables

logger = logging.getLogger(__name__)

_TUNABLES = get_tunables()

FactKind = Literal["dislike", "like", "habit", "context"]
FactSource = Literal["stated", "inferred_from_chat", "inferred_from_logs"]
Actor = Literal["user", "curator", "weekly"]

# Kind on rows written before migration 018, until the backfill re-types them.
LEGACY_KIND = "preference"

MAX_FACT_CHARS = 200

_SOURCE_FOR: dict[str, str] = {
    "user": "stated",
    "curator": "inferred_from_chat",
    "weekly": "inferred_from_logs",
}
# Kinds that may be evicted when the profile is full.
_SOFT_KINDS = frozenset({"like", "habit", "context", LEGACY_KIND})
_KIND_ORDER = ("dislike", "like", "habit", "context", LEGACY_KIND)
_KIND_HEADINGS: dict[str, str] = {
    "dislike": "Dislikes (avoid)",
    "like": "Likes",
    "habit": "Habits",
    "context": "Context",
    LEGACY_KIND: "Other noted preferences",
}
_PROFILE_HEADER = "Long-term profile of this user:"


class MemoryFact(BaseModel):
    """One live profile fact, as read by the coach, curators and the API."""

    id: str
    fact: str
    kind: str
    source: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(extra="forbid")


class AddFact(BaseModel):
    """Store a new fact."""

    op: Literal["add"] = "add"
    fact: str = Field(min_length=1, max_length=MAX_FACT_CHARS)
    kind: FactKind

    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="P(lasting fact) from the GLiDE judgment, when there is one",
    )

    model_config = ConfigDict(extra="forbid")


class ReplaceFact(BaseModel):
    """Rewrite an existing fact (update, correction or merge)."""

    op: Literal["replace"] = "replace"
    id: str
    fact: str = Field(min_length=1, max_length=MAX_FACT_CHARS)
    kind: FactKind

    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="P(lasting fact) from the GLiDE judgment, when there is one",
    )

    model_config = ConfigDict(extra="forbid")


class RemoveFact(BaseModel):
    """Drop an existing fact."""

    op: Literal["remove"] = "remove"
    id: str

    model_config = ConfigDict(extra="forbid")


class SetDietChip(BaseModel):
    """Ask for one diet setting to be switched on or off (a hard-profile entry)."""

    op: Literal["set_diet_chip"] = "set_diet_chip"
    chip: str
    on: bool

    model_config = ConfigDict(extra="forbid")


class AddRestriction(BaseModel):
    """Propose a hard restriction (an allergy or a food the user never eats)."""

    op: Literal["add_restriction"] = "add_restriction"
    fact: str = Field(min_length=1, max_length=MAX_FACT_CHARS)

    model_config = ConfigDict(extra="forbid")


MemoryOp = Annotated[
    AddFact | ReplaceFact | RemoveFact | SetDietChip | AddRestriction,
    Field(discriminator="op"),
]
HardOp = SetDietChip | AddRestriction

PENDING_ADD = "awaiting the user's confirmation"
PENDING_REMOVAL = "removal awaiting the user's confirmation"


class OpResult(BaseModel):
    """What happened to one requested op."""

    op: MemoryOp
    applied: bool
    reason: str = ""

    model_config = ConfigDict(extra="forbid")


class ApplyOutcome(BaseModel):
    """Result of one :func:`apply_ops` batch."""

    results: list[OpResult] = []
    evicted: list[str] = []

    model_config = ConfigDict(extra="forbid")

    @property
    def n_applied(self) -> int:
        """Number of ops that changed (or confirmed) the profile."""
        return sum(1 for r in self.results if r.applied)


class ProfileState(BaseModel):
    """Everything a curator needs to see before proposing ops."""

    facts: list[MemoryFact] = []
    tombstones: list[str] = []
    diet_chips: list[str] = []

    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class ProfileLimits:
    """Caps applied by :func:`plan_ops`."""

    max_facts: int
    max_chars: int
    max_tombstones: int

    @classmethod
    def from_tunables(cls) -> ProfileLimits:
        """Read the caps from tunables.yaml."""
        cfg = _TUNABLES.memory
        return cls(
            max_facts=cfg.profile_max_facts,
            max_chars=cfg.profile_max_chars,
            max_tombstones=cfg.profile_max_tombstones,
        )


@dataclass
class _Plan:
    """Row-level changes computed by :func:`plan_ops`, not yet persisted."""

    results: list[OpResult] = field(default_factory=list)
    added: list[UserMemory] = field(default_factory=list)
    deleted: list[UserMemory] = field(default_factory=list)
    evicted: list[str] = field(default_factory=list)


def profile_active(user_id: str) -> bool:
    """Whether this user is on the curated-profile path (flag or allowlist)."""
    cfg = _TUNABLES.memory
    return cfg.profile_enabled or user_id in cfg.profile_allowlist


def _clean(fact: str) -> str:
    """Collapse whitespace and drop a trailing full stop."""
    return re.sub(r"\s+", " ", fact).strip().rstrip(".").strip()


def normalize_fact(fact: str) -> str:
    """Key for exact-duplicate and tombstone matching."""
    return re.sub(r"[^a-z0-9]+", " ", fact.lower()).strip()


def _to_fact(row: UserMemory) -> MemoryFact:
    return MemoryFact(
        id=row.id,
        fact=row.fact,
        kind=row.category,
        source=row.source,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _sorted_facts(rows: list[UserMemory]) -> list[MemoryFact]:
    """Live rows as facts: by kind, then most recently updated first."""
    epoch = datetime.min.replace(tzinfo=UTC)
    live = [r for r in rows if r.deleted_at is None]
    live.sort(key=lambda r: r.updated_at or epoch, reverse=True)
    live.sort(
        key=lambda r: _KIND_ORDER.index(r.category) if r.category in _KIND_ORDER else 99
    )
    return [_to_fact(r) for r in live]


def plan_ops(
    user_id: str,
    rows: list[UserMemory],
    ops: list[MemoryOp],
    actor: Actor,
    *,
    now: datetime,
    limits: ProfileLimits,
) -> _Plan:
    """Apply ``ops`` to in-memory rows under the profile's write rules.

    Pure apart from mutating ``rows`` and its members, so it can be tested
    without a database. :func:`apply_ops` persists the returned plan.

    Args:
        user_id: Owner of the profile.
        rows: Every ``user_memory`` row of the user, tombstones included.
            Mutated: surviving rows are edited in place, new ones appended.
        ops: Requested operations, applied in order.
        actor: Who is asking; decides what is allowed (see module docstring).
        now: Timestamp for new rows, edits and tombstones.
        limits: Profile caps.

    Returns:
        Per-op results plus the rows to insert and delete, and evicted fact
        texts.
    """
    plan = _Plan()
    source = _SOURCE_FOR[actor]
    default_confidence = (
        1.0 if actor == "user" else _TUNABLES.memory.new_fact_confidence
    )

    def live() -> list[UserMemory]:
        return [r for r in rows if r.deleted_at is None]

    def find_live(fact_id: str) -> UserMemory | None:
        return next((r for r in live() if r.id == fact_id), None)

    def drop(row: UserMemory) -> None:
        rows.remove(row)
        if row in plan.added:
            plan.added.remove(row)
        else:
            plan.deleted.append(row)

    def over_cap() -> bool:
        current = live()
        return (
            len(current) > limits.max_facts
            or sum(len(r.fact) for r in current) > limits.max_chars
        )

    def make_room(keep: UserMemory) -> bool:
        """Evict oldest inferred soft facts until under the cap."""
        epoch = datetime.min.replace(tzinfo=UTC)
        victims = sorted(
            (
                r
                for r in live()
                if r is not keep and r.source != "stated" and r.category in _SOFT_KINDS
            ),
            key=lambda r: r.updated_at or epoch,
        )
        dropped: list[UserMemory] = []
        while over_cap() and victims:
            victim = victims.pop(0)
            victim.deleted_at = now  # provisional, so over_cap() sees it gone
            dropped.append(victim)
        if over_cap():
            for victim in dropped:
                victim.deleted_at = None
            return False
        for victim in dropped:
            victim.deleted_at = None
            plan.evicted.append(victim.fact)
            drop(victim)
        return True

    def reject(op: MemoryOp, reason: str) -> None:
        plan.results.append(OpResult(op=op, applied=False, reason=reason))

    def accept(op: MemoryOp, reason: str = "") -> None:
        plan.results.append(OpResult(op=op, applied=True, reason=reason))

    for op in ops:
        if isinstance(op, RemoveFact):
            row = find_live(op.id)
            if row is None:
                reject(op, "unknown fact id")
            elif actor == "user":
                row.deleted_at = now  # tombstone: do not learn it again
                accept(op)
            elif actor == "weekly" and row.source != "inferred_from_logs":
                reject(op, "the weekly job can only remove its own facts")
            else:
                drop(row)
                accept(op)
            continue

        fact = _clean(op.fact)
        key = normalize_fact(fact)
        confidence = default_confidence
        if actor != "user" and op.confidence is not None:
            confidence = op.confidence
        if not key:
            reject(op, "empty fact")
            continue

        target: UserMemory | None = None
        if isinstance(op, ReplaceFact):
            target = find_live(op.id)
            if target is None:
                reject(op, "unknown fact id")
                continue
            if actor == "weekly" and target.source != "inferred_from_logs":
                reject(op, "the weekly job can only change its own facts")
                continue

        tombstone = next(
            (
                r
                for r in rows
                if r.deleted_at is not None and normalize_fact(r.fact) == key
            ),
            None,
        )
        if tombstone is not None and actor != "user":
            reject(op, "the user removed this fact")
            continue
        twin = next(
            (r for r in live() if r is not target and normalize_fact(r.fact) == key),
            None,
        )

        if target is not None:
            if twin is not None:
                drop(target)
                accept(op, "merged into an existing fact")
                continue
            if tombstone is not None:
                drop(tombstone)
            target.fact = fact
            target.category = op.kind
            target.updated_at = now
            if actor == "user":
                target.source = "stated"
                target.confidence = confidence
            elif op.confidence is not None and target.source != "stated":
                target.confidence = confidence
            make_room(target)
            accept(op)
            continue

        if twin is not None:
            if actor == "user" and twin.source != "stated":
                twin.source = "stated"
                twin.confidence = confidence
                twin.updated_at = now
                accept(op, "already known; now marked as stated")
            else:
                reject(op, "already known")
            continue

        if tombstone is not None:
            # Explicit restatement by the user brings the fact back.
            new_row = tombstone
            new_row.deleted_at = None
            new_row.fact = fact
            new_row.category = op.kind
            new_row.source = source
            new_row.confidence = confidence
            new_row.updated_at = now
        else:
            new_row = UserMemory(
                id=str(uuid.uuid4()),
                user_id=user_id,
                fact=fact,
                category=op.kind,
                source=source,
                confidence=confidence,
                updated_at=now,
                deleted_at=None,
            )
            rows.append(new_row)
            plan.added.append(new_row)
        if not make_room(new_row):
            if actor != "user":
                drop(new_row)
                reject(op, "profile is full; merge or replace existing facts first")
                continue
            # The user's own additions are kept over the cap.
            accept(op, "saved over the cap")
            continue
        accept(op)

    epoch = datetime.min.replace(tzinfo=UTC)
    tombstones = sorted(
        (r for r in rows if r.deleted_at is not None),
        key=lambda r: r.deleted_at or epoch,
        reverse=True,
    )
    for stale in tombstones[limits.max_tombstones :]:
        drop(stale)
    return plan


def _rejected(op: MemoryOp, reason: str) -> OpResult:
    return OpResult(op=op, applied=False, reason=reason)


async def _propose_entry(
    user_id: str,
    op: HardOp,
    value: profile.EntryValue,
    label: str | None,
    actor: Actor,
) -> OpResult:
    """Add a pending hard entry unless an equal live one already exists."""
    live = await profile.load_hard_profile(user_id)
    twin = next((e for e in live if e.value == value), None)
    if twin is not None:
        reason = PENDING_ADD if twin.state == "pending" else "already on the profile"
        return OpResult(op=op, applied=twin.state == "pending", reason=reason)
    await profile.add_entry(
        user_id,
        value,
        source="patient" if actor == "user" else "inferred",
        state="pending",
        created_by="patient" if actor == "user" else "curator",
        label=label,
    )
    return OpResult(op=op, applied=True, reason=PENDING_ADD)


async def _apply_hard_op(user_id: str, op: HardOp, actor: Actor) -> OpResult:
    """Apply one hard op through the hard profile.

    Adds become pending entries; removals only request retirement (or deny a
    still-pending entry). Nothing here confirms or retires on its own.
    """
    if actor == "weekly":
        return _rejected(op, "the weekly job cannot change the hard profile")
    try:
        if isinstance(op, AddRestriction):
            value, label = restriction_value(_clean(op.fact), load_tables())
            return await _propose_entry(user_id, op, value, label, actor)
        if op.chip not in DIET_CHIPS:
            return _rejected(op, "unknown diet setting")
        value = profile.DietSettingValue(setting=op.chip)
        if op.on:
            return await _propose_entry(user_id, op, value, None, actor)
        if actor != "user":
            return _rejected(op, "only the user can switch a diet setting off")
        existing = next(
            (e for e in await profile.load_hard_profile(user_id) if e.value == value),
            None,
        )
        if existing is None:
            return OpResult(op=op, applied=True, reason="no change")
        if existing.state == "pending":
            await profile.deny(user_id, existing.id)
            return OpResult(op=op, applied=True, reason="no change")
        await profile.request_retirement(user_id, existing.id)
        return OpResult(op=op, applied=True, reason=PENDING_REMOVAL)
    except TablesUnavailable as exc:
        logger.error("clinical tables unavailable, hard op dropped: %s", exc)
        return _rejected(op, "the clinical tables are unavailable")
    except profile.ProfileFull:
        return _rejected(op, "the safety profile is full")
    except IntegrityError:
        return _rejected(op, "no user profile yet")


async def _apply_soft_ops(
    user_id: str, ops: list[MemoryOp], actor: Actor
) -> tuple[list[OpResult], list[str]]:
    """Apply soft-fact ops in one transaction under a per-user advisory lock."""
    session_factory = get_session()
    async with session_factory() as session:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": f"user_memory:{user_id}"},
        )
        goal = await session.get(UserGoal, user_id)
        if goal is None:
            return [_rejected(op, "no user profile yet") for op in ops], []
        rows = list(
            (
                await session.execute(
                    select(UserMemory).where(
                        UserMemory.user_id == user_id,
                        UserMemory.category != "restriction",
                    )
                )
            )
            .scalars()
            .all()
        )
        plan = plan_ops(
            user_id,
            rows,
            ops,
            actor,
            now=datetime.now(UTC),
            limits=ProfileLimits.from_tunables(),
        )
        for row in plan.added:
            session.add(row)
        for row in plan.deleted:
            await session.delete(row)
        await session.commit()
    return plan.results, plan.evicted


async def apply_ops(user_id: str, ops: list[MemoryOp], actor: Actor) -> ApplyOutcome:
    """Apply profile operations for one user.

    Soft-fact ops run in a single transaction under a per-user advisory lock,
    so concurrent batches for the same user (two curator tasks, or a curator
    and a tool call) run one after another. Hard ops (diet settings and
    restrictions) go through the hard profile as pending entries.

    Args:
        user_id: Supabase Auth UUID.
        ops: Operations to apply, in order.
        actor: "user" for explicit requests (coach tools, API); "curator"
            for the per-turn background curator; "weekly" for the
            log-habits job.

    Returns:
        Per-op results, in the order requested, and the texts of any evicted
        facts. Every op is rejected when the user has no ``user_goal`` row.
    """
    if not ops:
        return ApplyOutcome()
    with logfire.span("memory.apply_ops", actor=actor, n_ops=len(ops)) as span:
        soft = [op for op in ops if not isinstance(op, SetDietChip | AddRestriction)]
        soft_results, evicted = (
            await _apply_soft_ops(user_id, soft, actor) if soft else ([], [])
        )
        soft_iter = iter(soft_results)
        results: list[OpResult] = []
        for op in ops:
            if isinstance(op, SetDietChip | AddRestriction):
                results.append(await _apply_hard_op(user_id, op, actor))
            else:
                results.append(next(soft_iter))
        outcome = ApplyOutcome(results=results, evicted=evicted)
        span.set_attribute("n_applied", outcome.n_applied)
        span.set_attribute("n_evicted", len(outcome.evicted))
    return outcome


async def load_state(user_id: str) -> ProfileState:
    """Read the live facts, tombstones and diet settings for one user.

    Args:
        user_id: Supabase Auth UUID.

    Returns:
        The profile state; empty when the user has no rows.
    """
    session_factory = get_session()
    async with session_factory() as session:
        rows = list(
            (
                await session.execute(
                    select(UserMemory).where(
                        UserMemory.user_id == user_id,
                        UserMemory.category != "restriction",
                    )
                )
            )
            .scalars()
            .all()
        )
    return ProfileState(
        facts=_sorted_facts(rows),
        tombstones=[r.fact for r in rows if r.deleted_at is not None],
        diet_chips=profile.active_diet_settings(
            await profile.load_hard_profile(user_id)
        ),
    )


async def load_profile(user_id: str) -> list[MemoryFact]:
    """Read the user's live soft facts: one indexed query, no embedding call.

    Args:
        user_id: Supabase Auth UUID.

    Returns:
        Live facts ordered by kind, then most recently updated first.
    """
    session_factory = get_session()
    async with session_factory() as session:
        stmt = select(UserMemory).where(
            UserMemory.user_id == user_id,
            UserMemory.deleted_at.is_(None),
            UserMemory.category != "restriction",
        )
        rows = list((await session.execute(stmt)).scalars().all())
    return _sorted_facts(rows)


def label_facts(facts: list[MemoryFact]) -> list[tuple[str, MemoryFact]]:
    """Pair each fact with a short handle ("m1", "m2", ...) for LLM prompts.

    Models copy short handles more reliably than UUIDs; callers map the
    handle back to ``fact.id`` before building ops.
    """
    return [(f"m{i}", fact) for i, fact in enumerate(facts, start=1)]


def render_profile_block(
    facts: list[MemoryFact],
    staples: dict[str, list[str]] | None = None,
    *,
    max_chars: int | None = None,
) -> str:
    """Render the soft profile as the coach's prompt block.

    Kinds are added while the block stays within ``max_chars``, so the prompt
    is bounded even if the table is not. The staples line is bounded by its
    producer (agent/tools/history.py get_staple_foods). Hard facts are
    rendered separately by ``safety.profile.render_block``.

    Args:
        facts: Live facts, as returned by :func:`load_profile`.
        staples: Foods the user logs often, by meal type (soft signal).
        max_chars: Budget for the block; defaults to ``profile_max_chars``.

    Returns:
        The block, or "" when there is nothing to say.
    """
    budget = max_chars or _TUNABLES.memory.profile_max_chars
    lines: list[str] = []
    used = 0
    for kind in _KIND_ORDER:
        kept: list[str] = []
        for fact in (f.fact for f in facts if f.kind == kind):
            if used + len(fact) > budget:
                break
            kept.append(fact)
            used += len(fact)
        if kept:
            lines.append(f"- {_KIND_HEADINGS[kind]}: " + "; ".join(kept))

    if staples:
        parts = [
            f"{meal_type}: {', '.join(foods)}"
            for meal_type, foods in staples.items()
            if foods
        ]
        if parts:
            lines.append(
                "- Often eats, from their logs (soft signal): " + "; ".join(parts)
            )

    if not lines:
        return ""
    return "\n".join([_PROFILE_HEADER, *lines])


__all__ = [
    "DIET_CHIPS",
    "LEGACY_KIND",
    "MAX_FACT_CHARS",
    "PENDING_ADD",
    "PENDING_REMOVAL",
    "Actor",
    "AddFact",
    "AddRestriction",
    "ApplyOutcome",
    "FactKind",
    "MemoryFact",
    "MemoryOp",
    "normalize_fact",
    "OpResult",
    "ProfileLimits",
    "ProfileState",
    "RemoveFact",
    "ReplaceFact",
    "SetDietChip",
    "apply_ops",
    "label_facts",
    "load_profile",
    "load_state",
    "plan_ops",
    "profile_active",
    "render_profile_block",
]
