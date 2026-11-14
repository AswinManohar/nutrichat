"""Layer 3 of the reply guard: a GLiDE judgment on a prose reply.

Layers 1-2 (safety/reply_guard.py) match words. This one asks whether the
reply actually suggests the user eat something containing a food they must
avoid, so a warning ("skip the peanuts") is not treated like a suggestion. It
runs only when the reply names a food, no word matched, and the patient has a
food constraint, so most turns do not pay for it.

Sent to GLiDE: the reply text and the names of the foods to avoid. No user id,
history or profile. Neither is logged.

Never raises for service problems: with no answer, layers 1-2 stand.
"""

from __future__ import annotations

import logging

import httpx
import logfire

from backend.agent import glide
from backend.agent.food import usda_local
from backend.agent.glide import GlideUnavailable, noul
from backend.config import get_tunables
from backend.safety import reply_guard
from backend.safety.checker import Failure
from backend.safety.matching import term_rules
from backend.safety.profile import HardEntry
from backend.safety.reply_guard import GuardVerdict
from backend.safety.tables import ClinicalTables

logger = logging.getLogger(__name__)

_SAFETY = get_tunables().safety
# Idle connections are kept so the judgment does not pay a TLS handshake.
_KEEPALIVE_EXPIRY_S = 600.0
_KEY = "suggests_avoided_food"

_QUESTION = noul(
    instructions=(
        "`reply` was written by a nutrition assistant to a user who must avoid "
        "the foods in `avoid`. Does `reply` suggest, recommend or offer that "
        "the user eat or drink something that contains any food in `avoid`?"
    ),
    criteria={
        "true": (
            "The reply proposes a meal, dish, ingredient or swap containing an "
            "avoided food, e.g. avoid 'peanut' with reply 'Try pad thai with "
            "crushed peanuts on top'; avoid 'milk' with reply 'A latte would "
            "work well'."
        ),
        "false": (
            "The reply does not suggest an avoided food. A warning, a refusal "
            "or a reminder to avoid it is not a suggestion, e.g. avoid "
            "'peanut' with reply 'Skip the peanuts and use sunflower seeds'; "
            "avoid 'milk' with reply 'I kept this dairy free'."
        ),
    },
)

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient | None:
    """The process-wide client, or None when no API key is configured."""
    global _client
    if _client is None:
        _client = glide.make_client(
            _SAFETY.reply_judge_timeout_s,
            limits=httpx.Limits(keepalive_expiry=_KEEPALIVE_EXPIRY_S),
        )
    return _client


async def judge(reply: str, avoid: list[str]) -> float | None:
    """P(the reply suggests an avoided food), or None when GLiDE gave no answer.

    Args:
        reply: The assistant's prose reply.
        avoid: Names of the foods the patient must avoid.

    Returns:
        A probability, or None (no API key, timeout, error).
    """
    client = _get_client()
    if client is None:
        return None
    try:
        response = await glide.ask(
            client,
            {"reply": reply, "avoid": ", ".join(avoid)},
            {_KEY: _QUESTION},
        )
        return response.noul(_KEY)
    except GlideUnavailable as exc:
        logger.warning("GLiDE reply judgment unavailable: %s", exc.reason)
        return None


async def guard(
    text: str, entries: list[HardEntry], tables: ClinicalTables
) -> GuardVerdict:
    """Run all three layers on a reply, cheapest first.

    Args:
        text: The reply.
        entries: The patient's live hard entries; only confirmed ones bind.
        tables: Clinical tables.

    Returns:
        The verdict; ``violations`` is empty when the reply may be shown.

    Raises:
        TablesUnavailable: A confirmed entry names a group the tables lack.
        FoodDbUnavailable: The USDA database cannot be read.
    """
    with logfire.span("reply_guard") as span:
        verdict = await reply_guard.scan(text, entries, tables, usda_local.lookup)
        span.set_attribute("layer", verdict.layer)
        if verdict.violations or not verdict.food_phrases:
            return verdict
        rules = term_rules(entries, tables)
        avoid = list(dict.fromkeys(r.name for r in rules))
        probability = await judge(text, avoid)
        if probability is None:
            span.set_attribute("layer_skipped", "glide")
            return verdict
        span.set_attribute("glide_probability", probability)
        verdict = verdict.model_copy(update={"glide_probability": probability})
        if probability < _SAFETY.reply_guard_min_probability:
            return verdict
        violation = Failure(
            rule="allergen"
            if any(r.rule == "allergen" for r in rules)
            else rules[0].rule,
            entry_id=None,
            detail=f"reply suggests a food containing {', '.join(avoid)}",
        )
        return verdict.model_copy(
            update={
                "violations": [violation],
                "layer": "glide",
                "retry_reason": reply_guard.retry_reason([violation]),
            }
        )
