"""Routing judgment for a fresh chat message (Fastino GLiDE, System One).

GLiDE returns calibrated probabilities for fixed questions instead of
generated text, so the orchestrator can act on how sure the judgment is. One
request per fresh message asks three questions (they share the same state
and one round trip):

- ``intent``: is the user reporting food, asking the coach, or neither?
- ``reports_food``: does a question also report food they just ate? Drives the
  offer to log on coaching replies.
- ``needs_guidance``: recorded next to Gemini's decision for later comparison;
  never acted on.

Only the message text is sent: no user id, history, goals or conditions.
Question wording is mirrored in specs/009-migrate-jev-to-glide/contracts/
glide-routing-request.md. Change both together and re-run the eval gate.

``judge_message`` never raises for service problems: it returns ``None`` plus a
reason, and the caller routes with the Gemini classifier instead.

Until October 2026 this judgment came from TypeSafe Jev; stored routing
records keep the ``needs_guidance_jev`` key and carry ``judge_model`` to tell
the two apart.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from backend.agent import glide
from backend.agent.glide import GlideUnavailable, Questions, choice, noul
from backend.config import get_tunables

logger = logging.getLogger(__name__)

_CONFIG = get_tunables().glide

# httpx drops an idle connection after 5 s by default, and a fresh TLS
# handshake costs several hundred ms against the 0.8 s routing timeout, so
# idle connections are kept for 10 minutes.
_KEEPALIVE_EXPIRY_S = 600.0
# A cold model answers 425 until it has warmed up (about a minute).
_WARMING_REASON = "http_425"
_WARMING_WAIT_S = 60.0

Intent = Literal["log_meal", "coaching"]

_INTENT_QUESTION = choice(
    instructions=(
        "`message` was sent by a user to a nutrition-tracking assistant. "
        "What is the user doing in `message`?"
    ),
    criteria={
        "log_meal": {
            "covers": (
                "Reporting or naming food or drink they ate, drank, are eating, "
                "or are about to eat, so that it can be recorded. A bare food, "
                "drink, or dish name with no verb and no question is a report, "
                "with or without a quantity."
            ),
            "excludes": (
                "Any question or request for advice, even when it mentions "
                "food. A food name that contains a nutrient word is still a "
                "report, not a question about that nutrient."
            ),
            "examples": [
                "oatmeal with blueberries",
                "greek yogurt",
                "I had chicken tikka masala and naan for lunch",
                "a high protein yogurt",
                "half a glass of 3.8% fat milk",
            ],
        },
        "coaching": {
            "covers": (
                "Asking a question or requesting help about nutrition: totals, "
                "history, trends, goals, progress, whether a food is healthy, "
                "what to eat, meal plans, or advice."
            ),
            "excludes": "Statements that only report what was eaten.",
            "examples": [
                "how much protein did I eat last week?",
                "what food do I eat the most?",
                "is oatmeal good for cholesterol?",
                "plan my remaining meals to hit my goals",
                "suggest a high-fiber snack",
            ],
        },
        "other": (
            "A greeting, thanks, small talk, or anything that is neither a "
            "food report nor a nutrition question."
        ),
    },
)

_REPORTS_FOOD_QUESTION = noul(
    instructions=(
        "Does `message` state that the user ate, drank, is eating, or is about "
        "to eat a specific food or drink at a specific meal or moment?"
    ),
    criteria={
        "true": (
            "Names something they had or are having now, e.g. 'I had pizza, "
            "was that bad?', 'just ate two donuts, how bad is that'."
        ),
        "false": (
            "Only asks about a food in general, about their totals or history, "
            "or for advice, without saying they ate a specific thing just now, "
            "e.g. 'is pizza healthy?', 'how much protein have I had today?'."
        ),
    },
)

_NEEDS_GUIDANCE_QUESTION = noul(
    instructions=(
        "Assume `message` is addressed to a nutrition coach. Does answering it "
        "call for a dietary recommendation or a judgment about what is healthy "
        "or appropriate, rather than only reading back the user's own logged "
        "data?"
    ),
)

ROUTING_QUESTIONS: Questions = {
    "intent": _INTENT_QUESTION,
    "reports_food": _REPORTS_FOOD_QUESTION,
    "needs_guidance": _NEEDS_GUIDANCE_QUESTION,
}


class RoutingJudgment(BaseModel):
    """What GLiDE said about one message (see data-model.md)."""

    intent: Intent
    certainty: float = Field(ge=0.5, le=1.0)
    raw_choice: Literal["log_meal", "coaching", "other"]
    reports_food: float = Field(ge=0.0, le=1.0)
    needs_guidance: float = Field(ge=0.0, le=1.0)
    latency_ms: float = Field(ge=0.0)
    model: str
    input_tokens: int = Field(ge=0)

    model_config = ConfigDict(extra="forbid")


_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient | None:
    """Return the process-wide client, or None when no API key is configured."""
    global _client
    if _client is None:
        _client = glide.make_client(
            _CONFIG.request_timeout_s,
            limits=httpx.Limits(keepalive_expiry=_KEEPALIVE_EXPIRY_S),
        )
    return _client


def warn_if_unconfigured() -> None:
    """Log one startup warning when GLiDE routing is not configured."""
    if not glide.api_key():
        logger.warning(
            "%s is not set: every fresh message will be routed by the Gemini "
            "classifier instead of GLiDE",
            glide.API_KEY_ENV,
        )


async def warm_up() -> None:
    """Open the connection at startup so the first real message is not cold.

    The first request of a process pays DNS + TLS, and a cold model answers
    425 until it has loaded; either would push the first users' messages
    past the routing timeout onto the Gemini path. Sends one canned message
    with a generous timeout, and once more after a wait if the model was
    still warming. Never raises.
    """
    client = _get_client()
    if client is None:
        return
    for attempt in range(2):
        start = time.perf_counter()
        try:
            await glide.ask(
                client,
                {"message": "warm up"},
                ROUTING_QUESTIONS,
                timeout_s=_CONFIG.warm_up_timeout_s,
            )
        except GlideUnavailable as exc:
            logger.warning("GLiDE warm-up failed: %s", exc.reason)
            if exc.reason != _WARMING_REASON or attempt:
                return
            await asyncio.sleep(_WARMING_WAIT_S)
            continue
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info("GLiDE warm-up took %.0f ms", elapsed_ms)
        return


async def judge_message(message: str) -> tuple[RoutingJudgment | None, str | None]:
    """Ask GLiDE how to route one fresh message.

    Routing is decided on P(log_meal) against everything else, because
    ``coaching`` and ``other`` share a handler: probability split between those
    two is not routing uncertainty, so the response's own ``confidence``
    (margin between the top two of three options) would understate how sure
    the route is.

    Args:
        message: The user's raw text.

    Returns:
        ``(judgment, None)`` on success, or ``(None, reason)`` where reason is
        ``"not_configured"``, ``"malformed_response"``, ``"timeout"``,
        ``"http_<status>"`` or a transport exception class name. Never raises
        for service errors; re-raises cancellation.
    """
    client = _get_client()
    if client is None:
        return None, "not_configured"

    start = time.perf_counter()
    try:
        response = await glide.ask(client, {"message": message}, ROUTING_QUESTIONS)
        raw_choice, probabilities = response.choice("intent")
        p_log = probabilities["log_meal"]
        judgment = RoutingJudgment(
            intent="log_meal" if p_log >= 0.5 else "coaching",
            certainty=max(p_log, 1.0 - p_log),
            raw_choice=raw_choice,
            reports_food=response.noul("reports_food"),
            needs_guidance=response.noul("needs_guidance"),
            latency_ms=(time.perf_counter() - start) * 1000,
            model=response.model,
            input_tokens=response.input_tokens,
        )
    except asyncio.CancelledError:
        raise
    except GlideUnavailable as exc:
        # Reason only: the message text must not reach logs (spec FR-015).
        logger.warning("GLiDE routing unavailable: %s", exc.reason)
        return None, exc.reason
    except (KeyError, ValueError) as exc:
        # KeyError: the log_meal option is missing; ValueError: pydantic
        # rejected an out-of-range probability or an unknown choice.
        logger.warning("GLiDE routing response malformed: %s", type(exc).__name__)
        return None, "malformed_response"
    return judgment, None
