"""Resolve one free-text ingredient edit (swap or add) into a card item.

Stateless service behind ``POST /my-meals/resolve-ingredient``. It spends one
usage credit, asks the LLM for exactly one food (structured output), applies
the server-side grams rule and looks nutrition up with ``usda_lookup_batch``.
See specs/006-edit-saved-meals/research.md R7-R9.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import Literal

import logfire
from google.api_core.exceptions import GoogleAPIError
from google.genai.errors import APIError as GenaiAPIError
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.agent.llm import make_llm
from backend.agent.tools.meals import FoodEntity
from backend.agent.tools.usda import USDAResult, usda_lookup_batch
from backend.config import get_tunables
from backend.quota import consume_llm_credit

_REPLACE_SYSTEM = get_tunables().prompts.replace_ingredient_system
_LLM_TIMEOUT_S = 10


class ReplacementFood(BaseModel):
    """One food the model found in the user's text."""

    food_name: str = Field(description="USDA-style, specific food name")
    qty_g: float = Field(gt=0, description="Gram weight for the amount")
    unit: str = Field(description="Original unit as said: cup, tbsp, g, serving")
    amount_stated: bool = Field(
        description="True only if the user's text gives an amount"
    )

    model_config = ConfigDict(extra="forbid")


class ReplacementResult(BaseModel):
    """Structured LLM output; the server enforces exactly one food."""

    foods: list[ReplacementFood]


class ReplacingIngredient(BaseModel):
    """The saved-meal row being swapped out."""

    food_name: str
    qty_g: float = Field(gt=0)
    unit: str = "g"


class ResolvedIngredient(BaseModel):
    """Service result returned to the route."""

    item: USDAResult
    unit: str
    amount_stated: bool
    kept_previous_qty: bool
    model_food_name: str = ""  # the LLM's name, before USDA matching (for evals)


class QuotaExhausted(Exception):
    """Raised when the user has no usage credit left; the LLM is not called."""


class RephraseRequired(Exception):
    """Raised when the text did not yield exactly one valid food."""


class ResolveUnavailable(Exception):
    """Raised when the LLM call failed or timed out; the client may retry."""


_replace_llm = make_llm().with_structured_output(ReplacementResult)


def _build_message(
    mode: str,
    text: str,
    meal_name: str,
    replacing: ReplacingIngredient | None,
) -> str:
    """Build the single human message (research R8 context)."""
    lines = [f"mode: {mode}", f"meal: {json.dumps(meal_name)}"]
    if mode == "swap" and replacing is not None:
        lines.append(f"replacing: {json.dumps(replacing.model_dump())}")
    lines.append(f"user_text: {json.dumps(text)}")
    return "\n".join(lines)


async def resolve_ingredient(
    user_id: str,
    mode: Literal["swap", "add"],
    text: str,
    meal_name: str,
    replacing: ReplacingIngredient | None,
    *,
    consume_credit: Callable[[str], Awaitable[bool]] = consume_llm_credit,
) -> ResolvedIngredient:
    """Turn free text into one resolved card item.

    Args:
        user_id: Authenticated user, charged one credit.
        mode: "swap" replaces ``replacing``; "add" appends a new food.
        text: The user's free text (never logged, only its length).
        meal_name: Saved meal name, given to the model as context.
        replacing: Row being replaced; required context for swap.
        consume_credit: Credit check, injectable for evals and tests.

    Returns:
        The resolved item plus unit, amount_stated and kept_previous_qty.

    Raises:
        QuotaExhausted: No credit left (no LLM call is made).
        RephraseRequired: Zero or several foods, or invalid model output.
        ResolveUnavailable: LLM error or timeout.
    """
    started = time.monotonic()
    with logfire.span("resolve_ingredient", mode=mode, text_len=len(text)) as span:
        if not await consume_credit(user_id):
            raise QuotaExhausted()

        messages = [
            SystemMessage(content=_REPLACE_SYSTEM),
            HumanMessage(content=_build_message(mode, text, meal_name, replacing)),
        ]
        try:
            result = await asyncio.wait_for(
                _replace_llm.ainvoke(messages), timeout=_LLM_TIMEOUT_S
            )
        except (ValidationError, OutputParserException) as exc:
            raise RephraseRequired() from exc
        except (TimeoutError, GenaiAPIError, GoogleAPIError) as exc:
            raise ResolveUnavailable() from exc

        # A None/invalid structured result means the model gave no usable foods.
        foods = getattr(result, "foods", None)
        n_foods = len(foods) if foods is not None else 0
        span.set_attribute("n_foods", n_foods)
        if n_foods != 1:
            raise RephraseRequired()
        food = foods[0]

        kept = mode == "swap" and not food.amount_stated and replacing is not None
        if kept:
            final_g, unit = replacing.qty_g, replacing.unit
        else:
            final_g, unit = food.qty_g, food.unit

        entity = FoodEntity(food_name=food.food_name, qty_g=final_g, unit=unit)
        item = (await usda_lookup_batch([entity]))[0]

        latency_ms = int((time.monotonic() - started) * 1000)
        span.set_attributes(
            {
                "amount_stated": food.amount_stated,
                "source": item.source,
                "estimated": item.estimated,
                "latency_ms": latency_ms,
            }
        )
        return ResolvedIngredient(
            item=item,
            unit=unit,
            amount_stated=food.amount_stated,
            kept_previous_qty=kept,
            model_food_name=food.food_name,
        )
