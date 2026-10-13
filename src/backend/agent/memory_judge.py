"""Jev decides which proposed memory changes are saved.

The curator model (agent/memory_curator.py) only drafts candidates: it
writes the fact text and names the operation. Whether a candidate is kept
is a TypeSafe System One (Jev) judgment: one calibrated probability per
candidate, compared with a threshold from tunables by :func:`select_ops`.
No generated text takes part in the decision.

Two yes/no questions, one per kind of change:

- ``worth_remembering``: for an add, a replacement or a diet setting, does
  the user's message establish the candidate as a lasting fact about them?
- ``no_longer_true``: for a removal, does the message show the stored fact
  has stopped being true?

Runs in Celery after the reply is sent, so it adds nothing to a chat turn.
Each Celery task has its own event loop, so the client is opened and closed
per call instead of reusing the routing client in agent/system_one.py.

Sent to TypeSafe: the message text and the candidate fact text. No user
id, history or goals. Neither text is logged here.
"""

from __future__ import annotations

import asyncio
import logging
import os

from typesafe_sdk import AsyncTypeSafeClient, Noul, RetryPolicy, TypeSafeError

from backend.agent.memory import (
    AddFact,
    MemoryOp,
    ProfileState,
    ReplaceFact,
    SetDietChip,
)
from backend.config import get_tunables

logger = logging.getLogger(__name__)

_TUNABLES = get_tunables()
_API_KEY_ENV = "TYPESAFE_API_KEY"

_WORTH_REMEMBERING = "worth_remembering"
_NO_LONGER_TRUE = "no_longer_true"

_QUESTIONS: dict[str, Noul] = {
    _WORTH_REMEMBERING: Noul(
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
    _NO_LONGER_TRUE: Noul(
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


def _candidate(op: MemoryOp, state: ProfileState) -> tuple[str, str] | None:
    """Return the question key and candidate text Jev is asked about."""
    if isinstance(op, AddFact | ReplaceFact):
        return _WORTH_REMEMBERING, op.fact
    if isinstance(op, SetDietChip):
        return _WORTH_REMEMBERING, f"Follows a {op.chip.replace('_', ' ')} diet"
    stored = next((f.fact for f in state.facts if f.id == op.id), None)
    return (_NO_LONGER_TRUE, stored) if stored else None


async def _judge_one(
    client: AsyncTypeSafeClient, message: str, question: str, candidate: str
) -> float | None:
    """Ask one question about one candidate; None when Jev gives no answer."""
    try:
        response = await client.system_one(
            {"message": message, "candidate": candidate},
            {question: _QUESTIONS[question]},
        )
        probability = float(response.nouls[question].noul)
    except TypeSafeError as exc:
        # Class name only: exception text can echo the request body.
        logger.warning("TypeSafe memory judgment unavailable: %s", type(exc).__name__)
        return None
    except (KeyError, ValueError) as exc:
        logger.warning("TypeSafe memory judgment malformed: %s", type(exc).__name__)
        return None
    return probability if 0.0 <= probability <= 1.0 else None


async def judge_ops(
    message: str, ops: list[MemoryOp], state: ProfileState
) -> list[float | None]:
    """Score each proposed op with Jev.

    One request per op, sent concurrently on one connection. Never raises
    for service problems.

    Args:
        message: The user's message the ops were drafted from.
        ops: Candidate operations from the curator.
        state: The profile the ops refer to (removals name a stored fact).

    Returns:
        One probability per op, in order: P(save) for adds, replacements
        and diet settings, P(no longer true) for removals. ``None`` where
        Jev gave no answer (no API key, timeout, error, unknown fact).
    """
    api_key = os.environ.get(_API_KEY_ENV, "")
    if not api_key or not ops:
        return [None] * len(ops)
    candidates = [_candidate(op, state) for op in ops]
    async with AsyncTypeSafeClient(
        api_key=api_key,
        model=_TUNABLES.typesafe.model,
        timeout=_TUNABLES.memory.judge_timeout_s,
        retry=RetryPolicy(max_retries=0),
    ) as client:
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


def select_ops(ops: list[MemoryOp], scores: list[float | None]) -> list[MemoryOp]:
    """Keep the ops Jev scored at or above the threshold.

    The whole save decision: a comparison per op, no model call. A kept
    add or replacement carries Jev's probability as its confidence. An op
    Jev could not score is kept only when ``memory.save_unjudged`` is on.

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
            if cfg.save_unjudged:
                kept.append(op)
            logger.info("memory op %s unjudged, kept=%s", op.op, cfg.save_unjudged)
            continue
        keep = score >= cfg.save_min_probability
        logger.info("memory op %s scored %.2f, kept=%s", op.op, score, keep)
        if not keep:
            continue
        if isinstance(op, AddFact | ReplaceFact):
            op = op.model_copy(update={"confidence": score})
        kept.append(op)
    return kept


__all__ = ["judge_ops", "select_ops"]
