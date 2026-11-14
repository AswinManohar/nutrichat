"""Curators: keep a user's preference profile and hard profile current.

* :func:`extract_turn` runs once per conversation turn. One structured-output
  call sees the profile and drafts soft-fact operations (add / replace /
  remove), typed hard-fact candidates (allergy, diagnosis, medication,
  physical limitation, nutrient limit, diet setting, food exclusion) and
  retirements of confirmed hard entries. GLiDE scores each candidate
  (agent/memory_judge.py); the model's draft is never saved as is.
  On a coaching turn it runs inside the turn, concurrently with the query
  parse (agent/coaching.py); on a logging turn it runs in Celery after the
  reply (:func:`curate_turn`, workers/tasks.py).
* :func:`infer_log_habits` runs weekly per active logger and rewrites the
  few facts inferred from their meal logs. It can only produce soft facts.

A hard candidate must quote the patient's own words (``evidence``): one that
does not appear in the patient's message is discarded in code, so nothing the
assistant said or the logs showed can become a hard fact (spec 013 FR-023).
agent/memory.py apply_ops enforces what each soft write is allowed to do.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError

from backend import tracing
from backend.agent.aio import resolved
from backend.agent.intake.history import get_category_breakdown, get_staple_foods
from backend.agent.llm import FLASH_LITE_MODEL, make_llm
from backend.agent.memory.facts import (
    MAX_FACT_CHARS,
    AddFact,
    ApplyOutcome,
    MemoryOp,
    ProfileState,
    RemoveFact,
    ReplaceFact,
    apply_ops,
    label_facts,
    load_state,
    normalize_fact,
)
from backend.agent.memory.judge import (
    HardAdd,
    HardCandidate,
    HardDecision,
    HardRetire,
    judge_hard,
    judge_ops,
    select_hard_ops,
    select_ops,
)
from backend.config import get_tunables
from backend.safety import profile
from backend.safety.matching import allergen_group_for
from backend.safety.profile import (
    DIET_CHIPS,
    HardEntry,
    label_for,
    normalize_diet_key,
)
from backend.safety.tables import ClinicalTables, TablesUnavailable, load_tables

logger = logging.getLogger(__name__)

_TUNABLES = get_tunables()
# One prompt with soft and hard sections for every user.
_HARD_SYSTEM = _TUNABLES.prompts.profile_curator_hard_system
_CURATOR_SYSTEM = f"{_TUNABLES.prompts.profile_curator_system}\n\n{_HARD_SYSTEM}"
_LOG_HABITS_SYSTEM = _TUNABLES.prompts.log_habits_system
_LOG_SOURCE = "inferred_from_logs"

# Most drafts of each kind one turn may carry; bounds the GLiDE requests.
_MAX_DRAFTS = 8

CuratorKind = Literal[
    "dislike", "like", "cuisine", "budget", "cooking_time", "habit", "context"
]
HardType = Literal[
    "allergy",
    "diagnosis",
    "medication",
    "physical_limitation",
    "nutrient_limit",
    "diet_setting",
    "food_exclusion",
]


class CuratorOp(BaseModel):
    """One soft-fact operation proposed by the curator model.

    Flat on purpose: Gemini structured output handles one object with
    optional fields more reliably than a discriminated union. Converted to
    a typed MemoryOp by :func:`to_memory_ops`.
    """

    action: Literal["add", "replace", "remove"]
    ref: str | None = Field(
        default=None, description="Handle of an existing fact, e.g. m3"
    )
    fact: str | None = Field(default=None, description="Fact text for add/replace")
    kind: CuratorKind | None = Field(default=None, description="Kind for add/replace")

    model_config = ConfigDict(extra="forbid")


class HardDraft(BaseModel):
    """A hard fact the patient stated about themself, as the model drafts it.

    Flat for the same reason as :class:`CuratorOp`: only the fields of the
    chosen ``type`` are filled. Converted to a typed :class:`HardAdd` by
    :func:`to_hard_candidates`.
    """

    type: HardType
    label: str = Field(description="Short free-text name, e.g. 'Peanut allergy'")
    evidence: str = Field(description="The patient's exact words from their message")
    terms: list[str] | None = Field(
        default=None, description="allergy: each allergen; food_exclusion: the foods"
    )
    condition: str | None = Field(default=None, description="diagnosis")
    medication: str | None = Field(default=None, description="medication name")
    limitation: Literal["chewing", "swallowing", "grip", "standing_time"] | None = (
        Field(default=None, description="physical_limitation kind")
    )
    max_texture: str | None = None
    max_active_minutes: int | None = None
    nutrient: str | None = Field(default=None, description="nutrient_limit")
    amount: float | None = None
    unit: Literal["mg", "g", "ml"] | None = None
    period: Literal["per_meal", "per_day"] | None = None
    setting: str | None = Field(default=None, description="diet_setting chip")

    model_config = ConfigDict(extra="forbid")


class RetireDraft(BaseModel):
    """The patient says a confirmed hard entry (handle ``h1``...) no longer applies."""

    ref: str
    evidence: str = Field(description="The patient's exact words from their message")

    model_config = ConfigDict(extra="forbid")


class HardCuratorOutput(BaseModel):
    """Hard candidates for one conversation turn; empty for most turns."""

    hard: list[HardDraft] = Field(default_factory=list, max_length=_MAX_DRAFTS)
    retire: list[RetireDraft] = Field(default_factory=list, max_length=_MAX_DRAFTS)

    model_config = ConfigDict(extra="forbid")


class CuratorOutput(HardCuratorOutput):
    """Soft and hard candidates for one conversation turn."""

    ops: list[CuratorOp] = Field(default_factory=list, max_length=_MAX_DRAFTS)


_curator_llm = make_llm(FLASH_LITE_MODEL).with_structured_output(CuratorOutput)


def label_hard(entries: list[HardEntry]) -> list[tuple[str, HardEntry]]:
    """Handles ``h1``... for the confirmed entries a retirement may name."""
    return [
        (f"h{i}", e)
        for i, e in enumerate((e for e in entries if e.state == "confirmed"), 1)
    ]


def build_curator_input(
    state: ProfileState,
    user_input: str,
    agent_reply: str = "",
    entries: list[HardEntry] | None = None,
    tables: ClinicalTables | None = None,
) -> str:
    """Render the profile and the turn as the curator's user message.

    Args:
        state: Current profile state from ``memory.load_state``.
        user_input: The user's message this turn.
        agent_reply: The agent's reply this turn; empty when the extraction
            runs before the reply exists (coaching turns).
        entries: The patient's live hard entries.
        tables: Clinical tables, for labels and known condition keys.

    Returns:
        Prompt text listing facts by handle, the hard profile, removed facts,
        how full the profile is, and the turn.
    """
    cfg = _TUNABLES.memory
    used_chars = sum(len(f.fact) for f in state.facts)
    fill = max(
        len(state.facts) / cfg.profile_max_facts, used_chars / cfg.profile_max_chars
    )
    facts = "\n".join(
        f"{handle} [{fact.kind}] {fact.fact}"
        for handle, fact in label_facts(state.facts)
    )
    removed = "\n".join(f"- {t}" for t in state.tombstones)
    hard_lines: list[str] = []
    if tables is not None:
        handles = {e.id: h for h, e in label_hard(entries or [])}
        hard_lines = [
            f"{handles.get(e.id, '-')} [{e.state}] {label_for(e, tables)}"
            for e in entries or []
        ]
    conditions = ", ".join(tables.condition_limits.conditions) if tables else ""
    turn = f"User: {user_input}"
    if agent_reply:
        turn += f"\nAssistant: {agent_reply}"
    return "\n\n".join(
        [
            f"Current profile ({fill:.0%} full):\n{facts or '(empty)'}",
            "Hard profile (retire only handles h1...):\n"
            + ("\n".join(hard_lines) or "(empty)"),
            f"Known condition keys: {conditions or '(none)'}",
            f"Diet settings available: {', '.join(sorted(DIET_CHIPS))}",
            f"Removed by the user:\n{removed or '(none)'}",
            f"Conversation turn:\n{turn}",
        ]
    )


def to_memory_ops(proposed: list[CuratorOp], state: ProfileState) -> list[MemoryOp]:
    """Convert model output to typed soft ops, dropping malformed ones.

    Handles ("m3") are mapped back to fact ids. An op that is missing a
    required field or names an unknown handle is skipped: the model's
    output is a suggestion, and apply_ops is the authority.
    """
    by_handle = {handle: fact.id for handle, fact in label_facts(state.facts)}
    ops: list[MemoryOp] = []
    for item in proposed:
        fact = (item.fact or "").strip()[:MAX_FACT_CHARS]
        fact_id = by_handle.get((item.ref or "").strip().lower())
        if item.action == "add" and fact and item.kind:
            ops.append(AddFact(fact=fact, kind=item.kind))
        elif item.action == "replace" and fact_id and fact and item.kind:
            ops.append(ReplaceFact(id=fact_id, fact=fact, kind=item.kind))
        elif item.action == "remove" and fact_id:
            ops.append(RemoveFact(id=fact_id))
        else:
            logger.info("curator proposed an unusable op: %s", item.model_dump())
    return ops


def evidence_in(message: str, evidence: str) -> bool:
    """Whether ``evidence`` is a case-insensitive substring of ``message``.

    Whitespace runs count as one space, so a model that flattens a line break
    is not penalised. An empty quote never matches.
    """
    quote = " ".join(evidence.casefold().split())
    return bool(quote) and quote in " ".join(message.casefold().split())


def _drop_none(raw: dict) -> dict:
    return {k: v for k, v in raw.items() if v is not None}


def _values_for(
    draft: HardDraft, tables: ClinicalTables
) -> list[tuple[profile.EntryValue, str | None]]:
    """Typed values (with the label to store) for one draft; [] when invalid.

    An allergy draft with several allergens becomes one value each, so a
    group match on one cannot swallow the others.
    """
    terms = [t.strip() for t in draft.terms or [] if t.strip()]
    label = draft.label.strip() or None
    raws: list[tuple[dict, str | None]]
    if draft.type == "allergy":
        raws = []
        for term in terms:
            group = allergen_group_for(term, tables)
            raws.append(
                ({"allergen_group": group} if group else {"custom_terms": [term]}, None)
            )
    elif draft.type == "food_exclusion":
        raws = [({"terms": terms}, label)]
    elif draft.type == "diagnosis":
        raws = [({"condition": (draft.condition or "").strip().lower()}, None)]
    elif draft.type == "medication":
        raws = [({"name": (draft.medication or "").strip()}, None)]
    elif draft.type == "physical_limitation":
        raws = [
            (
                _drop_none(
                    {
                        "kind": draft.limitation,
                        "max_texture": draft.max_texture,
                        "max_active_minutes": draft.max_active_minutes,
                    }
                ),
                None,
            )
        ]
    elif draft.type == "nutrient_limit":
        raws = [
            (
                _drop_none(
                    {
                        "nutrient": (draft.nutrient or "").strip().lower(),
                        "amount": draft.amount,
                        "unit": draft.unit,
                        "period": draft.period,
                    }
                ),
                None,
            )
        ]
    else:
        setting = normalize_diet_key((draft.setting or "").strip().lower())
        raws = [({"setting": setting}, None)]
    values: list[tuple[profile.EntryValue, str | None]] = []
    for raw, keep_label in raws:
        try:
            values.append((profile.parse_value(draft.type, raw), keep_label))
        except ValueError:
            logger.info("curator drafted an invalid %s value", draft.type)
    return values


def to_hard_candidates(
    output: CuratorOutput,
    user_input: str,
    entries: list[HardEntry],
    tables: ClinicalTables,
) -> list[HardCandidate]:
    """Typed hard candidates from the model's drafts.

    Discards a draft whose ``evidence`` is not in the patient's message
    (FR-023), whose value does not fit its type, or whose retirement handle is
    unknown or names an unconfirmed entry. Repeated values collapse to one.

    Args:
        output: The curator's structured output.
        user_input: The patient's own message this turn; never the reply.
        entries: The patient's live hard entries.
        tables: Clinical tables, for allergen groups.

    Returns:
        Candidates ready for ``judge_hard``.
    """
    candidates: list[HardCandidate] = []
    seen: set[tuple[str, str]] = set()
    for draft in output.hard:
        if not evidence_in(user_input, draft.evidence):
            logger.info(
                "hard %s draft discarded: evidence not in the message", draft.type
            )
            continue
        for value, label in _values_for(draft, tables):
            key = (draft.type, value.model_dump_json())
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                HardAdd(
                    type=draft.type,
                    value=value,
                    label=label,
                    evidence=draft.evidence.strip(),
                )
            )
    by_handle = dict(label_hard(entries))
    for item in output.retire:
        target = by_handle.get(item.ref.strip().lower())
        if target is None:
            logger.info("retirement draft names an unknown handle")
        elif not evidence_in(user_input, item.evidence):
            logger.info("retirement draft discarded: evidence not in the message")
        elif target.id not in {
            c.entry_id for c in candidates if isinstance(c, HardRetire)
        }:
            candidates.append(
                HardRetire(entry_id=target.id, evidence=item.evidence.strip())
            )
    return candidates


@dataclass
class TurnExtraction:
    """What one turn's extraction wrote."""

    soft: ApplyOutcome = field(default_factory=ApplyOutcome)
    accepted: list[HardEntry] = field(default_factory=list)
    asked: list[HardEntry] = field(default_factory=list)
    retirements: list[HardEntry] = field(default_factory=list)

    @property
    def changed_hard(self) -> bool:
        """Whether the hard profile has to be reloaded."""
        return bool(self.accepted or self.asked or self.retirements)


async def _apply_hard(
    user_id: str, decisions: list[HardDecision], result: TurnExtraction
) -> None:
    """Write the hard decisions; one failure never loses the others."""
    for decision in decisions:
        candidate = decision.candidate
        try:
            if isinstance(candidate, HardRetire):
                result.retirements.append(
                    await profile.request_retirement(user_id, candidate.entry_id)
                )
                continue
            accepted = decision.band == "accept"
            entry = await profile.add_entry(
                user_id,
                candidate.value,
                source="inferred",
                state="confirmed" if accepted else "pending",
                created_by="curator",
                confirmed_by="inference" if accepted else None,
                label=candidate.label,
                evidence=candidate.evidence,
                inference_probability=decision.probability,
                replaces_id=decision.replaces_id,
            )
            (result.accepted if accepted else result.asked).append(entry)
        except profile.ProfileError as exc:
            logger.warning("hard candidate not saved for %s: %s", user_id, exc)
        except IntegrityError:
            logger.warning("hard candidate not saved for %s: no user profile", user_id)


async def extract_turn(
    user_id: str, user_input: str, agent_reply: str = ""
) -> TurnExtraction:
    """Extract soft and hard facts from one turn and write them.

    One curator model call, then GLiDE scores every candidate concurrently
    (soft with ``judge_timeout_s``, hard with ``hard_judge_timeout_s``) and the
    writes run concurrently. No database session is held across a model call.

    Args:
        user_id: Supabase Auth UUID.
        user_input: The patient's message. Only this text can support a hard
            fact.
        agent_reply: The assistant's reply, when it exists already. Context
            for soft facts only.

    Returns:
        What was written; empty when the turn changed nothing.
    """
    if not user_input.strip():
        return TurnExtraction()
    with tracing.stage_span(tracing.MEMORY_EXTRACT_TURN) as span:
        state, entries = await asyncio.gather(
            load_state(user_id), profile.load_hard_profile(user_id)
        )
        try:
            tables: ClinicalTables | None = load_tables()
        except TablesUnavailable as exc:
            logger.error(
                "clinical tables unavailable, no hard facts this turn: %s", exc
            )
            tables = None
        output: CuratorOutput = await _curator_llm.ainvoke(
            [
                SystemMessage(content=_CURATOR_SYSTEM),
                HumanMessage(
                    content=build_curator_input(
                        state, user_input, agent_reply, entries, tables
                    )
                ),
            ]
        )
        soft_candidates = to_memory_ops(output.ops, state)
        hard_candidates = (
            to_hard_candidates(output, user_input, entries, tables) if tables else []
        )
        span.set_attribute("n_proposed", len(soft_candidates) + len(hard_candidates))
        if not soft_candidates and not hard_candidates:
            return TurnExtraction()
        soft_scores, hard_scores = await asyncio.gather(
            judge_ops(user_input, soft_candidates, state),
            judge_hard(user_input, hard_candidates, entries, tables)
            if tables
            else resolved([]),
        )
        soft_ops = select_ops(soft_candidates, soft_scores)
        decisions = select_hard_ops(hard_candidates, hard_scores, entries)
        span.set_attribute("n_kept", len(soft_ops) + len(decisions))
        result = TurnExtraction()
        await asyncio.gather(
            _apply_soft(user_id, soft_ops, result),
            _apply_hard(user_id, decisions, result),
        )
        return result


async def _apply_soft(
    user_id: str, ops: list[MemoryOp], result: TurnExtraction
) -> None:
    if ops:
        result.soft = await apply_ops(user_id, ops, "curator")


async def curate_turn(user_id: str, user_input: str, agent_reply: str) -> ApplyOutcome:
    """Update a user's profile from one logged turn (Celery, after the reply).

    Args:
        user_id: Supabase Auth UUID.
        user_input: The user's message.
        agent_reply: The agent's response.

    Returns:
        What was applied to the soft profile; empty when nothing changed.
    """
    with tracing.stage_span(tracing.MEMORY_CURATE_TURN) as span:
        outcome = (await extract_turn(user_id, user_input, agent_reply)).soft
        span.set_attribute("n_applied", outcome.n_applied)
        return outcome


class LogHabit(BaseModel):
    """One pattern inferred from a month of meal logs."""

    fact: str
    kind: Literal["habit", "like"]

    model_config = ConfigDict(extra="forbid")


class LogHabitsOutput(BaseModel):
    """Patterns inferred from the logs; empty when none is clear."""

    facts: list[LogHabit] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


_log_habits_llm = make_llm(FLASH_LITE_MODEL).with_structured_output(LogHabitsOutput)


def build_log_habits_input(
    state: ProfileState,
    staples: dict[str, list[str]],
    by_meal_type: list[dict],
    *,
    days: int,
    max_facts: int,
) -> str:
    """Render the log statistics and profile as the weekly job's message.

    Args:
        state: Current profile state from ``memory.load_state``.
        staples: Output of ``get_staple_foods``.
        by_meal_type: Output of ``get_category_breakdown``.
        days: Length of the window the statistics cover.
        max_facts: Most facts the model may return.

    Returns:
        Prompt text for the log-habits model.
    """
    staple_lines = "\n".join(
        f"- {meal_type}: {', '.join(foods)}" for meal_type, foods in staples.items()
    )
    stat_lines = "\n".join(
        f"- {row['meal_type']}: {row['n_meals']} meals on {row['days_logged']} of "
        f"{days} days, avg {row['avg_kcal']:.0f} kcal, "
        f"{row['avg_protein_g']:.0f}g protein"
        for row in by_meal_type
    )
    profile = "\n".join(f"- [{f.kind}] {f.fact}" for f in state.facts)
    removed = "\n".join(f"- {t}" for t in state.tombstones)
    return "\n\n".join(
        [
            f"Foods logged repeatedly in the last {days} days:\n"
            f"{staple_lines or '(none)'}",
            f"Per meal type:\n{stat_lines or '(none)'}",
            f"Diet settings on: {', '.join(state.diet_chips) or '(none)'}",
            f"Already in the profile:\n{profile or '(empty)'}",
            f"Removed by the user:\n{removed or '(none)'}",
            f"Return at most {max_facts} facts.",
        ]
    )


def plan_log_habit_ops(
    proposed: list[LogHabit], state: ProfileState, max_facts: int
) -> list[MemoryOp]:
    """Turn this week's inferred habits into ops that replace last week's.

    Facts the job wrote before and did not propose again are removed; ones
    proposed again are left untouched; new ones are added.
    """
    wanted: dict[str, LogHabit] = {}
    for habit in proposed:
        text = habit.fact.strip()[:MAX_FACT_CHARS]
        key = normalize_fact(text)
        if key and key not in wanted and len(wanted) < max_facts:
            wanted[key] = LogHabit(fact=text, kind=habit.kind)

    ops: list[MemoryOp] = []
    for fact in state.facts:
        if fact.source != _LOG_SOURCE:
            continue
        if normalize_fact(fact.fact) in wanted:
            del wanted[normalize_fact(fact.fact)]
        else:
            ops.append(RemoveFact(id=fact.id))
    ops.extend(AddFact(fact=h.fact, kind=h.kind) for h in wanted.values())
    return ops


async def infer_log_habits(user_id: str) -> ApplyOutcome:
    """Rewrite one user's log-inferred habit facts from the last month.

    Reads the staples and per-meal-type statistics (both derived from
    ``meal_log``), asks the model for a few interpreted patterns, and
    applies them as the "weekly" actor: it may only add soft facts and
    replace its own. No database session is open during the model call.

    Args:
        user_id: Supabase Auth UUID.

    Returns:
        What was applied; empty when there is nothing to infer from.
    """
    with tracing.stage_span(tracing.MEMORY_INFER_LOG_HABITS) as span:
        cfg = _TUNABLES.memory
        days = cfg.staples_window_days
        staples = await get_staple_foods(user_id, days=days)
        if not staples:
            return ApplyOutcome()
        by_meal_type = await get_category_breakdown(user_id, days)
        state = await load_state(user_id)
        output: LogHabitsOutput = await _log_habits_llm.ainvoke(
            [
                SystemMessage(content=_LOG_HABITS_SYSTEM),
                HumanMessage(
                    content=build_log_habits_input(
                        state,
                        staples,
                        by_meal_type,
                        days=days,
                        max_facts=cfg.weekly_habits_max_facts,
                    )
                ),
            ]
        )
        ops = plan_log_habit_ops(output.facts, state, cfg.weekly_habits_max_facts)
        span.set_attributes({"n_proposed": len(output.facts), "n_kept": len(ops)})
        if not ops:
            return ApplyOutcome()
        outcome = await apply_ops(user_id, ops, "weekly")
        span.set_attribute("n_applied", outcome.n_applied)
        return outcome


__all__ = [
    "CuratorOp",
    "CuratorOutput",
    "HardCuratorOutput",
    "HardDraft",
    "LogHabit",
    "LogHabitsOutput",
    "RetireDraft",
    "TurnExtraction",
    "build_curator_input",
    "build_log_habits_input",
    "curate_turn",
    "evidence_in",
    "extract_turn",
    "infer_log_habits",
    "label_hard",
    "plan_log_habit_ops",
    "to_hard_candidates",
    "to_memory_ops",
]
