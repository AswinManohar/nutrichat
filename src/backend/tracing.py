"""Span names and one helper for tracing a turn in Logfire.

Convention:

* A span name is ``<area>.<step>`` and follows the package layout under
  ``agent/`` (``routing``, ``meal_logging``, ``food``, ``coaching``,
  ``memory``, ``safety``). The root span of a chat turn is plain ``turn``.
* Attributes are ids, counts (``n_*``), enums and timings (``*_ms``). Never
  the user's message, a reply, a food's free text or image data. The spans
  opened here are exported, and the red-flag screen (spec 013 FR-015) must
  not leak message text through them. Prompts and completions are captured
  separately, by the LangChain and Pydantic AI instrumentation.
* Names live here, so a span can be found by grepping one file. Call sites
  open spans with :func:`stage_span` instead of ``logfire.span``.

Two names are fixed by their consumers and keep their spelling:
``invoke_agent meal_logging`` (Logfire's Agents view reads that exact name
and its ``gen_ai.*`` attributes) and ``memory.apply_ops``.
"""

from __future__ import annotations

from typing import Any

import logfire
from opentelemetry import trace

TURN = "turn"
ROUTING_DECIDE = "routing.decide"
ROUTING_SECOND_OPINION = "routing.second_opinion"
SAFETY_RED_FLAG_SCREEN = "safety.red_flag_screen"
MEMORY_READBACK_REPLY = "memory.readback_reply"
MEMORY_APPLY_OPS = "memory.apply_ops"
MEAL_LOGGING_AGENT = "invoke_agent meal_logging"
MEAL_LOGGING_RESOLVE_INGREDIENT = "meal_logging.resolve_ingredient"
FOOD_LOOKUP_BATCH = "food.lookup_batch"
FOOD_RESOLVE = "food.resolve"
MEAL_LOGGING_CARD_CHECK = "meal_logging.card_check"
GLIDE_ASK = "glide.ask"
COACHING_CONTEXT = "coaching.context"
COACHING_FETCH_DATA = "coaching.fetch_data"
COACHING_RETRIEVE = "coaching.retrieve"
MEMORY_EXTRACT_TURN = "memory.extract_turn"
MEMORY_CURATE_TURN = "memory.curate_turn"
MEMORY_INFER_LOG_HABITS = "memory.infer_log_habits"
COACHING_TURN = "coaching.turn"
COACHING_SUGGEST_MEAL = "coaching.suggest_meal"
COACHING_CHECK_RECIPE = "coaching.check_recipe"
COACHING_REPLY_GUARD = "coaching.reply_guard"


def stage_span(name: str, **attributes: Any) -> logfire.LogfireSpan:
    """Open a span for one named stage of a turn.

    Args:
        name: One of the constants in this module.
        **attributes: Span attributes; ids, counts, enums and timings only.

    Returns:
        A context manager yielding the span.
    """
    return logfire.span(name, **attributes)


def record_handled(exc: BaseException, *, stage: str) -> None:
    """Record a failure that was caught and replaced by a fallback.

    Adds an ``exception`` event carrying the exception type to the open span
    and tags the span with ``handled_error=<stage>``, without marking the
    span as failed: the turn went on. The exception's message and traceback
    are left out, because a validation error can echo the user's text.

    Args:
        exc: The exception that was caught.
        stage: Short name of the step that fell back, for example
            ``extract_entities``.
    """
    span = trace.get_current_span()
    span.add_event("exception", {"exception.type": type(exc).__qualname__})
    span.set_attribute("handled_error", stage)


def set_current_attribute(key: str, value: str | int | float | bool) -> None:
    """Set an attribute on whichever span is open right now.

    For a caller that runs inside a span it does not own, such as the branch a
    coaching turn took. A no-op when no span is recording.

    Args:
        key: Attribute name.
        value: An id, count, enum, flag or timing, never text from the user.
    """
    trace.get_current_span().set_attribute(key, value)
