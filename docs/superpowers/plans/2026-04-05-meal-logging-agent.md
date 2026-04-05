# Meal Logging Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the full meal logging agent — text + image input, USDA batch lookup with Postgres cache, correction loop, and LangGraph graph with interrupt-based confirmation.

**Architecture:** Strict sequential LangGraph graph where LLM nodes (Flash-Lite) only do NLP (extract, classify, apply_correction) and Python nodes handle all I/O (USDA API, DB writes, Redis). Graph interrupts after `present` node; resumes on next user message routed to confirm/correct/reject.

**Tech Stack:** LangGraph 1.1.4, langchain-google-genai (Flash-Lite), aiohttp, SQLAlchemy async, asyncpg, Redis, Pydantic v2.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `src/backend/agent/tools/meals.py` | Rewrite | FoodEntity, ExtractionResult, ImageClassification, extract_entities, classify_food_image, apply_correction, format_confirmation_card, classify_intent, log_meal |
| `src/backend/agent/tools/usda.py` | Rewrite | NutrientValue, USDAResult, usda_lookup_batch, Postgres cache logic |
| `src/backend/db/session.py` | Create | Async SQLAlchemy engine + session factory |
| `src/backend/agent/graph.py` | Rewrite | Full AgentState + all graph nodes + interrupt wiring |
| `src/backend/agent/orchestrator.py` | Rewrite | handle_message with proper config |
| `tests/test_usda_tools.py` | Create | usda_lookup_batch tests |
| `tests/test_meal_tools.py` | Create | extract, classify, apply_correction, format_card, classify_intent, log_meal tests |
| `tests/test_graph.py` | Create | End-to-end graph tests |

---

## Task 1: DB session factory

**Files:**
- Create: `src/backend/db/session.py`

- [ ] **Step 1: Write the file**

```python
# src/backend/db/session.py
from __future__ import annotations

import os
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@lru_cache(maxsize=1)
def _engine():
    return create_async_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)


def get_session() -> async_sessionmaker[AsyncSession]:
    """Return a cached async session factory. Call inside async functions."""
    return async_sessionmaker(_engine(), class_=AsyncSession, expire_on_commit=False)
```

- [ ] **Step 2: Verify import**

```bash
DATABASE_URL=postgresql+asyncpg://nutrichat:nutrichat@127.0.0.1:5411/nutrichat \
  uv run python -c "from backend.db.session import get_session; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**
```bash
git add src/backend/db/session.py
git commit -m "feat: async DB session factory"
```

---

## Task 2: Pydantic models

**Files:**
- Modify: `src/backend/agent/tools/meals.py`
- Modify: `src/backend/agent/tools/usda.py`
- Create: `tests/test_meal_tools.py`

- [ ] **Step 1: Write failing model tests**

```python
# tests/test_meal_tools.py
from backend.agent.tools.meals import FoodEntity, ExtractionResult, ImageClassification
from backend.agent.tools.usda import NutrientValue, USDAResult


def test_food_entity_defaults():
    e = FoodEntity(food_name="egg", qty_g=61.0, unit="piece")
    assert e.confidence == 1.0


def test_food_entity_rejects_zero_qty():
    import pytest
    with pytest.raises(Exception):
        FoodEntity(food_name="egg", qty_g=0.0, unit="piece")


def test_usda_result_has_nutrients():
    r = USDAResult(
        fdc_id=1, food_name="egg", qty_g=61.0,
        match_confidence=0.9, candidates=[],
        kcal=87.0, protein_g=6.0, carbs_g=0.6,
        fat_g=6.0, fiber_g=0.0, sugar_g=0.6, sat_fat_g=1.6,
        nutrients={"Vitamin C": NutrientValue(amount=0.0, unit="mg")},
    )
    assert r.nutrients["Vitamin C"].amount == 0.0


def test_image_classification_no_food():
    ic = ImageClassification(
        is_food=False, food_items=[], ingredients=[], reason="No food visible"
    )
    assert not ic.is_food
```

- [ ] **Step 2: Run — expect ImportError**

```bash
uv run pytest tests/test_meal_tools.py -v 2>&1 | head -20
```

- [ ] **Step 3: Write models in meals.py**

```python
# src/backend/agent/tools/meals.py
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class FoodEntity(BaseModel):
    food_name: str = Field(description="USDA-style food name, e.g. 'egg whole cooked scrambled'")
    qty_g: float = Field(gt=0, description="Gram weight of the portion")
    unit: str = Field(description="Original unit: cup, tablespoon, piece, etc.")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    class Config:
        extra = "forbid"


class ExtractionResult(BaseModel):
    entities: list[FoodEntity]


class ImageClassification(BaseModel):
    is_food: bool
    food_items: list[str]
    ingredients: list[str]
    reason: Optional[str] = None
```

- [ ] **Step 4: Write models in usda.py**

```python
# src/backend/agent/tools/usda.py
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel


class NutrientValue(BaseModel):
    amount: float
    unit: str  # g, mg, mcg, kcal


class USDAResult(BaseModel):
    fdc_id: int
    food_name: str
    qty_g: float
    match_confidence: float
    candidates: list[str]

    # Promoted macros — scaled to qty_g
    kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float
    sugar_g: float
    sat_fat_g: float

    # Full nutrient breakdown scaled to qty_g
    nutrients: dict[str, NutrientValue]


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
```

- [ ] **Step 5: Run tests — expect PASS**

```bash
uv run pytest tests/test_meal_tools.py -v
```
Expected: 4 passed.

- [ ] **Step 6: Commit**
```bash
git add src/backend/agent/tools/ tests/test_meal_tools.py
git commit -m "feat: pydantic models for meal logging agent"
```

---

## Task 3: USDA lookup batch

**Files:**
- Modify: `src/backend/agent/tools/usda.py`
- Create: `tests/test_usda_tools.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_usda_tools.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend.agent.tools.meals import FoodEntity
from backend.agent.tools.usda import usda_lookup_batch, USDAResult

MOCK_FDC_RESPONSE = {
    "foods": [{
        "fdcId": 172187,
        "description": "Egg, whole, cooked, scrambled",
        "foodNutrients": [
            {"nutrientName": "Energy", "value": 149.0, "unitName": "kcal"},
            {"nutrientName": "Protein", "value": 9.99, "unitName": "g"},
            {"nutrientName": "Carbohydrate, by difference", "value": 1.61, "unitName": "g"},
            {"nutrientName": "Total lipid (fat)", "value": 11.2, "unitName": "g"},
            {"nutrientName": "Fiber, total dietary", "value": 0.0, "unitName": "g"},
            {"nutrientName": "Total Sugars", "value": 1.22, "unitName": "g"},
            {"nutrientName": "Fatty acids, total saturated", "value": 3.34, "unitName": "g"},
            {"nutrientName": "Vitamin C, total ascorbic acid", "value": 0.0, "unitName": "mg"},
        ],
    }]
}


@pytest.mark.asyncio
async def test_cache_miss_hits_fdc():
    entity = FoodEntity(food_name="scrambled egg", qty_g=100.0, unit="g")
    mock_resp = AsyncMock()
    mock_resp.json = AsyncMock(return_value=MOCK_FDC_RESPONSE)
    mock_resp.raise_for_status = MagicMock()
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.agent.tools.usda._cache_lookup", return_value=None), \
         patch("backend.agent.tools.usda._cache_write", return_value=None), \
         patch("aiohttp.ClientSession.get", return_value=mock_resp):
        results = await usda_lookup_batch([entity])

    assert len(results) == 1
    assert results[0].fdc_id == 172187
    assert results[0].kcal == pytest.approx(149.0)  # 100g * 149/100


@pytest.mark.asyncio
async def test_scales_nutrients_to_qty_g():
    entity = FoodEntity(food_name="scrambled egg", qty_g=61.0, unit="piece")
    mock_resp = AsyncMock()
    mock_resp.json = AsyncMock(return_value=MOCK_FDC_RESPONSE)
    mock_resp.raise_for_status = MagicMock()
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.agent.tools.usda._cache_lookup", return_value=None), \
         patch("backend.agent.tools.usda._cache_write", return_value=None), \
         patch("aiohttp.ClientSession.get", return_value=mock_resp):
        results = await usda_lookup_batch([entity])

    assert results[0].kcal == pytest.approx(149.0 * 61 / 100, rel=0.01)


@pytest.mark.asyncio
async def test_usda_miss_returns_error_result():
    entity = FoodEntity(food_name="xyzzy_nonexistent_food", qty_g=100.0, unit="g")
    empty_resp = AsyncMock()
    empty_resp.json = AsyncMock(return_value={"foods": []})
    empty_resp.raise_for_status = MagicMock()
    empty_resp.__aenter__ = AsyncMock(return_value=empty_resp)
    empty_resp.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.agent.tools.usda._cache_lookup", return_value=None), \
         patch("backend.agent.tools.usda._cache_write", return_value=None), \
         patch("aiohttp.ClientSession.get", return_value=empty_resp):
        results = await usda_lookup_batch([entity])

    assert results[0].fdc_id == -1
    assert results[0].match_confidence == 0.0
```

- [ ] **Step 2: Run — expect ImportError/AttributeError**
```bash
uv run pytest tests/test_usda_tools.py -v 2>&1 | head -20
```

- [ ] **Step 3: Implement usda_lookup_batch**

```python
# src/backend/agent/tools/usda.py  (append after models)
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import aiohttp
from sqlalchemy import select, text

from backend.agent.tools.meals import FoodEntity
from backend.db.session import get_session
from backend.db.models import FoodSource

logger = logging.getLogger(__name__)

USDA_SEARCH_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"

_MACRO_MAP = {
    "Energy": "kcal",
    "Protein": "protein_g",
    "Carbohydrate, by difference": "carbs_g",
    "Total lipid (fat)": "fat_g",
    "Fiber, total dietary": "fiber_g",
    "Total Sugars": "sugar_g",
    "Fatty acids, total saturated": "sat_fat_g",
}


async def _cache_lookup(food_name: str) -> Optional[dict]:
    """Check Postgres food_source for a matching food name (case-insensitive)."""
    async with get_session()() as session:
        result = await session.execute(
            select(FoodSource).where(
                FoodSource.food_name.ilike(f"%{food_name}%")
            ).limit(1)
        )
        row = result.scalar_one_or_none()
        if row:
            return {"fdc_id": row.fdc_id, "food_name": row.food_name,
                    "nutrients": row.nutrients}
    return None


async def _cache_write(fdc_id: int, food_name: str, nutrients: dict) -> None:
    """Write a new food_source row. Silently ignores duplicate fdc_id."""
    async with get_session()() as session:
        await session.execute(
            text(
                "INSERT INTO food_source (fdc_id, food_name, nutrients, nutrients_count, source_db) "
                "VALUES (:fdc_id, :name, :nutrients, :count, 'FDC') "
                "ON CONFLICT (fdc_id) DO NOTHING"
            ),
            {"fdc_id": fdc_id, "name": food_name,
             "nutrients": nutrients, "count": len(nutrients)},
        )
        await session.commit()


def _scale(nutrients_per_100g: dict, qty_g: float) -> dict[str, NutrientValue]:
    scale = qty_g / 100.0
    return {
        name: NutrientValue(amount=round(val * scale, 3), unit=unit)
        for name, (val, unit) in nutrients_per_100g.items()
    }


def _confidence(query: str, description: str) -> float:
    """Jaccard similarity between query words and FDC description words."""
    a = set(query.lower().split())
    b = set(description.lower().split())
    if not a or not b:
        return 0.5
    return len(a & b) / len(a | b)


def _parse_fdc_response(data: dict, entity: FoodEntity) -> Optional[USDAResult]:
    foods = data.get("foods", [])
    if not foods:
        return None

    top = foods[0]
    raw_nutrients: dict[str, tuple[float, str]] = {}
    for n in top.get("foodNutrients", []):
        name = n.get("nutrientName", "")
        raw_nutrients[name] = (n.get("value", 0.0), n.get("unitName", "g").lower())

    scale = entity.qty_g / 100.0
    macros = {}
    for fdc_name, field in _MACRO_MAP.items():
        val, _ = raw_nutrients.get(fdc_name, (0.0, "g"))
        macros[field] = round(val * scale, 2)

    nutrients = {
        name: NutrientValue(amount=round(val * scale, 3), unit=unit)
        for name, (val, unit) in raw_nutrients.items()
    }

    candidates = [f["description"] for f in foods[:3]]
    confidence = _confidence(entity.food_name, top["description"])

    return USDAResult(
        fdc_id=top["fdcId"],
        food_name=top["description"],
        qty_g=entity.qty_g,
        match_confidence=confidence,
        candidates=candidates,
        **macros,
        nutrients=nutrients,
    )


async def _fetch_one(
    session: aiohttp.ClientSession, entity: FoodEntity
) -> USDAResult:
    """Fetch one entity: cache-first, FDC on miss, write cache on miss."""
    cached = await _cache_lookup(entity.food_name)
    if cached:
        nutrients_per_100g = {
            name: (v["amount"] if isinstance(v, dict) else v, "g")
            for name, v in cached["nutrients"].items()
        }
        scale = entity.qty_g / 100.0
        nutrients = {
            name: NutrientValue(amount=round(val * scale, 3), unit=unit)
            for name, (val, unit) in nutrients_per_100g.items()
        }
        macros = {
            field: round(nutrients_per_100g.get(fdc_name, (0.0, "g"))[0] * scale, 2)
            for fdc_name, field in _MACRO_MAP.items()
        }
        return USDAResult(
            fdc_id=cached["fdc_id"],
            food_name=cached["food_name"],
            qty_g=entity.qty_g,
            match_confidence=0.95,
            candidates=[],
            **macros,
            nutrients=nutrients,
        )

    api_key = os.environ.get("USDA_API_KEY", "DEMO_KEY")
    params = {
        "api_key": api_key,
        "query": entity.food_name,
        "dataType": "Foundation,SR Legacy",
        "pageSize": 5,
    }

    for attempt in range(2):
        try:
            async with session.get(
                USDA_SEARCH_URL, params=params,
                timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
            break
        except (aiohttp.ClientTimeout, aiohttp.ClientError) as exc:
            if attempt == 1:
                logger.error("FDC request failed after retry: %s", exc)
                return _miss_result(entity)
            await asyncio.sleep(1.0)

    result = _parse_fdc_response(data, entity)
    if result is None:
        return _miss_result(entity)

    # Cache raw per-100g nutrients
    raw_per_100g = {
        n["nutrientName"]: {"amount": n.get("value", 0.0), "unit": n.get("unitName", "g")}
        for n in data["foods"][0].get("foodNutrients", [])
    }
    await _cache_write(result.fdc_id, result.food_name, raw_per_100g)
    return result


def _miss_result(entity: FoodEntity) -> USDAResult:
    return USDAResult(
        fdc_id=-1, food_name=entity.food_name, qty_g=entity.qty_g,
        match_confidence=0.0, candidates=[],
        kcal=0.0, protein_g=0.0, carbs_g=0.0, fat_g=0.0,
        fiber_g=0.0, sugar_g=0.0, sat_fat_g=0.0, nutrients={},
    )


async def usda_lookup_batch(entities: list[FoodEntity]) -> list[USDAResult]:
    """Fetch USDA nutrients for multiple entities in parallel.

    Checks Postgres food_source cache first. Falls back to FDC API on miss
    and writes the result back to cache.

    Args:
        entities: List of FoodEntity with food_name and qty_g.

    Returns:
        List of USDAResult — one per entity, in same order. Failed lookups
        return a result with fdc_id=-1 and match_confidence=0.0.
    """
    async with aiohttp.ClientSession() as session:
        return list(await asyncio.gather(
            *[_fetch_one(session, e) for e in entities]
        ))
```

- [ ] **Step 4: Run tests**
```bash
uv run pytest tests/test_usda_tools.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**
```bash
git add src/backend/agent/tools/usda.py tests/test_usda_tools.py
git commit -m "feat: usda_lookup_batch with postgres cache-first and parallel FDC fetch"
```

---

## Task 4: extract_entities + classify_food_image + apply_correction

**Files:**
- Modify: `src/backend/agent/tools/meals.py`
- Modify: `tests/test_meal_tools.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_meal_tools.py`:

```python
import pytest
from unittest.mock import MagicMock, patch
from backend.agent.tools.meals import (
    extract_entities, classify_food_image, apply_correction,
    FoodEntity, ExtractionResult, ImageClassification,
)


def test_extract_entities_returns_extraction_result():
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = ExtractionResult(entities=[
        FoodEntity(food_name="scrambled egg", qty_g=122.0, unit="2 large eggs"),
        FoodEntity(food_name="whole wheat bread", qty_g=28.0, unit="slice"),
    ])
    with patch("backend.agent.tools.meals._extraction_llm", mock_llm):
        result = extract_entities("2 scrambled eggs and a slice of toast")
    assert len(result.entities) == 2
    assert result.entities[0].food_name == "scrambled egg"


def test_extract_entities_vague_quantity_low_confidence():
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = ExtractionResult(entities=[
        FoodEntity(food_name="mixed nuts", qty_g=30.0, unit="handful", confidence=0.4),
    ])
    with patch("backend.agent.tools.meals._extraction_llm", mock_llm):
        result = extract_entities("a handful of mixed nuts")
    assert result.entities[0].confidence < 0.6


def test_classify_food_image_no_food():
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = ImageClassification(
        is_food=False, food_items=[], ingredients=[], reason="No food visible"
    )
    with patch("backend.agent.tools.meals._classifier_llm", mock_llm):
        result = classify_food_image("fake_base64")
    assert not result.is_food


def test_apply_correction_quantity_change():
    entities = [
        FoodEntity(food_name="scrambled egg", qty_g=122.0, unit="2 eggs").model_dump(),
    ]
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = ExtractionResult(entities=[
        FoodEntity(food_name="scrambled egg", qty_g=183.0, unit="3 eggs"),
    ])
    with patch("backend.agent.tools.meals._correction_llm", mock_llm):
        result = apply_correction(entities, "actually 3 eggs not 2")
    assert result.entities[0].qty_g == 183.0


def test_apply_correction_addition():
    entities = [
        FoodEntity(food_name="scrambled egg", qty_g=122.0, unit="2 eggs").model_dump(),
    ]
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = ExtractionResult(entities=[
        FoodEntity(food_name="scrambled egg", qty_g=122.0, unit="2 eggs"),
        FoodEntity(food_name="black coffee", qty_g=240.0, unit="cup"),
    ])
    with patch("backend.agent.tools.meals._correction_llm", mock_llm):
        result = apply_correction(entities, "add a cup of black coffee")
    assert len(result.entities) == 2
```

- [ ] **Step 2: Run — expect ImportError**
```bash
uv run pytest tests/test_meal_tools.py -v 2>&1 | head -20
```

- [ ] **Step 3: Implement the three LLM functions**

Append to `src/backend/agent/tools/meals.py`:

```python
import json
import os
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

_FLASH_LITE_MODEL = "gemini-2.0-flash-lite"

def _make_llm() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=_FLASH_LITE_MODEL,
        google_api_key=os.environ.get("GOOGLE_API_KEY", ""),
    )

_extraction_llm = _make_llm().with_structured_output(ExtractionResult)
_classifier_llm = _make_llm().with_structured_output(ImageClassification)
_correction_llm = _make_llm().with_structured_output(ExtractionResult)

_EXTRACTION_SYSTEM = """Extract all food items from the meal description.
Return food_name (USDA-style, specific), qty_g (gram weight), unit (original unit mentioned),
confidence (0-1, lower for vague quantities like 'some' or 'a bit').

Common conversions:
1 large egg=61g | 1 tbsp=14g | 1 cup oats cooked=234g
1 slice bread=28g | 1 medium banana=118g | 1 cup milk=244g"""

_CLASSIFY_SYSTEM = """You are a food image classifier.
Identify every distinct food item and discernible ingredient visible in the image.
If no food is present, set is_food=false and explain why in reason."""

_CORRECTION_SYSTEM = """You are updating a confirmed food entity list based on a user correction.
Apply the correction precisely:
- Quantity change ("actually 3 eggs") → update qty_g
- Addition ("add a coffee") → append new entity
- Removal ("remove the toast") → drop matching entity
- Substitution ("almond milk not oat") → replace food_name, keep qty_g
- Multiple corrections → apply all
Return the complete updated entity list."""


def extract_entities(text: str) -> ExtractionResult:
    """Parse a free-text meal description into structured food entities.

    Args:
        text: Raw meal description from the user.

    Returns:
        ExtractionResult with a list of FoodEntity.
    """
    return _extraction_llm.invoke([
        SystemMessage(content=_EXTRACTION_SYSTEM),
        HumanMessage(content=text),
    ])


def classify_food_image(image_b64: str) -> ImageClassification:
    """Identify food items and ingredients from a base64-encoded image.

    Args:
        image_b64: Base64-encoded image string (JPEG or PNG).

    Returns:
        ImageClassification with is_food, food_items, ingredients.
    """
    return _classifier_llm.invoke([
        SystemMessage(content=_CLASSIFY_SYSTEM),
        HumanMessage(content=[
            {"type": "image_url",
             "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
            {"type": "text", "text": "List all food items and ingredients visible."},
        ]),
    ])


def apply_correction(entities: list[dict], correction: str) -> ExtractionResult:
    """Apply a user correction to the current entity list.

    Args:
        entities: Current list of FoodEntity dicts (from state).
        correction: User's correction message.

    Returns:
        Updated ExtractionResult.
    """
    system = _CORRECTION_SYSTEM + f"\n\nCurrent entities:\n{json.dumps(entities, indent=2)}"
    return _correction_llm.invoke([
        SystemMessage(content=system),
        HumanMessage(content=correction),
    ])
```

- [ ] **Step 4: Run tests**
```bash
uv run pytest tests/test_meal_tools.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**
```bash
git add src/backend/agent/tools/meals.py tests/test_meal_tools.py
git commit -m "feat: extract_entities, classify_food_image, apply_correction"
```

---

## Task 5: format_confirmation_card + classify_intent + log_meal

**Files:**
- Modify: `src/backend/agent/tools/meals.py`
- Modify: `tests/test_meal_tools.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_meal_tools.py`:

```python
from backend.agent.tools.meals import (
    format_confirmation_card, classify_intent, log_meal,
)
from backend.agent.tools.usda import USDAResult, NutrientValue


def _make_usda_result(name, qty, kcal, protein, fdc_id=1, confidence=0.9) -> USDAResult:
    return USDAResult(
        fdc_id=fdc_id, food_name=name, qty_g=qty,
        match_confidence=confidence, candidates=[],
        kcal=kcal, protein_g=protein, carbs_g=5.0,
        fat_g=3.0, fiber_g=1.0, sugar_g=1.0, sat_fat_g=0.5,
        nutrients={"Vitamin C": NutrientValue(amount=0.0, unit="mg")},
    )


def test_format_card_shows_macros():
    results = [
        _make_usda_result("scrambled egg", 122.0, 182.0, 12.0),
        _make_usda_result("whole wheat bread", 28.0, 75.0, 3.0),
    ]
    card = format_confirmation_card(results)
    assert "182" in card
    assert "scrambled egg" in card.lower()
    assert "Total" in card


def test_format_card_flags_low_confidence():
    results = [_make_usda_result("mixed nuts", 30.0, 175.0, 5.0, confidence=0.5)]
    card = format_confirmation_card(results)
    assert "⚠" in card


def test_format_card_flags_usda_miss():
    results = [_make_usda_result("unknown food", 100.0, 0.0, 0.0, fdc_id=-1, confidence=0.0)]
    card = format_confirmation_card(results)
    assert "not found" in card.lower() or "❌" in card


def test_classify_intent_confirm():
    for msg in ["yes", "looks good", "correct", "log it", "confirm", "yep", "ok"]:
        assert classify_intent(msg) == "confirm", f"Expected confirm for: {msg}"


def test_classify_intent_reject():
    for msg in ["no", "cancel", "nevermind", "stop"]:
        assert classify_intent(msg) == "reject", f"Expected reject for: {msg}"


def test_classify_intent_correction():
    for msg in ["actually 3 eggs", "add a coffee", "remove the toast", "change the milk"]:
        assert classify_intent(msg) == "correct", f"Expected correct for: {msg}"


@pytest.mark.asyncio
async def test_log_meal_writes_to_db_and_redis():
    results = [_make_usda_result("scrambled egg", 122.0, 182.0, 12.0)]
    with patch("backend.agent.tools.meals.increment_today") as mock_redis, \
         patch("backend.agent.tools.meals._insert_meal_log", return_value="meal-uuid-123"):
        result = await log_meal(
            user_id="test-user", usda_results=results, meal_type="breakfast"
        )
    mock_redis.assert_called_once()
    assert result.meal_id == "meal-uuid-123"
    assert result.kcal == 182.0
```

- [ ] **Step 2: Run — expect ImportError**
```bash
uv run pytest tests/test_meal_tools.py::test_format_card_shows_macros -v 2>&1 | head -10
```

- [ ] **Step 3: Implement format_confirmation_card, classify_intent, log_meal**

Append to `src/backend/agent/tools/meals.py`:

```python
import uuid
from sqlalchemy import text as sa_text
from backend.agent.tools.usda import USDAResult
from backend.db.redis_client import increment_today
from backend.db.session import get_session

_CONFIRM_KEYWORDS = {"yes", "yep", "yeah", "correct", "right", "ok", "okay",
                     "log", "confirm", "looks good", "sure", "good", "perfect"}
_REJECT_KEYWORDS = {"no", "nope", "cancel", "nevermind", "never mind", "stop", "quit"}


def format_confirmation_card(usda_results: list[USDAResult]) -> str:
    """Format a human-readable confirmation card from USDA results.

    Args:
        usda_results: List of USDAResult from usda_lookup_batch.

    Returns:
        Formatted string ready to send to the user.
    """
    lines = []
    totals = {"kcal": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0, "fiber_g": 0.0}

    for r in usda_results:
        if r.fdc_id == -1:
            lines.append(f"  ❌ {r.food_name} ({r.qty_g:.0f}g) — not found in USDA")
            continue

        flag = " ⚠" if r.match_confidence < 0.6 else ""
        cand = ""
        if r.match_confidence < 0.85 and r.candidates:
            cand = f"\n     ↳ Matched: \"{r.food_name}\""
        lines.append(
            f"  • {r.food_name} ({r.qty_g:.0f}g){flag} — "
            f"{r.kcal:.0f} kcal · {r.protein_g:.0f}g protein · {r.fiber_g:.0f}g fiber{cand}"
        )
        for key in totals:
            totals[key] += getattr(r, key)

    body = "\n".join(lines)
    summary = (
        f"\n  Total: {totals['kcal']:.0f} kcal · {totals['protein_g']:.0f}g protein · "
        f"{totals['carbs_g']:.0f}g carbs · {totals['fat_g']:.0f}g fat · {totals['fiber_g']:.0f}g fiber"
    )
    footer = "\n\nDoes this look right? Confirm, correct any item, or cancel."
    return body + summary + footer


def classify_intent(message: str) -> str:
    """Classify user response as confirm / correct / reject (no LLM).

    Args:
        message: User's reply to the confirmation card.

    Returns:
        "confirm", "reject", or "correct".
    """
    lowered = message.lower().strip()
    words = set(lowered.split())
    if words & _CONFIRM_KEYWORDS:
        return "confirm"
    if words & _REJECT_KEYWORDS:
        return "reject"
    return "correct"


async def _insert_meal_log(
    user_id: str, meal_type: str,
    usda_results: list[USDAResult],
    totals: dict,
) -> str:
    """Insert a meal_log row and return the generated meal_id."""
    meal_id = str(uuid.uuid4())
    entities = [r.model_dump() for r in usda_results]
    async with get_session()() as session:
        await session.execute(
            sa_text(
                "INSERT INTO meal_log "
                "(meal_id, user_id, meal_type, kcal, protein_g, carbs_g, fat_g, fiber_g, entities) "
                "VALUES (:meal_id, :user_id, :meal_type, :kcal, :protein_g, :carbs_g, "
                ":fat_g, :fiber_g, :entities)"
            ),
            {
                "meal_id": meal_id, "user_id": user_id, "meal_type": meal_type,
                "kcal": totals["kcal"], "protein_g": totals["protein_g"],
                "carbs_g": totals["carbs_g"], "fat_g": totals["fat_g"],
                "fiber_g": totals["fiber_g"],
                "entities": json.dumps(entities),
            },
        )
        await session.commit()
    return meal_id


async def log_meal(
    user_id: str,
    usda_results: list[USDAResult],
    meal_type: str = "unspecified",
) -> MealLogResult:
    """Persist confirmed meal to Postgres and increment Redis daily totals.

    Args:
        user_id: Supabase Auth UUID.
        usda_results: Confirmed, resolved USDAResult list (no fdc_id=-1 items).
        meal_type: breakfast | lunch | snack | dinner | unspecified.

    Returns:
        MealLogResult with meal_id, totals, and confirmation message.
    """
    resolved = [r for r in usda_results if r.fdc_id != -1]
    totals = {
        "kcal":      round(sum(r.kcal for r in resolved), 1),
        "protein_g": round(sum(r.protein_g for r in resolved), 1),
        "carbs_g":   round(sum(r.carbs_g for r in resolved), 1),
        "fat_g":     round(sum(r.fat_g for r in resolved), 1),
        "fiber_g":   round(sum(r.fiber_g for r in resolved), 1),
    }
    meal_id = await _insert_meal_log(user_id, meal_type, resolved, totals)
    await increment_today(
        user_id, kcal=totals["kcal"], protein_g=totals["protein_g"],
        fiber_g=totals["fiber_g"],
    )
    return MealLogResult(
        meal_id=meal_id, meal_type=meal_type,
        n_items=len(resolved), **totals,
        message=(
            f"Logged {totals['kcal']:.0f} kcal, "
            f"{totals['protein_g']:.0f}g protein, "
            f"{totals['fiber_g']:.0f}g fiber"
        ),
    )
```

- [ ] **Step 4: Run tests**
```bash
uv run pytest tests/test_meal_tools.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**
```bash
git add src/backend/agent/tools/meals.py tests/test_meal_tools.py
git commit -m "feat: format_confirmation_card, classify_intent, log_meal"
```

---

## Task 6: Full LangGraph graph

**Files:**
- Modify: `src/backend/agent/graph.py`
- Create: `tests/test_graph.py`

- [ ] **Step 1: Write failing graph tests**

```python
# tests/test_graph.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend.agent.tools.meals import FoodEntity, ExtractionResult
from backend.agent.tools.usda import USDAResult, NutrientValue
from backend.agent.graph import build_graph, AgentState
from langchain_core.messages import HumanMessage


def _egg_result() -> USDAResult:
    return USDAResult(
        fdc_id=172187, food_name="scrambled egg", qty_g=122.0,
        match_confidence=0.9, candidates=[],
        kcal=182.0, protein_g=12.0, carbs_g=2.0, fat_g=13.0,
        fiber_g=0.0, sugar_g=1.0, sat_fat_g=3.5,
        nutrients={"Vitamin C": NutrientValue(amount=0.0, unit="mg")},
    )


@pytest.mark.asyncio
async def test_text_input_routes_to_extract():
    mock_extract = MagicMock(return_value=ExtractionResult(entities=[
        FoodEntity(food_name="scrambled egg", qty_g=122.0, unit="2 eggs")
    ]))
    mock_usda = AsyncMock(return_value=[_egg_result()])

    with patch("backend.agent.graph.extract_entities", mock_extract), \
         patch("backend.agent.graph.usda_lookup_batch", mock_usda):
        graph = build_graph(checkpointer=None)
        config = {"configurable": {"thread_id": "t1", "user_id": "u1"}}
        state = await graph.ainvoke(
            {"messages": [HumanMessage(content="2 scrambled eggs")],
             "user_id": "u1", "image_b64": None,
             "entities": [], "usda_results": [], "meal_type": None},
            config,
        )

    assert len(state["usda_results"]) == 1
    assert "182" in state["messages"][-1].content


@pytest.mark.asyncio
async def test_image_input_routes_to_classify_then_extract():
    from backend.agent.tools.meals import ImageClassification
    mock_classify = MagicMock(return_value=ImageClassification(
        is_food=True, food_items=["scrambled eggs"], ingredients=[], reason=None
    ))
    mock_extract = MagicMock(return_value=ExtractionResult(entities=[
        FoodEntity(food_name="scrambled egg", qty_g=122.0, unit="portion")
    ]))
    mock_usda = AsyncMock(return_value=[_egg_result()])

    with patch("backend.agent.graph.classify_food_image", mock_classify), \
         patch("backend.agent.graph.extract_entities", mock_extract), \
         patch("backend.agent.graph.usda_lookup_batch", mock_usda):
        graph = build_graph(checkpointer=None)
        config = {"configurable": {"thread_id": "t2", "user_id": "u1"}}
        state = await graph.ainvoke(
            {"messages": [HumanMessage(content="[image]")],
             "user_id": "u1", "image_b64": "fake_base64",
             "entities": [], "usda_results": [], "meal_type": None},
            config,
        )

    mock_classify.assert_called_once()
    assert len(state["usda_results"]) == 1
```

- [ ] **Step 2: Run — expect ImportError**
```bash
uv run pytest tests/test_graph.py -v 2>&1 | head -20
```

- [ ] **Step 3: Implement the full graph**

```python
# src/backend/agent/graph.py
from __future__ import annotations

import json
from typing import Annotated, Any, Optional, Sequence, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from backend.agent.tools.meals import (
    FoodEntity,
    apply_correction,
    classify_food_image,
    classify_intent,
    extract_entities,
    format_confirmation_card,
    log_meal,
)
from backend.agent.tools.usda import usda_lookup_batch


class AgentState(TypedDict):
    messages:     Annotated[Sequence[BaseMessage], add_messages]
    user_id:      str
    image_b64:    Optional[str]
    entities:     list[dict]
    usda_results: list[dict]
    meal_type:    Optional[str]


# ── Nodes ─────────────────────────────────────────────────────────────────────

def node_router(state: AgentState) -> dict[str, Any]:
    """Decide path: image → classify, text → extract. No-op state change."""
    return {}


def node_classify(state: AgentState) -> dict[str, Any]:
    """Classify the image and convert identified foods to text for extract."""
    result = classify_food_image(state["image_b64"])
    if not result.is_food:
        return {
            "messages": [AIMessage(
                content="I couldn't identify any food in that image. "
                        "Could you describe the meal instead?"
            )],
            "image_b64": None,
        }
    food_text = ", ".join(result.food_items + result.ingredients)
    return {"image_b64": None, "messages": [HumanMessage(content=food_text)]}


def node_extract(state: AgentState) -> dict[str, Any]:
    """Extract food entities from the latest user message text."""
    last_text = next(
        (m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
        "",
    )
    result = extract_entities(last_text)
    return {"entities": [e.model_dump() for e in result.entities]}


async def node_usda_batch(state: AgentState) -> dict[str, Any]:
    """Run parallel USDA lookups for all entities in state."""
    food_entities = [FoodEntity(**e) for e in state["entities"]]
    results = await usda_lookup_batch(food_entities)
    return {"usda_results": [r.model_dump() for r in results]}


def node_present(state: AgentState) -> dict[str, Any]:
    """Format and return the confirmation card. Graph interrupts after this."""
    from backend.agent.tools.usda import USDAResult
    results = [USDAResult(**r) for r in state["usda_results"]]
    card = format_confirmation_card(results)
    return {"messages": [AIMessage(content=card)]}


async def node_classify_intent(state: AgentState) -> dict[str, Any]:
    """Read the user's reply to the confirmation card and classify intent."""
    last_human = next(
        (m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
        "",
    )
    intent = classify_intent(last_human)
    return {"meal_type": intent}  # reuse meal_type field to carry intent signal


async def node_apply_correction(state: AgentState) -> dict[str, Any]:
    """Apply user correction to entity list."""
    last_human = next(
        (m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
        "",
    )
    updated = apply_correction(state["entities"], last_human)
    return {"entities": [e.model_dump() for e in updated.entities]}


async def node_log(state: AgentState) -> dict[str, Any]:
    """Write confirmed meal to Postgres and increment Redis totals."""
    from backend.agent.tools.usda import USDAResult
    results = [USDAResult(**r) for r in state["usda_results"]]
    meal_result = await log_meal(
        user_id=state["user_id"],
        usda_results=results,
        meal_type=state.get("meal_type") or "unspecified",
    )
    return {
        "messages": [AIMessage(content=meal_result.message)],
        "entities": [],
        "usda_results": [],
    }


# ── Routing functions ──────────────────────────────────────────────────────────

def _route_from_router(state: AgentState) -> str:
    return "classify" if state.get("image_b64") else "extract"


def _route_from_intent(state: AgentState) -> str:
    intent = state.get("meal_type", "correct")
    if intent == "confirm":
        return "log"
    if intent == "reject":
        return END
    return "apply_correction"


def _should_continue_after_classify(state: AgentState) -> str:
    """If classify found no food, skip to END. Otherwise extract."""
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and "couldn't identify" in last.content:
        return END
    return "extract"


# ── Graph assembly ─────────────────────────────────────────────────────────────

def build_graph(checkpointer: Any = None) -> Any:
    """Build and compile the meal logging graph.

    Args:
        checkpointer: LangGraph checkpointer for multi-session persistence.

    Returns:
        Compiled LangGraph graph.
    """
    workflow = StateGraph(AgentState)

    workflow.add_node("router", node_router)
    workflow.add_node("classify", node_classify)
    workflow.add_node("extract", node_extract)
    workflow.add_node("usda_batch", node_usda_batch)
    workflow.add_node("present", node_present)
    workflow.add_node("classify_intent", node_classify_intent)
    workflow.add_node("apply_correction", node_apply_correction)
    workflow.add_node("log", node_log)

    workflow.set_entry_point("router")
    workflow.add_conditional_edges("router", _route_from_router,
                                   {"classify": "classify", "extract": "extract"})
    workflow.add_conditional_edges("classify", _should_continue_after_classify,
                                   {"extract": "extract", END: END})
    workflow.add_edge("extract", "usda_batch")
    workflow.add_edge("usda_batch", "present")
    workflow.add_edge("present", "classify_intent")
    workflow.add_conditional_edges("classify_intent", _route_from_intent,
                                   {"log": "log", "apply_correction": "apply_correction", END: END})
    workflow.add_edge("apply_correction", "usda_batch")
    workflow.add_edge("log", END)

    return workflow.compile(
        checkpointer=checkpointer,
        interrupt_after=["present"],
    )
```

- [ ] **Step 4: Run tests**
```bash
uv run pytest tests/test_graph.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**
```bash
git add src/backend/agent/graph.py tests/test_graph.py
git commit -m "feat: full meal logging graph with interrupt-based confirmation loop"
```

---

## Task 7: Update orchestrator

**Files:**
- Modify: `src/backend/agent/orchestrator.py`

- [ ] **Step 1: Rewrite orchestrator**

```python
# src/backend/agent/orchestrator.py
from __future__ import annotations

from typing import Any, Optional

from langchain_core.messages import HumanMessage

from backend.agent.graph import build_graph


async def handle_message(
    user_id: str,
    user_input: str,
    thread_id: str,
    checkpointer: Any,
    image_b64: Optional[str] = None,
) -> dict[str, Any]:
    """Entry point for the meal logging agent.

    On first message: runs graph through router → extract/classify →
    usda_batch → present, then pauses (interrupt_after present).

    On follow-up message (confirm/correct/reject): resumes from after
    present via classify_intent node.

    Args:
        user_id: Supabase Auth UUID.
        user_input: User's message text.
        thread_id: Conversation thread ID (default: user_id).
        checkpointer: AsyncPostgresSaver from app.state.
        image_b64: Optional base64 image for photo logging.

    Returns:
        Dict with status and last agent message content.
    """
    graph = build_graph(checkpointer)
    config = {"configurable": {"thread_id": thread_id, "user_id": user_id}}

    # Check if there is a pending interrupt (existing thread with usda_results)
    snapshot = await graph.aget_state(config)
    is_resuming = bool(snapshot and snapshot.next)

    if is_resuming:
        # Resume after interrupt — add the user's reply to messages
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content=user_input)]},
            config,
        )
    else:
        # Fresh invocation
        result = await graph.ainvoke(
            {
                "messages": [HumanMessage(content=user_input)],
                "user_id": user_id,
                "image_b64": image_b64,
                "entities": [],
                "usda_results": [],
                "meal_type": None,
            },
            config,
        )

    last_message = result["messages"][-1] if result.get("messages") else None
    return {
        "status": "success",
        "reply": last_message.content if last_message else "",
        "thread_id": thread_id,
    }
```

- [ ] **Step 2: Update api/meals.py to pass image_b64**

```python
# src/backend/api/meals.py
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

from backend.agent.orchestrator import handle_message

router = APIRouter(prefix="/meals", tags=["meals"])


class LogMealRequest(BaseModel):
    user_input: str
    conversation_id: Optional[str] = None
    image_b64: Optional[str] = None  # base64-encoded image for photo logging


@router.post("/log")
async def log_meal_endpoint(req: LogMealRequest, request: Request) -> dict:
    user_id = "default_user_123"  # replaced by JWT auth in Step 7
    thread_id = req.conversation_id or user_id
    checkpointer = request.app.state.checkpointer

    response = await handle_message(
        user_id=user_id,
        user_input=req.user_input,
        thread_id=thread_id,
        checkpointer=checkpointer,
        image_b64=req.image_b64,
    )
    return response
```

- [ ] **Step 3: Verify server starts**
```bash
DATABASE_URL=postgresql+asyncpg://nutrichat:nutrichat@127.0.0.1:5411/nutrichat \
REDIS_URL=redis://127.0.0.1:6379/0 \
GOOGLE_API_KEY=dummy \
uv run uvicorn backend.main:app --port 8000 2>&1 | head -5
```
Expected: `Application startup complete.`

- [ ] **Step 4: Commit**
```bash
git add src/backend/agent/orchestrator.py src/backend/api/meals.py
git commit -m "feat: orchestrator with interrupt resume + image_b64 support"
```

---

## Task 8: Notebook experiment cells

**Files:**
- Modify: `/home/aswinmanohar/foodlife/dev/notebooks/entity_agent.ipynb`

- [ ] **Step 1: Add 7 experiment cells to the notebook**

Open the notebook and add the following cells at the bottom:

**Cell — Setup**
```python
import sys
sys.path.insert(0, "/home/aswinmanohar/nutrichat/src")
import os
os.environ["GOOGLE_API_KEY"] = "YOUR_KEY_HERE"
os.environ["USDA_API_KEY"] = "DEMO_KEY"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://nutrichat:nutrichat@127.0.0.1:5411/nutrichat"
os.environ["REDIS_URL"] = "redis://127.0.0.1:6379/0"
```

**Cell 1 — extract varied inputs**
```python
from backend.agent.tools.meals import extract_entities

test_inputs = [
    "2 scrambled eggs and a slice of whole wheat toast",
    "a handful of mixed nuts",          # should have confidence < 0.6
    "big bowl of pasta with tomato sauce",  # vague portion
    "200g grilled chicken breast",
]
for inp in test_inputs:
    r = extract_entities(inp)
    for e in r.entities:
        flag = " ⚠ LOW CONFIDENCE" if e.confidence < 0.6 else ""
        print(f"  {e.food_name}: {e.qty_g}g ({e.unit}) conf={e.confidence:.2f}{flag}")
    print()
```

**Cell 2 — classify image**
```python
import base64
from backend.agent.tools.meals import classify_food_image

# Point to a real image file to test
img_path = "/path/to/food_image.jpg"
if os.path.exists(img_path):
    with open(img_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    result = classify_food_image(b64)
    print(f"is_food: {result.is_food}")
    print(f"food_items: {result.food_items}")
    print(f"ingredients: {result.ingredients}")
else:
    print("Provide an image path to test classification")
```

**Cell 3 — apply_correction**
```python
from backend.agent.tools.meals import FoodEntity, apply_correction

entities = [
    FoodEntity(food_name="scrambled egg", qty_g=122.0, unit="2 eggs").model_dump(),
    FoodEntity(food_name="whole wheat bread", qty_g=28.0, unit="slice").model_dump(),
]
corrections = [
    "actually 3 eggs not 2",
    "add a cup of black coffee",
    "remove the toast",
    "almond milk not oat milk",
]
for correction in corrections:
    result = apply_correction(entities, correction)
    print(f"Correction: '{correction}'")
    for e in result.entities:
        print(f"  {e.food_name}: {e.qty_g}g")
    print()
```

**Cell 4 — usda_lookup_batch**
```python
import asyncio
from backend.agent.tools.meals import FoodEntity
from backend.agent.tools.usda import usda_lookup_batch

entities = [
    FoodEntity(food_name="scrambled egg", qty_g=122.0, unit="2 eggs"),
    FoodEntity(food_name="whole wheat bread", qty_g=28.0, unit="slice"),
    FoodEntity(food_name="black coffee", qty_g=240.0, unit="cup"),
]
results = asyncio.run(usda_lookup_batch(entities))
for r in results:
    print(f"{r.food_name}: {r.kcal:.0f} kcal, {r.protein_g:.1f}g protein "
          f"(confidence: {r.match_confidence:.2f}, fdc_id: {r.fdc_id})")
    print(f"  Nutrients: {len(r.nutrients)} tracked")
```

**Cell 5 — format_confirmation_card**
```python
from backend.agent.tools.meals import format_confirmation_card
card = format_confirmation_card(results)
print(card)
```

**Cell 6 — full text round-trip**
```python
from backend.agent.tools.meals import extract_entities
from backend.agent.tools.usda import usda_lookup_batch
from backend.agent.tools.meals import format_confirmation_card

text = "had 2 scrambled eggs, a slice of whole wheat toast, and black coffee"
extracted = extract_entities(text)
usda_results = asyncio.run(usda_lookup_batch(extracted.entities))
card = format_confirmation_card(usda_results)
print(card)
```

**Cell 7 — classify_intent validation**
```python
from backend.agent.tools.meals import classify_intent

test_cases = [
    ("yes", "confirm"), ("looks good", "confirm"), ("log it", "confirm"),
    ("no", "reject"), ("cancel", "reject"),
    ("actually 3 eggs", "correct"), ("add a coffee", "correct"),
]
all_pass = True
for msg, expected in test_cases:
    got = classify_intent(msg)
    status = "✅" if got == expected else "❌"
    print(f"{status} '{msg}' → {got} (expected {expected})")
    if got != expected:
        all_pass = False
print("\nAll pass!" if all_pass else "\nSome failed — review classify_intent keywords")
```

- [ ] **Step 2: Run cells 1, 3, 5, 6, 7 without live API keys (mock where needed)**
- [ ] **Step 3: Run cells 2, 4 with live GOOGLE_API_KEY + USDA_API_KEY**
- [ ] **Step 4: Commit**
```bash
git add docs/
git commit -m "feat: notebook experiment cells for prompt iteration (Tasks 1-7)"
```

---

## Self-Review

**Spec coverage:**
- ✅ Graph architecture: router → classify/extract → usda_batch → present → interrupt → classify_intent → log/correct/reject
- ✅ All 7 LangGraph nodes implemented
- ✅ `extract_entities`, `classify_food_image`, `apply_correction` — Flash-Lite structured output
- ✅ `format_confirmation_card` — pure Python, macros only, ⚠ flags, ❌ miss flags
- ✅ `classify_intent` — keyword-based, no LLM
- ✅ `usda_lookup_batch` — Postgres cache-first, parallel aiohttp, retry, miss result
- ✅ `log_meal` — Postgres INSERT + Redis increment_today
- ✅ Full nutrient breakdown in USDAResult.nutrients
- ✅ Micronutrients stored, not in confirmation card
- ✅ Error handling: miss, low confidence, ambiguous, image-not-food, FDC timeout
- ✅ Correction loop: apply_correction → usda_batch → present → re-interrupt
- ✅ Notebook cells 1–7
- ✅ Tests for every function

**Type consistency:** `FoodEntity`, `ExtractionResult`, `USDAResult`, `NutrientValue`, `MealLogResult`, `ImageClassification` defined in Task 2 and used consistently throughout all tasks.

**No placeholders:** All steps contain complete code.
