"""Suggest a meal: generate a recipe, check it in code, show it only if it passes.

The model proposes a structured recipe (``safety.recipe.Recipe``). USDA values
and the patient's confirmed hard profile decide whether it may be shown
(``safety.checker``); the model is never asked to judge its own recipe. A recipe
that fails is regenerated with the reasons, at most ``safety.max_recipe_attempts``
times in all. Every failed attempt and every recipe shown is stored (FR-012,
FR-038). When nothing passes, or the check cannot run, no recipe is shown.

Latency: one structured model call per attempt (about 1.5-3 s each, Flash-Lite,
thinking off), plus a parallel USDA lookup per ingredient (a few ms). A first
attempt that passes costs one call; each failed attempt adds one.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

import logfire
from pydantic import BaseModel, ConfigDict
from pydantic_ai import Agent, RunContext
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
from sqlalchemy.dialects.postgresql import insert

from backend.agent.cost import record_run_cost
from backend.agent.llm import FLASH_LITE_MODEL
from backend.agent.memory import load_profile, profile_active, render_profile_block
from backend.agent.tools import usda_local
from backend.config import get_tunables
from backend.db.models import CheckFailure, Recommendation, ReviewItem
from backend.db.redis_client import CoachingTurn
from backend.db.session import get_session
from backend.safety import profile
from backend.safety.checker import CheckResult, Failure, check, find_conflicts
from backend.safety.limits import intake_today
from backend.safety.matching import medication_drug
from backend.safety.recipe import Recipe, resolve
from backend.safety.render import render_recipe
from backend.safety.tables import ClinicalTables, TablesUnavailable, load_tables

logger = logging.getLogger(__name__)

_TUNABLES = get_tunables()
_SAFETY = _TUNABLES.safety

_HISTORY_TURNS = 6


class SuggestionResult(BaseModel):
    """What a meal request produced; ``message`` is always safe to show."""

    message: str
    recipe: Recipe | None = None
    recommendation_id: str | None = None
    attempts: int = 0

    model_config = ConfigDict(extra="forbid")


@dataclass
class _Deps:
    """Per-run instructions: the profile blocks and earlier failures."""

    hard_block: str
    soft_block: str
    prior_failures: list[str]


# Thinking off: a structured-output call in the chat turn, like parse_query.
# retries=0 so a malformed answer comes back to the loop as a failed attempt
# instead of a hidden retry that would not count toward the attempt limit.
_recipe_agent = Agent(
    GoogleModel(FLASH_LITE_MODEL),
    output_type=Recipe,
    deps_type=_Deps,
    instructions=_TUNABLES.prompts.recipe_generation_system,
    retries=0,
    model_settings=GoogleModelSettings(
        google_thinking_config={
            "thinking_budget": _TUNABLES.token_limits.extraction_thinking_budget
        }
    ),
)


@_recipe_agent.instructions
def _profile_instructions(ctx: RunContext[_Deps]) -> str:
    """The patient's profile, then what earlier attempts got wrong."""
    blocks = [ctx.deps.hard_block, ctx.deps.soft_block]
    if ctx.deps.prior_failures:
        blocks.append(
            "Previous attempts that failed the safety check. Fix every reason:\n"
            + "\n".join(ctx.deps.prior_failures)
        )
    return "\n\n".join(block for block in blocks if block)


def _prompt(request: str, history: Sequence[CoachingTurn]) -> str:
    recent = "\n".join(f"{t.role}: {t.content}" for t in history[-_HISTORY_TURNS:])
    parts = [f"Recent conversation:\n{recent}"] if recent else []
    parts.append(f"The patient asks: {request}")
    return "\n\n".join(parts)


def _failure_row(failure: Failure) -> dict:
    return {
        "rule": failure.rule,
        "entry_id": failure.entry_id,
        "detail": failure.detail,
        "compared": {
            "value": failure.value,
            "limit": failure.limit,
            "unit": failure.unit,
        },
    }


@dataclass
class _Attempt:
    """One failed attempt, kept until the outcome is known."""

    number: int
    recipe: dict
    failures: list[Failure]


def _lesson(attempt: _Attempt) -> str:
    name = attempt.recipe.get("name", "the previous answer")
    return f"- Attempt {attempt.number} ({name}): " + "; ".join(
        f.detail for f in attempt.failures
    )


async def _soft_block(user_id: str) -> str:
    if not profile_active(user_id):
        return ""
    return render_profile_block(await load_profile(user_id))


async def _generate(deps: _Deps, prompt: str) -> Recipe | str:
    """A recipe, or the reason the model's answer was malformed."""
    try:
        run = await _recipe_agent.run(prompt, deps=deps)
    except UnexpectedModelBehavior as exc:
        # Reason only: the cause can quote the model's output.
        return str(exc.__cause__ or exc)[:300]
    record_run_cost(run, FLASH_LITE_MODEL, operation="suggest_meal")
    return run.output


def plan_sampled(recommendation_id: str, rate: float) -> bool:
    """Whether a shown recommendation is queued for dietitian spot-check.

    Deterministic: the id is hashed, so a recommendation is always in or out.

    Args:
        recommendation_id: The recommendation's UUID.
        rate: Share to sample, 0 to 1 (``safety.plan_sample_rate``).

    Returns:
        True when the recommendation falls in the sampled share.
    """
    digest = hashlib.sha256(recommendation_id.encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64 < rate


def _review_rows(
    user_id: str, entries: list[profile.HardEntry], tables: ClinicalTables
) -> list[dict]:
    """Conflicts and unmatched medications the dietitian queue should see."""
    binding = profile.confirmed(entries)
    rows = [
        {
            "user_id": user_id,
            "kind": "rule_conflict",
            "subject_id": conflict.entry_ids[0],
            "detail": {"entries": conflict.entry_ids, "note": conflict.note},
        }
        for conflict in find_conflicts(binding, tables)
    ]
    rows += [
        {
            "user_id": user_id,
            "kind": "unknown_medication",
            "subject_id": entry.id,
            "detail": {"medication": entry.value.name},
        }
        for entry in binding
        if isinstance(entry.value, profile.MedicationValue)
        and medication_drug(entry, tables) is None
    ]
    return rows


async def _store(
    user_id: str,
    attempts: list[_Attempt],
    shown: CheckResult | None,
    recipe: Recipe | None,
    entries: list[profile.HardEntry],
    tables: ClinicalTables,
    conversation_id: str | None,
) -> str | None:
    """Write the failed attempts, the recommendation and the review items.

    One transaction: a recipe is shown only if its record was written.

    Returns:
        The recommendation id when a recipe passed, else None.
    """
    recommendation_id = str(uuid.uuid4()) if shown else None
    version = profile.version_of(entries)
    async with get_session()() as session, session.begin():
        if shown and recipe:
            session.add(
                Recommendation(
                    id=recommendation_id,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    recipe=recipe.model_dump(mode="json"),
                    check_snapshot=shown.model_dump(mode="json"),
                    attempts=shown.attempt,
                    status="shown",
                )
            )
            await session.flush()
        for index, attempt in enumerate(attempts):
            dropped = shown is None and index == len(attempts) - 1
            session.add(
                CheckFailure(
                    user_id=user_id,
                    recommendation_id=recommendation_id,
                    attempt=attempt.number,
                    recipe=attempt.recipe,
                    failures=[_failure_row(f) for f in attempt.failures],
                    profile_version=version,
                    outcome="dropped" if dropped else "regenerated",
                )
            )
        rows = _review_rows(user_id, entries, tables)
        if recommendation_id and plan_sampled(
            recommendation_id, _SAFETY.plan_sample_rate
        ):
            rows.append(
                {
                    "user_id": user_id,
                    "kind": "plan_sample",
                    "subject_id": recommendation_id,
                    "detail": None,
                }
            )
        if rows:
            await session.execute(insert(ReviewItem).on_conflict_do_nothing(), rows)
    return recommendation_id


async def suggest_meal(
    user_id: str,
    request: str,
    history: Sequence[CoachingTurn],
    entries: list[profile.HardEntry],
    *,
    conversation_id: str | None = None,
) -> SuggestionResult:
    """Produce a recipe that passes the patient's checks, or say none was found.

    Args:
        user_id: Supabase Auth UUID.
        request: The patient's message.
        history: Recent conversation turns, oldest first.
        entries: The patient's live hard entries, already loaded this turn.
        conversation_id: Thread id, stored with the recommendation.

    Returns:
        The rendered recipe with its recommendation id, or a fixed message
        (``safety.no_suitable_meal_text``, or ``safety.food_db_unavailable_text``
        when the food database or the clinical tables cannot be read).
    """
    with logfire.span("suggest_meal") as span:
        try:
            result = await _suggest(user_id, request, history, entries, conversation_id)
        except (usda_local.FoodDbUnavailable, TablesUnavailable) as exc:
            logger.error("meal check unavailable: %s", exc)
            span.set_attribute("unavailable", type(exc).__name__)
            return SuggestionResult(message=_SAFETY.food_db_unavailable_text)
        span.set_attribute("attempts", result.attempts)
        span.set_attribute("shown", result.recipe is not None)
        return result


async def _suggest(
    user_id: str,
    request: str,
    history: Sequence[CoachingTurn],
    entries: list[profile.HardEntry],
    conversation_id: str | None,
) -> SuggestionResult:
    tables = load_tables()
    soft_block, intake = await asyncio.gather(
        _soft_block(user_id), intake_today(user_id, entries)
    )
    deps = _Deps(
        hard_block=profile.render_block(entries, tables),
        soft_block=soft_block,
        prior_failures=[],
    )
    prompt = _prompt(request, history)
    attempts: list[_Attempt] = []
    for number in range(1, _SAFETY.max_recipe_attempts + 1):
        generated = await _generate(deps, prompt)
        if isinstance(generated, str):
            failure = Failure(
                rule="malformed", entry_id=None, detail=f"malformed: {generated}"
            )
            attempts.append(_Attempt(number, {"error": failure.detail}, [failure]))
        else:
            with logfire.span("check_recipe", attempt=number) as span:
                resolved = await resolve(generated, usda_local.lookup)
                result = check(generated, resolved, entries, intake, tables, number)
                span.set_attribute("passed", result.passed)
                span.set_attribute(
                    "failed_rules", ",".join(sorted({f.rule for f in result.failures}))
                )
            if result.passed:
                recommendation_id = await _store(
                    user_id,
                    attempts,
                    result,
                    generated,
                    entries,
                    tables,
                    conversation_id,
                )
                return SuggestionResult(
                    message=render_recipe(generated, result),
                    recipe=generated,
                    recommendation_id=recommendation_id,
                    attempts=number,
                )
            attempts.append(
                _Attempt(number, generated.model_dump(mode="json"), result.failures)
            )
        deps.prior_failures.append(_lesson(attempts[-1]))
    await _store(user_id, attempts, None, None, entries, tables, conversation_id)
    return SuggestionResult(
        message=_SAFETY.no_suitable_meal_text, attempts=len(attempts)
    )
