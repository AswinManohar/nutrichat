"""Intent routing for a fresh chat message: GLiDE judgment, Gemini second opinion."""

from __future__ import annotations

import asyncio
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict

from backend import tracing
from backend.agent.llm import FLASH_LITE_MODEL, make_llm
from backend.agent.routing.system_one import RoutingJudgment
from backend.config import get_tunables

_TUNABLES = get_tunables()

_INTENT_SYSTEM = _TUNABLES.prompts.intent_system

RoutePath = Literal["judgment", "second_opinion_unsure", "second_opinion_unavailable"]


class _IntentResult(BaseModel):
    type: Literal["log_meal", "coaching"]

    model_config = ConfigDict(extra="forbid")


class RouteDecision(BaseModel):
    """How one fresh message was routed (see specs/001-jev-intent-routing)."""

    intent: Literal["log_meal", "coaching"]
    path: RoutePath
    judgment: RoutingJudgment | None
    offer_to_log: bool

    model_config = ConfigDict(extra="forbid")

    def routing_record(self) -> dict[str, float | str | bool] | None:
        """Values stored in coaching_response.parsed_query["routing"].

        ``needs_guidance_jev`` keeps its name from when Jev was the judge, so
        the series stays in one key; ``judge_model`` says who answered.

        None when the judge gave no answer, so there is nothing to compare with
        Gemini's needs_guidance (spec Story 5, scenario 4).
        """
        if self.judgment is None:
            return None
        return {
            "path": self.path,
            "certainty": round(self.judgment.certainty, 4),
            "raw_choice": self.judgment.raw_choice,
            "reports_food": round(self.judgment.reports_food, 4),
            "needs_guidance_jev": round(self.judgment.needs_guidance, 4),
            "offer_to_log": self.offer_to_log,
            "judge_model": self.judgment.model,
        }


# Gemini flash-lite spends thinking tokens from this same budget before the
# structured JSON — too low a limit truncates output (see tunables.yaml).
_intent_llm = make_llm(
    FLASH_LITE_MODEL,
    max_output_tokens=_TUNABLES.token_limits.intent_classifier_max_output,
).with_structured_output(_IntentResult)


async def _classify_with_gemini(message: str) -> Literal["log_meal", "coaching"]:
    """Second opinion: the Gemini intent classifier. Never costs a usage credit."""
    with tracing.stage_span(tracing.ROUTING_SECOND_OPINION):
        result = await _intent_llm.ainvoke(
            [
                SystemMessage(content=_INTENT_SYSTEM),
                HumanMessage(content=message),
            ]
        )
    return result.type


async def route_message(
    message: str,
    judgment_task: (
        asyncio.Task[tuple[RoutingJudgment | None, str | None]] | None
    ) = None,
) -> RouteDecision:
    """Decide which handler a fresh message goes to.

    The GLiDE judgment is the single routing path. A judgment at or above
    ``glide.intent_min_probability`` is acted on directly; below it, or
    when GLiDE gave no answer, the Gemini classifier decides. No path spends a
    usage credit or looks at the user's balance; credits are spent only by
    the handler that does the requested work.

    Args:
        message: Raw user message.
        judgment_task: A ``judge_message`` task already started by the caller
            (so it overlaps other I/O). None starts no judgment, and Gemini
            decides.

    Returns:
        The route, which path decided it, and whether a coaching reply should
        end with the offer to log.
    """
    cfg = _TUNABLES.glide
    with tracing.stage_span(tracing.ROUTING_DECIDE) as span:
        if judgment_task is None:
            judgment, failure = None, "not_requested"
        else:
            judgment, failure = await judgment_task

        path: RoutePath
        if judgment is None:
            path = "second_opinion_unavailable"
            intent = await _classify_with_gemini(message)
        elif judgment.certainty >= cfg.intent_min_probability:
            path = "judgment"
            intent = judgment.intent
        else:
            path = "second_opinion_unsure"
            intent = await _classify_with_gemini(message)

        decision = RouteDecision(
            intent=intent,
            path=path,
            judgment=judgment,
            offer_to_log=(
                intent == "coaching"
                and judgment is not None
                and judgment.reports_food >= cfg.log_offer_min_probability
            ),
        )
        span.set_attribute("path", path)
        span.set_attribute("intent", intent)
        span.set_attribute("offer_to_log", decision.offer_to_log)
        if failure is not None:
            span.set_attribute("failure", failure)
        if judgment is not None:
            span.set_attribute("certainty", judgment.certainty)
            span.set_attribute("raw_choice", judgment.raw_choice)
            span.set_attribute("reports_food", judgment.reports_food)
            span.set_attribute("needs_guidance_jev", judgment.needs_guidance)
            span.set_attribute("judgment_ms", judgment.latency_ms)
            span.set_attribute("judge_model", judgment.model)
            span.set_attribute("judgment_input_tokens", judgment.input_tokens)
    return decision
