"""Span names and one helper for tracing a turn in Logfire.

Convention:

* A span name is ``<area>.<step>`` and follows the package layout under
  ``agent/`` (``routing``, ``meal_logging``, ``food``, ``coaching``,
  ``memory``, ``safety``). The root span of a chat turn is plain ``turn``.
* Attributes are ids, counts (``n_*``), enums and timings (``*_ms``). Never
  the user's message, a reply, a food's free text or image data: spans are
  exported, and the red-flag screen and spec 013 FR-015 already promise that
  message text stays out of telemetry.
* Names live here, so a span can be found by grepping one file. Call sites
  open spans with :func:`stage_span` instead of ``logfire.span``.

Two names are fixed by their consumers and keep their spelling:
``invoke_agent meal_logging`` (Logfire's Agents view reads that exact name
and its ``gen_ai.*`` attributes) and ``memory.apply_ops``.
"""

from __future__ import annotations

from typing import Any

import logfire

TURN = "turn"
ROUTING_DECIDE = "routing.decide"
ROUTING_SECOND_OPINION = "routing.second_opinion"
SAFETY_RED_FLAG_SCREEN = "safety.red_flag_screen"
MEMORY_READBACK_REPLY = "memory.readback_reply"
MEMORY_APPLY_OPS = "memory.apply_ops"
MEAL_LOGGING_AGENT = "invoke_agent meal_logging"
MEAL_LOGGING_RESOLVE_INGREDIENT = "meal_logging.resolve_ingredient"
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
