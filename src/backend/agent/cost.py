"""LLM cost tracking for Pydantic AI runs and LangChain chat-model calls.

Prices each call with `genai-prices` (offline price table, no
network) and emits the cost two ways:

  * a Logfire log-point (`llm_cost`) nested under the active span, so the
    dollar figure shows up inline in the trace tree next to the agent run;
  * a Logfire metric counter (`gen_ai.cost_usd`), labelled by model and
    operation, for aggregate dashboards ("total spend today").

Token counts come from the run's `RunUsage` (Pydantic AI) or from the
response's `usage_metadata` (LangChain, via `LlmCostCallback`). Unknown models (e.g.
the embedding model, which is not a Pydantic AI agent) are skipped without
raising — cost tracking must never break a user request.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import logfire
from genai_prices import Usage, calc_price
from langchain_core.callbacks import BaseCallbackHandler

if TYPE_CHECKING:
    from genai_prices.types import AbstractUsage
    from langchain_core.outputs import LLMResult
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


def _emit_cost(model_ref: str, operation: str, usage: AbstractUsage) -> None:
    """Price one LLM call and emit the ``llm_cost`` record and the counter.

    Args:
        model_ref: The model name the call used.
        operation: Short label for the call site, a metric dimension.
        usage: Token counts of the call.
    """
    try:
        price = calc_price(usage, model_ref=model_ref, provider_id=_PROVIDER_ID)
    except LookupError:
        # Model not in the price table (e.g. embeddings) — token usage is
        # still captured by instrument_pydantic_ai; just skip the dollar figure.
        logger.debug("No price entry for model_ref=%s; skipping cost", model_ref)
        return
    except Exception:  # noqa: BLE001 — cost telemetry must not break a request
        logger.warning("could not price %s call", operation, exc_info=True)
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
    _emit_cost(model_ref, operation, result.usage)


class LlmCostCallback(BaseCallbackHandler):
    """LangChain callback that prices each chat-model call it sees.

    Attach it to a model constructor (``make_llm(operation=...)``). The model's
    own callbacks fire for its run whatever chain wraps it, so this also
    covers ``.with_structured_output(...)`` and calls made in a worker thread.

    Args:
        model_ref: The model name the calls use.
        operation: Short label for the call site, a metric dimension.
    """

    # Priced in the caller's context, so the record nests under its span.
    run_inline = True

    def __init__(self, model_ref: str, operation: str) -> None:
        self._model_ref = model_ref
        self._operation = operation

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """Emit the cost of a finished call; never raises into the call."""
        try:
            usage = _usage_of(response)
            if usage is None:
                logger.debug("No usage on %s response; skipping cost", self._operation)
                return
            _emit_cost(self._model_ref, self._operation, usage)
        except Exception:  # noqa: BLE001 — cost telemetry must not break a call
            logger.warning("cost record failed for %s", self._operation, exc_info=True)


def _usage_of(response: LLMResult) -> Usage | None:
    """Token counts from the first generation's ``usage_metadata``, if any."""
    try:
        message = getattr(response.generations[0][0], "message", None)
    except IndexError:
        return None
    metadata = getattr(message, "usage_metadata", None)
    if not metadata:
        return None
    cache_read = (metadata.get("input_token_details") or {}).get("cache_read") or None
    return Usage(
        input_tokens=metadata.get("input_tokens"),
        output_tokens=metadata.get("output_tokens"),
        cache_read_tokens=cache_read,
    )


__all__ = ["LlmCostCallback", "record_run_cost"]
