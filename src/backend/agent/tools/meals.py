from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from kombu.exceptions import OperationalError
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text as sa_text

from backend.agent.llm import make_llm
from backend.config import get_tunables
from backend.db.redis_client import increment_today
from backend.db.session import get_session
from backend.workers.tasks import embed_meal_summary

logger = logging.getLogger(__name__)

_TUNABLES = get_tunables()

# ---------------------------------------------------------------------------
# Meal categories
# ---------------------------------------------------------------------------

MealCategory = Literal["breakfast", "brunch", "lunch", "dinner", "snack"]
MEAL_CATEGORIES: tuple[str, ...] = (
    "breakfast",
    "brunch",
    "lunch",
    "dinner",
    "snack",
)

_CATEGORY_TZ = ZoneInfo(_TUNABLES.day.timezone)


def _meal_type_from_hour(hour: int) -> str:
    """Map a 24h clock hour to a meal category (deterministic fallback).

    Mirrors the browser-side default used to pre-select the confirmation
    card so server-inferred categories agree with the UI.

    Args:
        hour: Hour of day in 0-23.

    Returns:
        One of MEAL_CATEGORIES.
    """
    if 5 <= hour < 11:
        return "breakfast"
    if hour == 11:
        return "brunch"
    if 12 <= hour < 15:
        return "lunch"
    if 15 <= hour < 17:
        return "snack"
    if 17 <= hour < 22:
        return "dinner"
    return "snack"


def normalize_meal_type(value: str | None) -> str:
    """Return a valid meal category, falling back to the server clock.

    The web UI always sends an explicit, user-picked category. This guards
    other entry points (e.g. Telegram) and rejects junk values by inferring
    from the current hour in the configured timezone.

    Args:
        value: Candidate category (any case) or None.

    Returns:
        One of MEAL_CATEGORIES.
    """
    if value and value.strip().lower() in MEAL_CATEGORIES:
        return value.strip().lower()
    return _meal_type_from_hour(datetime.now(_CATEGORY_TZ).hour)

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class FoodEntity(BaseModel):
    food_name: str = Field(
        description="USDA-style food name, e.g. 'egg whole cooked scrambled'"
    )
    qty_g: float = Field(gt=0, description="Gram weight of the portion")
    unit: str = Field(description="Original unit: cup, tablespoon, piece, etc.")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    is_composite: bool = Field(
        default=False,
        description=(
            "True for a prepared/multi-ingredient dish that should be broken "
            "into ingredients (biryani, pasta dishes, curries, sandwiches, "
            "smoothies, stir-fries); false for a whole/standard single food "
            "(apple, chicken breast, cooked rice, milk)."
        ),
    )
    # Set by auto_decompose_node, NOT emitted by the LLM: the composite dish
    # this ingredient was broken out of. Drives the Combine action + label.
    source_dish: str | None = None

    model_config = ConfigDict(extra="forbid")


class ExtractionResult(BaseModel):
    entities: list[FoodEntity]


class ImageClassification(BaseModel):
    is_food: bool
    food_items: list[str]
    ingredients: list[str]
    reason: str | None = None


class MealLogResult(BaseModel):
    meal_id: str
    meal_type: str
    n_items: int
    kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float
    message: str


# ---------------------------------------------------------------------------
# LLM setup
# ---------------------------------------------------------------------------

_extraction_llm = make_llm().with_structured_output(ExtractionResult)
_classifier_llm = make_llm().with_structured_output(ImageClassification)
_correction_llm = make_llm().with_structured_output(ExtractionResult)
_log_reply_llm = make_llm()

_EXTRACTION_SYSTEM = _TUNABLES.prompts.extraction_system
_CLASSIFY_SYSTEM = _TUNABLES.prompts.image_classify_system
_CORRECTION_SYSTEM = _TUNABLES.prompts.correction_system
_LOG_REPLY_SYSTEM = _TUNABLES.prompts.log_reply_system


# ---------------------------------------------------------------------------
# LLM functions
# ---------------------------------------------------------------------------


def extract_entities(text: str) -> ExtractionResult:
    """Parse a free-text meal description into structured food entities.

    Args:
        text: Raw meal description from the user.

    Returns:
        ExtractionResult with a list of FoodEntity.
    """
    return _extraction_llm.invoke(
        [
            SystemMessage(content=_EXTRACTION_SYSTEM),
            HumanMessage(content=text),
        ]
    )


def classify_food_image(image_b64: str) -> ImageClassification:
    """Identify food items and ingredients from a base64-encoded image.

    Args:
        image_b64: Base64-encoded image string (JPEG or PNG).

    Returns:
        ImageClassification with is_food, food_items, ingredients.
    """
    return _classifier_llm.invoke(
        [
            SystemMessage(content=_CLASSIFY_SYSTEM),
            HumanMessage(
                content=[
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                    },
                    {
                        "type": "text",
                        "text": "List all food items and ingredients visible.",
                    },
                ]
            ),
        ]
    )


def apply_correction(entities: list[dict], correction: str) -> ExtractionResult:
    """Apply a user correction to the current entity list.

    Args:
        entities: Current list of FoodEntity dicts (from state).
        correction: User's correction message.

    Returns:
        Updated ExtractionResult.
    """
    system = (
        _CORRECTION_SYSTEM + f"\n\nCurrent entities:\n{json.dumps(entities, indent=2)}"
    )
    return _correction_llm.invoke(
        [
            SystemMessage(content=system),
            HumanMessage(content=correction),
        ]
    )


# ---------------------------------------------------------------------------
# Confirmation card + intent classifier
# ---------------------------------------------------------------------------

_CONFIRM_KEYWORDS = frozenset(_TUNABLES.routing.confirm_keywords)
_REJECT_KEYWORDS = frozenset(_TUNABLES.routing.reject_keywords)


def format_confirmation_card(usda_results: list) -> str:
    """Format a human-readable confirmation card from USDA results.

    Args:
        usda_results: List of USDAResult from usda_lookup_batch.

    Returns:
        Formatted string ready to send to the user.
    """
    lines = []
    totals = {
        "kcal": 0.0,
        "protein_g": 0.0,
        "carbs_g": 0.0,
        "fat_g": 0.0,
        "fiber_g": 0.0,
    }

    for r in usda_results:
        if r.fdc_id == -1 and not r.estimated:
            lines.append(f"  ❌ {r.food_name} ({r.qty_g:.0f}g) — not found in USDA")
            continue

        if r.estimated:
            lines.append(
                f"  ≈ {r.food_name} ({r.qty_g:.0f}g) — estimated (not in USDA) — "
                f"{r.kcal:.0f} kcal · {r.protein_g:.0f}g protein · "
                f"{r.fiber_g:.0f}g fiber"
            )
            for key in totals:
                totals[key] += getattr(r, key)
            continue

        flag = (
            " ⚠"
            if r.match_confidence < _TUNABLES.usda.low_confidence_flag_below
            else ""
        )
        cand = ""
        if (
            r.match_confidence < _TUNABLES.usda.suggest_alternative_below
            and len(r.candidates) > 1
        ):
            # First comma-segment of the next-best candidate, e.g.
            # "Bananas, overripe, raw" -> "bananas".
            alternative = r.candidates[1].split(",")[0].strip().lower()
            cand = (
                f'\n     ↳ Matched: "{r.food_name}" — say "use {alternative}" to switch'
            )
        lines.append(
            f"  • {r.food_name} ({r.qty_g:.0f}g){flag} — "
            f"{r.kcal:.0f} kcal · {r.protein_g:.0f}g protein · "
            f"{r.fiber_g:.0f}g fiber{cand}"
        )
        for key in totals:
            totals[key] += getattr(r, key)

    body = "\n".join(lines)
    summary = (
        f"\n  Total: {totals['kcal']:.0f} kcal · {totals['protein_g']:.0f}g protein · "
        f"{totals['carbs_g']:.0f}g carbs · {totals['fat_g']:.0f}g fat · "
        f"{totals['fiber_g']:.0f}g fiber"
    )
    footer = "\n\nDoes this look right? Confirm, correct any item, or cancel."
    return body + summary + footer


def classify_intent(message: str) -> str:
    """Classify user response as confirm / correct / reject — no LLM.

    Args:
        message: User's reply to the confirmation card.

    Returns:
        "confirm", "reject", or "correct".
    """
    lowered = message.lower().strip()
    # Strip punctuation for word-level matching
    cleaned = re.sub(r"[^\w\s]", "", lowered)
    words = set(cleaned.split())
    # Check multi-word phrases first (substring match), then individual words
    for kw in _CONFIRM_KEYWORDS:
        if " " in kw and kw in lowered:
            return "confirm"
        if kw in words:
            return "confirm"
    for kw in _REJECT_KEYWORDS:
        if " " in kw and kw in lowered:
            return "reject"
        if kw in words:
            return "reject"
    return "correct"


# ---------------------------------------------------------------------------
# log_meal
# ---------------------------------------------------------------------------


def _is_junk(result) -> bool:
    """Flag a USDAResult as junk food via per-100g nutrient density.

    Junk when (sugar dense AND fiber poor) OR saturated-fat dense —
    thresholds in tunables.yaml `junk` section. Whole fruit escapes via
    the fiber floor.
    """
    if result.qty_g <= 0:
        return False
    per100 = 100.0 / result.qty_g
    junk = _TUNABLES.junk
    sugar_dense = result.sugar_g * per100 >= junk.sugar_density_g
    fiber_poor = result.fiber_g * per100 < junk.fiber_floor_g
    sat_fat_dense = result.sat_fat_g * per100 >= junk.sat_fat_density_g
    return (sugar_dense and fiber_poor) or sat_fat_dense


def _junk_flags(usda_results: list) -> dict:
    """Build the meal_log.flags payload from resolved USDA results."""
    junk_items = [r.food_name for r in usda_results if _is_junk(r)]
    return {"has_junk": bool(junk_items), "junk_items": junk_items}


async def _generate_log_reply(
    label: str,
    totals: dict,
    junk_items: list[str],
) -> str:
    """Generate a short personalized confirmation message via LLM.

    Falls back to a static summary if the LLM call fails so the log
    response is never blocked by a model error.

    Args:
        label: Human-facing meal name (e.g. "chicken biryani").
        totals: Dict with kcal, protein_g, fiber_g.
        junk_items: List of food names flagged as junk.

    Returns:
        Two-line confirmation string.
    """
    user_msg = (
        f"Meal: {label}\n"
        f"Nutrition: {totals['kcal']:.0f} kcal, "
        f"{totals['protein_g']:.0f}g protein, "
        f"{totals['fiber_g']:.0f}g fiber\n"
        f"Junk items: {', '.join(junk_items) if junk_items else 'none'}"
    )
    try:
        result = await _log_reply_llm.ainvoke(
            [
                SystemMessage(content=_LOG_REPLY_SYSTEM),
                HumanMessage(content=user_msg),
            ]
        )
        return result.content.strip()
    except Exception:
        return (
            f"{label} logged. "
            f"{totals['kcal']:.0f} kcal, "
            f"{totals['protein_g']:.0f}g protein."
        )


def _meal_label(entities: list[dict]) -> str:
    """Human-facing dish-name snapshot for meal_log.label.

    Uses source_dish where an entity came from decomposing a composite dish,
    else its food_name; deduplicates while preserving first-seen order.

    Args:
        entities: Logged entity dicts (FoodEntity/USDAResult shape).

    Returns:
        Comma-joined dish/food names, e.g. "chicken biryani, apple".
    """
    names: list[str] = []
    for e in entities:
        name = e.get("source_dish") or e.get("food_name")
        if name and name not in names:
            names.append(name)
    return ", ".join(names)


async def _insert_meal_log(
    user_id: str,
    meal_type: str,
    usda_results: list,
    totals: dict,
    label: str | None = None,
) -> str:
    """Insert a meal_log row and return the generated meal_id."""
    meal_id = str(uuid.uuid4())
    entities = [r.model_dump() for r in usda_results]
    flags = _junk_flags(usda_results)
    async with get_session()() as session:
        await session.execute(
            sa_text(
                "INSERT INTO meal_log "
                "(meal_id, user_id, meal_type, kcal, protein_g, carbs_g, "
                "fat_g, fiber_g, entities, flags, label) "
                "VALUES (:meal_id, :user_id, :meal_type, :kcal, :protein_g, "
                ":carbs_g, :fat_g, :fiber_g, CAST(:entities AS jsonb), "
                "CAST(:flags AS jsonb), :label)"
            ),
            {
                "meal_id": meal_id,
                "user_id": user_id,
                "meal_type": meal_type,
                "kcal": totals["kcal"],
                "protein_g": totals["protein_g"],
                "carbs_g": totals["carbs_g"],
                "fat_g": totals["fat_g"],
                "fiber_g": totals["fiber_g"],
                "entities": json.dumps(entities),
                "flags": json.dumps(flags),
                "label": label,
            },
        )
        await session.commit()
    return meal_id


async def log_meal(
    user_id: str,
    usda_results: list,
    meal_type: str = "unspecified",
    label: str | None = None,
) -> MealLogResult:
    """Persist confirmed meal to Postgres and increment Redis daily totals.

    Args:
        user_id: Supabase Auth UUID.
        usda_results: Confirmed USDAResult list (fdc_id=-1 items excluded).
        meal_type: breakfast | lunch | snack | dinner | unspecified.

    Returns:
        MealLogResult with meal_id, totals, and confirmation message.
    """
    # LLM estimates also carry fdc_id=-1 (no real FDC row) but ARE usable
    # nutrition data — only exclude true misses (no estimate either).
    resolved = [r for r in usda_results if r.fdc_id != -1 or r.estimated]
    totals = {
        "kcal": round(sum(r.kcal for r in resolved), 1),
        "protein_g": round(sum(r.protein_g for r in resolved), 1),
        "carbs_g": round(sum(r.carbs_g for r in resolved), 1),
        "fat_g": round(sum(r.fat_g for r in resolved), 1),
        "fiber_g": round(sum(r.fiber_g for r in resolved), 1),
    }
    junk_items = _junk_flags(resolved)["junk_items"]

    async def _persist() -> str:
        """Insert the row, bump Redis, enqueue the embedding; return meal_id."""
        meal_id = await _insert_meal_log(user_id, meal_type, resolved, totals, label)
        await increment_today(
            user_id,
            kcal=totals["kcal"],
            protein_g=totals["protein_g"],
            fiber_g=totals["fiber_g"],
        )
        # Best-effort embedding for history search; a broker outage (e.g. Redis
        # down) must never fail the meal log the user just confirmed.
        try:
            embed_meal_summary.delay(meal_id)
        except (OperationalError, OSError) as exc:
            logger.warning("Could not enqueue meal embedding: %s", exc)
        return meal_id

    # The confirmation reply depends only on label/totals/junk (not meal_id), so
    # generate it concurrently with the writes — confirm latency is then
    # max(write, llm) instead of their sum.
    meal_id, reply = await asyncio.gather(
        _persist(),
        _generate_log_reply(
            label=label or "Meal", totals=totals, junk_items=junk_items
        ),
    )
    return MealLogResult(
        meal_id=meal_id,
        meal_type=meal_type,
        n_items=len(resolved),
        **totals,
        message=reply,
    )


async def soft_delete_meal(meal_id: str, user_id: str) -> bool:
    """Mark a meal_log row as deleted without removing it.

    The `meal_log_set_updated_at` trigger bumps `updated_at`, which lets the
    integration API surface this as a tombstone on the next poll.

    Args:
        meal_id: UUID of the meal to delete.
        user_id: Supabase Auth UUID — scopes the update to the owner.

    Returns:
        True if a row was updated, False if no matching row was found.
    """
    async with get_session()() as session:
        result = await session.execute(
            sa_text(
                "UPDATE meal_log SET deleted_at = now() "
                "WHERE meal_id = :meal_id AND user_id = :user_id "
                "AND deleted_at IS NULL"
            ),
            {"meal_id": meal_id, "user_id": user_id},
        )
        await session.commit()
    return result.rowcount > 0
