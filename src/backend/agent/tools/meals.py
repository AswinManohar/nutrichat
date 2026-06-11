from __future__ import annotations

import json
import re
import uuid

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text as sa_text

from backend.agent.llm import make_llm
from backend.config import get_tunables
from backend.db.redis_client import increment_today
from backend.db.session import get_session
from backend.workers.tasks import embed_meal_summary

_TUNABLES = get_tunables()

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

_EXTRACTION_SYSTEM = _TUNABLES.prompts.extraction_system
_CLASSIFY_SYSTEM = _TUNABLES.prompts.image_classify_system
_CORRECTION_SYSTEM = _TUNABLES.prompts.correction_system


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
        if r.fdc_id == -1:
            lines.append(f"  ❌ {r.food_name} ({r.qty_g:.0f}g) — not found in USDA")
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


async def _insert_meal_log(
    user_id: str,
    meal_type: str,
    usda_results: list,
    totals: dict,
) -> str:
    """Insert a meal_log row and return the generated meal_id."""
    meal_id = str(uuid.uuid4())
    entities = [r.model_dump() for r in usda_results]
    async with get_session()() as session:
        await session.execute(
            sa_text(
                "INSERT INTO meal_log "
                "(meal_id, user_id, meal_type, kcal, protein_g, carbs_g, "
                "fat_g, fiber_g, entities) "
                "VALUES (:meal_id, :user_id, :meal_type, :kcal, :protein_g, :carbs_g, "
                ":fat_g, :fiber_g, CAST(:entities AS jsonb))"
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
            },
        )
        await session.commit()
    return meal_id


async def log_meal(
    user_id: str,
    usda_results: list,
    meal_type: str = "unspecified",
) -> MealLogResult:
    """Persist confirmed meal to Postgres and increment Redis daily totals.

    Args:
        user_id: Supabase Auth UUID.
        usda_results: Confirmed USDAResult list (fdc_id=-1 items excluded).
        meal_type: breakfast | lunch | snack | dinner | unspecified.

    Returns:
        MealLogResult with meal_id, totals, and confirmation message.
    """
    resolved = [r for r in usda_results if r.fdc_id != -1]
    totals = {
        "kcal": round(sum(r.kcal for r in resolved), 1),
        "protein_g": round(sum(r.protein_g for r in resolved), 1),
        "carbs_g": round(sum(r.carbs_g for r in resolved), 1),
        "fat_g": round(sum(r.fat_g for r in resolved), 1),
        "fiber_g": round(sum(r.fiber_g for r in resolved), 1),
    }
    meal_id = await _insert_meal_log(user_id, meal_type, resolved, totals)
    await increment_today(
        user_id,
        kcal=totals["kcal"],
        protein_g=totals["protein_g"],
        fiber_g=totals["fiber_g"],
    )
    embed_meal_summary.delay(meal_id)
    return MealLogResult(
        meal_id=meal_id,
        meal_type=meal_type,
        n_items=len(resolved),
        **totals,
        message=(
            f"Logged {totals['kcal']:.0f} kcal, "
            f"{totals['protein_g']:.0f}g protein, "
            f"{totals['fiber_g']:.0f}g fiber"
        ),
    )
