"""Worst-case size of one coaching response call.

Every part of the coaching input has its own cap: the profile (written
under ``memory.profile_max_chars``), the history (``coaching_history_turns``
exchanges cut to ``coaching_history_max_chars``), guideline passages
(``retrieval.guideline_top_k`` chunks of at most ``MAX_CHUNK_WORDS``), the
data payload (aggregates only) and the message
(``token_limits.max_user_input_chars``). This test fills each part to its
cap and checks the total against ``token_limits.coaching_max_input_tokens``,
so a cap raised later cannot silently grow the prompt past the budget.

Tokens are estimated at 4 characters each. Tool definitions (profile path
only) are not counted.
"""

from __future__ import annotations

from unittest.mock import patch

from pydantic_ai import capture_run_messages
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart
from pydantic_ai.models.test import TestModel

from backend.agent import coaching
from backend.agent.context import (
    ContextBundle,
    GoalSummary,
    WeeklyPattern,
    build_system_prompt,
)
from backend.agent.memory import DIET_CHIPS, MAX_FACT_CHARS, MemoryFact
from backend.config import get_tunables
from backend.db import redis_client
from backend.db.redis_client import CoachingTurn, TodayTotals
from backend.guidelines.chunking import MAX_CHUNK_WORDS
from backend.guidelines.retrieval import RetrievedChunk

_TUNABLES = get_tunables()
_CHARS_PER_TOKEN = 4


def _full_profile() -> list[MemoryFact]:
    """Facts totalling exactly the profile character cap."""
    budget = _TUNABLES.memory.profile_max_chars
    facts: list[MemoryFact] = []
    while budget > 0:
        size = min(MAX_FACT_CHARS, budget)
        facts.append(
            MemoryFact(
                id=str(len(facts)),
                fact="r" * size,
                kind="restriction",
                source="stated",
            )
        )
        budget -= size
    return facts


def _full_context_prompt() -> str:
    ctx = ContextBundle(
        today_totals=TodayTotals(kcal=1800, protein_g=90, fiber_g=20, n_meals=4),
        goals=GoalSummary(
            kcal_goal=2200,
            protein_goal=140,
            fiber_goal=30,
            dietary_prefs=dict.fromkeys(DIET_CHIPS, True),
            conditions=["diabetes", "prediabetes", "hypertension", "ckd"],
            streak_days=120,
        ),
        weekly_pattern=WeeklyPattern(
            avg_protein_g=95,
            days_hit_protein=3,
            weak_spots=["fiber", "vitamin d", "iron", "calcium"],
            missed_meals=["breakfast", "lunch"],
        ),
        profile_active=True,
        profile=_full_profile(),
        staples={
            meal: ["s" * 40] * 5 for meal in ("breakfast", "lunch", "dinner", "snack")
        },
    )
    return build_system_prompt(ctx)


def _full_history() -> list[CoachingTurn]:
    long = "h" * 5000
    turns = [
        CoachingTurn(role=role, content=long)
        for _ in range(_TUNABLES.memory.coaching_history_turns)
        for role in ("user", "assistant")
    ]
    # Read through the store's own compaction, as get_coaching_history does.
    return [redis_client._compact(t) for t in turns]


def _full_passages() -> list[RetrievedChunk]:
    return [
        RetrievedChunk(
            id=str(n),
            source_id="src",
            source_title="t" * 80,
            section="s" * 80,
            # Five-letter words: about the corpus's average word length, so
            # the cap is measured in realistic characters. Real chunks in
            # docs/guidelines are far below it (max 707 chars, 2026-11-10).
            text=" ".join(["words"] * MAX_CHUNK_WORDS),
            score=0.9,
        )
        for n in range(_TUNABLES.retrieval.guideline_top_k)
    ]


def _full_data() -> dict:
    food = {"name": "f" * 40, "count": 12, "kcal": 450.0}
    return {
        "today_totals": TodayTotals(kcal=1800, protein_g=90, fiber_g=20).model_dump(),
        "macros": {
            "kcal": 1.0,
            "protein_g": 1.0,
            "carbs_g": 1.0,
            "fat_g": 1.0,
            "fiber_g": 1.0,
            "n_meals": 1,
        },
        "micronutrients": {
            f"nutrient_{i:02d}_mg": {"amount": 123.4, "unit": "mg"} for i in range(40)
        },
        "foods": {
            "top_foods_by_frequency": [food] * 8,
            "flagged_junk_foods": [food] * 5,
            "highest_calorie_foods": [food] * 5,
        },
        "goals": {
            "kcal_goal": 2200,
            "protein_goal": 140,
            "fiber_goal": 30,
            "dietary_prefs": dict.fromkeys(DIET_CHIPS, True),
        },
        "period": {"start": "2026-10-01", "end": "2026-10-30", "label": "custom"},
    }


def _message_chars(msg: ModelRequest | ModelResponse) -> int:
    total = len(getattr(msg, "instructions", None) or "")
    for part in msg.parts:
        content = getattr(part, "content", "")
        total += len(content) if isinstance(content, str) else 0
    return total


async def test_worst_case_coaching_input_fits_the_budget() -> None:
    message = "m" * _TUNABLES.token_limits.max_user_input_chars

    with (
        patch("backend.agent.coaching.profile_active", return_value=True),
        coaching._response_agent.override(model=TestModel(call_tools=[])),
        capture_run_messages() as msgs,
    ):
        await coaching.generate_response(
            message,
            _full_data(),
            context_prompt=_full_context_prompt(),
            history=_full_history(),
            passages=_full_passages(),
            user_id="user-1",
        )

    # Everything sent on the first model request: instructions, the replayed
    # history and the question with its data.
    first_request = next(
        i
        for i, m in enumerate(msgs)
        if isinstance(m, ModelRequest) and m.instructions is not None
    )
    sent = msgs[: first_request + 1]
    assert any(
        isinstance(m, ModelResponse) and isinstance(m.parts[0], TextPart) for m in sent
    ), "history was not replayed, so the test is not measuring it"
    tokens = sum(_message_chars(m) for m in sent) / _CHARS_PER_TOKEN

    assert tokens <= _TUNABLES.token_limits.coaching_max_input_tokens, (
        f"worst-case coaching input is ~{tokens:.0f} tokens, over the "
        f"{_TUNABLES.token_limits.coaching_max_input_tokens} budget"
    )
