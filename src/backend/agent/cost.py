"""LLM cost tracking for Pydantic AI agent runs.

Prices each Pydantic AI run with `genai-prices` (offline price table, no
network) and emits the cost two ways:

  * a Logfire log-point (`llm_cost`) nested under the active span, so the
    dollar figure shows up inline in the trace tree next to the agent run;
  * a Logfire metric counter (`gen_ai.cost_usd`), labelled by model and
    operation, for aggregate dashboards ("total spend today").

Token counts come straight from the run's `RunUsage`. Unknown models (e.g.
the embedding model, which is not a Pydantic AI agent) are skipped without
raising — cost tracking must never break a user request.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import logfire
from genai_prices import calc_price

if TYPE_CHECKING:
    from pydantic_ai.agent import AgentRunResult

logger = logging.getLogger(__name__)

# Gemini is served by the "google" provider in the genai-prices table.
_PROVIDER_ID = "google"

# Aggregatable spend counter. Created once; buffered until logfire.configure().
_cost_counter = logfire.metric_counter(
    "gen_ai.cost_usd",
    unit="USD",
    description="Estimated LLM spend per Pydantic AI run, by model/operation.",
)


def record_run_cost(
    result: AgentRunResult,
    model_ref: str,
    *,
    operation: str,
) -> None:
    """Price a Pydantic AI run and emit cost telemetry to Logfire.

    Args:
        result: The value returned by `Agent.run()`.
        model_ref: The model name passed to the agent (e.g. COACHING_MODEL).
        operation: Short label for the call site (e.g. "parse_query"),
            used as a metric dimension.
    """
    usage = result.usage
    try:
        price = calc_price(usage, model_ref=model_ref, provider_id=_PROVIDER_ID)
    except LookupError:
        # Model not in the price table (e.g. embeddings) — token usage is
        # still captured by instrument_pydantic_ai; just skip the dollar figure.
        logger.debug("No price entry for model_ref=%s; skipping cost", model_ref)
        return

    total_usd = float(price.total_price)
    matched_model = price.model.id if price.model is not None else model_ref

    logfire.info(
        "llm_cost",
        operation=operation,
        model=model_ref,
        priced_as=matched_model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        input_usd=float(price.input_price),
        output_usd=float(price.output_price),
        cost_usd=total_usd,
    )
    _cost_counter.add(total_usd, {"model": matched_model, "operation": operation})


__all__ = ["record_run_cost"]
