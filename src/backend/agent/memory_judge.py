"""GLiDE decides which proposed memory changes are saved.

The curator model (agent/memory_curator.py) only drafts candidates: it
writes the fact text and names the operation. Whether a candidate is kept
is a Fastino GLiDE judgment (agent/glide.py): one calibrated probability
per candidate, compared with a threshold from tunables by
:func:`select_ops`. No generated text takes part in the decision.

Two yes/no questions, one per kind of change:

- ``worth_remembering``: for an add, a replacement or a diet setting, does
  the user's message establish the candidate as a lasting fact about them?
- ``no_longer_true``: for a removal, does the message show the stored fact
  has stopped being true?

Hard facts (spec 013 US4) get their own questions, one per entry type, and
:func:`select_hard_ops` places each candidate in the accept, ask or drop band
(research R2). Accept needs both a high probability and a candidate that adds
a constraint, decided in code; anything that removes or loosens one, and
anything GLiDE could not score, is asked, never accepted.

Soft facts run in Celery after the reply is sent, so they add nothing to a
chat turn; hard facts run inside a coaching turn, so :func:`judge_hard` uses
the short ``memory.hard_judge_timeout_s``.
Each Celery task has its own event loop, so the client is opened and closed
per call instead of reusing the routing client in agent/system_one.py.

Sent to GLiDE: the message text and the candidate fact text. No user id,
history or goals. Neither text is logged here.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import httpx
import logfire
from pydantic import BaseModel, ConfigDict, Field

from backend.agent import glide
from backend.agent.glide import GlideUnavailable, Question, Questions, noul
from backend.agent.memory import (
    AddFact,
    AddRestriction,
    MemoryOp,
    ProfileState,
    RemoveFact,
    ReplaceFact,
    SetDietChip,
)
from backend.config import get_tunables
from backend.safety.profile import (
    EntryType,
    EntryValue,
    HardEntry,
    NutrientLimitValue,
    label_for,
)
from backend.safety.tables import ClinicalTables

logger = logging.getLogger(__name__)

_TUNABLES = get_tunables()

_WORTH_REMEMBERING = "worth_remembering"
_NO_LONGER_TRUE = "no_longer_true"

_QUESTIONS: Questions = {
    _WORTH_REMEMBERING: noul(
        instructions=(
            "`message` was sent by a user to a nutrition-tracking assistant. "
            "`candidate` is a note about that user proposed for long-term "
            "memory. Does `message` establish `candidate` as a lasting fact "
            "about the user: an allergy or intolerance, a dietary rule, a food "
            "they like or avoid, a regular eating habit, or their cooking, "
            "budget or schedule?"
        ),
        criteria={
            "true": (
                "The user says it about themselves as generally true, e.g. "
                "message 'no peanuts please, I'm allergic' with candidate "
                "'Allergic to peanuts'; message 'I've gone vegetarian' with "
                "candidate 'Follows a vegetarian diet'; message 'I usually "
                "skip breakfast' with candidate 'Usually skips breakfast'."
            ),
            "false": (
                "`message` only reports one meal, a one-off choice, a "
                "temporary state, a hypothetical or a question, or "
                "`candidate` says more than `message` supports, e.g. message "
                "'had a salad for lunch' with candidate 'Likes salad'; "
                "message 'eating out tonight' with candidate 'Eats out "
                "often'; message 'is tofu healthy?' with candidate 'Likes "
                "tofu'."
            ),
        },
    ),
    _NO_LONGER_TRUE: noul(
        instructions=(
            "`message` was sent by a user to a nutrition-tracking assistant. "
            "`candidate` is a note about that user held in long-term memory. "
            "Does `message` show that `candidate` is no longer true of the "
            "user?"
        ),
        criteria={
            "true": (
                "The user states a lasting change that contradicts it, e.g. "
                "message 'I've gone vegetarian' with candidate 'Loves "
                "chicken'; message 'I can't stand oats any more' with "
                "candidate 'Likes oatmeal'."
            ),
            "false": (
                "`message` is about one meal or one day, or does not "
                "contradict `candidate`, e.g. message 'no chicken today' "
                "with candidate 'Loves chicken'."
            ),
        },
    ),
}


def _own_fact(what: str, positive: str, negative: str) -> Question:
    """Yes/no question: does ``message`` state the user's own lasting fact?"""
    return noul(
        instructions=(
            "`message` was sent by a user to a nutrition-tracking assistant. "
            f"`candidate` names {what}. Does `message` state that the user "
            "themself has it, as a lasting fact about them?"
        ),
        criteria={
            "true": (
                "The user says it about themselves, in the present, as "
                f"generally true, e.g. {positive}."
            ),
            "false": (
                "The message is about someone else (my sister, my dad), a "
                "hypothetical ('if I were'), a question ('is X bad for "
                "diabetics?'), a past state that no longer holds ('I used "
                "to'), a negation ('I'm not allergic'), a doubt ('maybe', "
                f"'I think'), or one meal only, e.g. {negative}."
            ),
        },
    )


_HARD_QUESTION: dict[str, str] = {
    "allergy": "states_own_allergy",
    "food_exclusion": "states_own_food_exclusion",
    "diet_setting": "states_own_diet",
    "diagnosis": "has_diagnosis",
    "medication": "takes_medication",
    "physical_limitation": "has_physical_limitation",
    "nutrient_limit": "has_nutrient_limit",
}

_HARD_QUESTIONS: Questions = {
    _HARD_QUESTION["allergy"]: _own_fact(
        "an allergy or intolerance",
        "message 'I found out I'm allergic to shellfish' with candidate "
        "'Shellfish allergy'",
        "message 'my sister is allergic to shellfish' or 'is shellfish "
        "allergy common?' with candidate 'Shellfish allergy'",
    ),
    _HARD_QUESTION["food_exclusion"]: _own_fact(
        "a food the user never eats",
        "message 'I never eat pork' with candidate 'No pork'",
        "message 'no pork tonight' or 'my husband won't eat pork' with "
        "candidate 'No pork'",
    ),
    _HARD_QUESTION["diet_setting"]: _own_fact(
        "a way of eating",
        "message 'I'm vegan now' with candidate 'Vegan'",
        "message 'thinking about going vegan' or 'what is a vegan diet?' "
        "with candidate 'Vegan'",
    ),
    _HARD_QUESTION["diagnosis"]: _own_fact(
        "a medical condition",
        "message 'I was diagnosed with type 2 diabetes' with candidate 'Diabetes'",
        "message 'my mum has diabetes' or 'could I have diabetes?' with "
        "candidate 'Diabetes'",
    ),
    _HARD_QUESTION["medication"]: _own_fact(
        "a medication",
        "message 'I take warfarin every day' with candidate 'Warfarin'",
        "message 'my dad takes warfarin' or 'does warfarin interact with "
        "kale?' with candidate 'Warfarin'",
    ),
    _HARD_QUESTION["physical_limitation"]: _own_fact(
        "a chewing, swallowing, grip or standing limitation",
        "message 'I have trouble swallowing solid food' with candidate "
        "'Swallowing difficulty'",
        "message 'my gran has trouble chewing' with candidate 'Chewing difficulty'",
    ),
    _HARD_QUESTION["nutrient_limit"]: _own_fact(
        "a daily or per-meal ceiling on a nutrient",
        "message 'my doctor limited me to 1500 mg of sodium a day' with "
        "candidate 'Sodium: up to 1,500 mg a day'",
        "message 'is 1500 mg of sodium a lot?' with candidate 'Sodium: up "
        "to 1,500 mg a day'",
    ),
}
_ALL_QUESTIONS: Questions = {**_QUESTIONS, **_HARD_QUESTIONS}


def _candidate(op: MemoryOp, state: ProfileState) -> tuple[str, str] | None:
    """Return the question key and candidate text GLiDE is asked about."""
    if isinstance(op, AddFact | ReplaceFact | AddRestriction):
        return _WORTH_REMEMBERING, op.fact
    if isinstance(op, SetDietChip):
        return _WORTH_REMEMBERING, f"Follows a {op.chip.replace('_', ' ')} diet"
    stored = next((f.fact for f in state.facts if f.id == op.id), None)
    return (_NO_LONGER_TRUE, stored) if stored else None


async def _judge_one(
    client: httpx.AsyncClient, message: str, question: str, candidate: str
) -> float | None:
    """Ask one question about one candidate; None when GLiDE gives no answer."""
    try:
        response = await glide.ask(
            client,
            {"message": message, "candidate": candidate},
            {question: _ALL_QUESTIONS[question]},
        )
        return response.noul(question)
    except GlideUnavailable as exc:
        logger.warning("GLiDE memory judgment unavailable: %s", exc.reason)
        return None


async def judge_ops(
    message: str, ops: list[MemoryOp], state: ProfileState
) -> list[float | None]:
    """Score each proposed op with GLiDE.

    One request per op, sent concurrently on one connection. Never raises
    for service problems.

    Args:
        message: The user's message the ops were drafted from.
        ops: Candidate operations from the curator.
        state: The profile the ops refer to (removals name a stored fact).

    Returns:
        One probability per op, in order: P(save) for adds, replacements
        and diet settings, P(no longer true) for removals. ``None`` where
        GLiDE gave no answer (no API key, timeout, error, unknown fact).
    """
    if not ops:
        return []
    client = glide.make_client(_TUNABLES.memory.judge_timeout_s)
    if client is None:
        return [None] * len(ops)
    candidates = [_candidate(op, state) for op in ops]
    async with client:
        return list(
            await asyncio.gather(
                *[
                    _judge_one(client, message, *candidate)
                    if candidate is not None
                    else _no_answer()
                    for candidate in candidates
                ]
            )
        )


async def _no_answer() -> None:
    """Placeholder so unjudgeable ops keep their position in the gather."""
    return None


def _keep_unjudged(op: MemoryOp, *, save_unjudged: bool) -> bool:
    """Whether to save an op GLiDE could not score.

    A new restriction is always proposed: a missed allergy is silent, while a
    wrong one is only a pending entry the user can deny. A removal or a
    replacement is always held, since unscored it could erase a fact the
    user relies on. Anything else follows ``memory.save_unjudged``.
    """
    if isinstance(op, AddRestriction):
        return True
    if isinstance(op, RemoveFact | ReplaceFact):
        return False
    return save_unjudged


def select_ops(ops: list[MemoryOp], scores: list[float | None]) -> list[MemoryOp]:
    """Keep the ops GLiDE scored at or above the threshold.

    The whole save decision: a comparison per op, no model call. A kept
    add or replacement carries GLiDE's probability as its confidence. An op
    GLiDE could not score is decided by :func:`_keep_unjudged`.

    Args:
        ops: Candidate operations from the curator.
        scores: Output of :func:`judge_ops`, aligned with ``ops``.

    Returns:
        The ops to hand to ``apply_ops``, in the original order.
    """
    cfg = _TUNABLES.memory
    kept: list[MemoryOp] = []
    for op, score in zip(ops, scores, strict=True):
        if score is None:
            keep_unjudged = _keep_unjudged(op, save_unjudged=cfg.save_unjudged)
            if keep_unjudged:
                kept.append(op)
            logger.info("memory op %s unjudged, kept=%s", op.op, keep_unjudged)
            continue
        keep = score >= cfg.save_min_probability
        logger.info("memory op %s scored %.2f, kept=%s", op.op, score, keep)
        if not keep:
            continue
        if isinstance(op, AddFact | ReplaceFact):
            op = op.model_copy(update={"confidence": score})
        kept.append(op)
    return kept


# --- hard facts -----------------------------------------------------------------


class HardAdd(BaseModel):
    """A typed hard fact the patient stated, as the curator drafted it.

    ``evidence`` is the patient's own words, already checked to be a substring
    of their message (agent/memory_curator.py).
    """

    type: EntryType
    value: EntryValue
    label: str | None = Field(
        default=None, description="Free text, kept only for food exclusions"
    )
    evidence: str = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")


class HardRetire(BaseModel):
    """The patient says a confirmed entry no longer applies."""

    entry_id: str
    evidence: str = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")


HardCandidate = HardAdd | HardRetire
Band = Literal["accept", "ask"]


@dataclass(frozen=True)
class HardDecision:
    """What to do with one hard candidate: save it confirmed, or ask first."""

    candidate: HardCandidate
    band: Band
    probability: float | None
    # A looser limit replaces the confirmed one it loosens, once confirmed.
    replaces_id: str | None = None


def candidate_entry(add: HardAdd) -> HardEntry:
    """A transient entry for ``add``, so ``label_for`` can name it."""
    now = datetime.now(UTC)
    return HardEntry(
        id="candidate",
        type=add.type,
        value=add.value,
        stored_label=add.label,
        source="inferred",
        state="pending",
        created_at=now,
        created_by="curator",
    )


def _hard_text(
    candidate: HardCandidate, entries: list[HardEntry], tables: ClinicalTables
) -> tuple[str, str] | None:
    """The GLiDE question key and candidate text for a hard candidate."""
    if isinstance(candidate, HardAdd):
        return _HARD_QUESTION[candidate.type], label_for(
            candidate_entry(candidate), tables
        )
    target = next((e for e in entries if e.id == candidate.entry_id), None)
    if target is None:
        return None
    return _NO_LONGER_TRUE, label_for(target, tables)


async def judge_hard(
    message: str,
    candidates: list[HardCandidate],
    entries: list[HardEntry],
    tables: ClinicalTables,
) -> list[float | None]:
    """Score each hard candidate with GLiDE, concurrently, never raising.

    Args:
        message: The patient's message the candidates were drafted from.
        candidates: Typed candidates that passed the evidence check.
        entries: The patient's live hard entries (retirements name one).
        tables: Clinical tables, for the candidate's label.

    Returns:
        One probability per candidate, in order: P(states own fact) for an
        add, P(no longer true) for a retirement. ``None`` where GLiDE gave no
        answer (no API key, timeout, error, unknown entry).
    """
    if not candidates:
        return []
    client = glide.make_client(_TUNABLES.memory.hard_judge_timeout_s)
    if client is None:
        return [None] * len(candidates)
    texts = [_hard_text(c, entries, tables) for c in candidates]
    async with client:
        return list(
            await asyncio.gather(
                *[
                    _judge_one(client, message, *text)
                    if text is not None
                    else _no_answer()
                    for text in texts
                ]
            )
        )


_UNIT_FACTOR = {"mg": 1.0, "g": 1000.0, "ml": 1.0}


def _ceiling(value: NutrientLimitValue) -> tuple[str, float]:
    """A limit's unit family and amount in the family's base unit."""
    family = "ml" if value.unit == "ml" else "mass"
    return family, value.amount * _UNIT_FACTOR[value.unit]


def adds_constraint(add: HardAdd, entries: list[HardEntry]) -> bool | None:
    """Whether a hard add only tightens what the patient already declared.

    Args:
        add: The candidate.
        entries: The patient's live entries.

    Returns:
        True when it is new (no equal live entry; a nutrient limit that is new
        for its nutrient and period) or a stricter limit than every confirmed
        one for the same nutrient and period. False when it loosens a limit or
        cannot be compared (another unit family). None when it duplicates a
        live entry, so there is nothing to save or ask.
    """
    live = [e for e in entries if e.type == add.type]
    if any(e.value == add.value for e in live):
        return None
    if not isinstance(add.value, NutrientLimitValue):
        return True
    same = [
        e.value
        for e in live
        if e.state == "confirmed"
        and isinstance(e.value, NutrientLimitValue)
        and e.value.nutrient == add.value.nutrient
        and e.value.period == add.value.period
    ]
    if not same:
        return True
    family, amount = _ceiling(add.value)
    for other in same:
        other_family, other_amount = _ceiling(other)
        if other_family != family or amount >= other_amount:
            return False
    return True


def select_hard_ops(
    candidates: list[HardCandidate],
    scores: list[float | None],
    entries: list[HardEntry],
) -> list[HardDecision]:
    """Place each hard candidate in a band. No model call, no I/O.

    Bands, from ``memory.hard_accept_min_probability`` (accept) and
    ``memory.hard_ask_min_probability`` (ask):

    * accept: probability >= accept and the add adds a constraint;
    * ask: ask <= probability < accept, and any candidate GLiDE could not
      score; also, whatever the score (FR-020), any retirement and any add
      that loosens a limit. A loosened limit is saved pending and replaces the
      confirmed one it loosens once confirmed;
    * drop: an add with probability < ask, and duplicates of a live entry.

    Args:
        candidates: Output of the curator's evidence check.
        scores: Output of :func:`judge_hard`, aligned with ``candidates``.
        entries: The patient's live hard entries.

    Returns:
        The decisions to apply, in the original order.
    """
    cfg = _TUNABLES.memory
    decisions: list[HardDecision] = []
    for candidate, score in zip(candidates, scores, strict=True):
        replaces_id: str | None = None
        if isinstance(candidate, HardRetire):
            target = next((e for e in entries if e.id == candidate.entry_id), None)
            if target is None or target.retire_requested_at is not None:
                continue
            tightens, always_ask = False, True
        else:
            added = adds_constraint(candidate, entries)
            if added is None:
                continue
            tightens, always_ask = added, not added
            if always_ask:
                replaces_id = _loosened_entry(candidate, entries)
        if always_ask:
            band: Band | None = "ask"
        elif score is None:
            band = "ask"
        elif score < cfg.hard_ask_min_probability:
            band = None
        elif score >= cfg.hard_accept_min_probability and tightens:
            band = "accept"
        else:
            band = "ask"
        # A Logfire event, not a log line: error analysis reads the band of
        # each candidate next to the GLiDE call in the turn's trace.
        logfire.info(
            "hard candidate {kind} scored {score}, band={band}",
            kind=candidate.type if isinstance(candidate, HardAdd) else "retire",
            score=score,
            band=band or "drop",
        )
        if band is not None:
            decisions.append(HardDecision(candidate, band, score, replaces_id))
    return decisions


def _loosened_entry(add: HardAdd, entries: list[HardEntry]) -> str | None:
    """The confirmed limit a looser limit replaces: the strictest comparable one."""
    if not isinstance(add.value, NutrientLimitValue):
        return None
    family, _ = _ceiling(add.value)
    same = [
        e
        for e in entries
        if e.state == "confirmed"
        and isinstance(e.value, NutrientLimitValue)
        and e.value.nutrient == add.value.nutrient
        and e.value.period == add.value.period
        and _ceiling(e.value)[0] == family
    ]
    if not same:
        return None
    return min(same, key=lambda e: _ceiling(e.value)[1]).id


__all__ = [
    "HardAdd",
    "HardCandidate",
    "HardDecision",
    "HardRetire",
    "adds_constraint",
    "judge_hard",
    "judge_ops",
    "select_hard_ops",
    "select_ops",
]
