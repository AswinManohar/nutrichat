# Automatic Selective Ingredient Decomposition — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-detect composite dishes (biryani, pasta) per-food and break only those into ingredients, while saved My Meals keep priority and a "Log as single item" action can revert.

**Architecture:** Extraction emits a per-entity `is_composite` flag. A new `auto_decompose_node` (between `extract` and `usda_batch`) decomposes composite entities into ingredient entities tagged with `source_dish` provenance; atomic entities pass through. A `combine_node` (triggered by `action == "combine"`) collapses tagged ingredients back to their dish. The logged meal stays a normal `meal_log` row, but a new `meal_log.label` column persists the dish name so history retrieval is a one-column lookup.

**Tech Stack:** Python 3.12, LangGraph, Pydantic, SQLAlchemy + Alembic, PostgreSQL + pgvector, Gemini Flash-Lite (extraction/decompose), React + TypeScript (frontend), pytest + pytest-asyncio.

## Global Constraints

- `from __future__ import annotations` at the top of every Python file.
- Type-annotate all functions. Pydantic models that cross a boundary keep `model_config = ConfigDict(extra="forbid")` unless a field must be optional/defaulted.
- Black (88 col) / Ruff defaults for Python; Prettier (100 col) for TS.
- Tests run with `uv run pytest` (asyncio_mode = "auto", testpaths = ["tests"]).
- Tunables (prompts, flags) live in `src/backend/config/tunables.yaml`, validated by the strict `Tunables` schema in `src/backend/config/__init__.py` (`extra="forbid"` — every new YAML key needs a schema field).
- `action` is passed verbatim from the API through `handle_message` into graph state on resume; new action values need no API validation change.
- Never break the saved-meal priority: `saved_lookup` runs first and short-circuits to `present`; auto-decompose only exists on the saved-meal-miss path.

---

### Task 1: `meal_log.label` column (migration + ORM)

**Files:**
- Create: `src/backend/db/migrations/versions/20260619_008_meal_log_label.py`
- Modify: `src/backend/db/models.py` (MealLog, ~line 87-109)
- Test: `tests/test_models_label.py`

**Interfaces:**
- Produces: `MealLog.label` attribute (`str | None`); DB column `meal_log.label text NULL`; index `ix_meal_log_user_label (user_id, label)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models_label.py
"""MealLog gains a nullable `label` column for dish-name history retrieval."""

from __future__ import annotations

from backend.db.models import MealLog


def test_meal_log_has_label_column() -> None:
    col = MealLog.__table__.columns.get("label")
    assert col is not None, "meal_log.label column missing"
    assert col.nullable is True


def test_meal_log_label_index_present() -> None:
    index_names = {ix.name for ix in MealLog.__table__.indexes}
    assert "ix_meal_log_user_label" in index_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models_label.py -v`
Expected: FAIL — `meal_log.label column missing`.

- [ ] **Step 3: Add the ORM column + index**

In `src/backend/db/models.py`, inside `class MealLog`, add the column after `entities` (line 87) — `Text` is already imported (used by `UserMeal`):

```python
    entities: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
```

In `MealLog.__table_args__`, add the index:

```python
        Index("ix_meal_log_cursor", "user_id", "updated_at", "meal_id"),
        Index("ix_meal_log_user_label", "user_id", "label"),
```

- [ ] **Step 4: Write the Alembic migration**

```python
# src/backend/db/migrations/versions/20260619_008_meal_log_label.py
"""meal_log.label — persist dish name(s) for history retrieval.

Decomposed composite dishes are logged as normal meal_log rows whose entities
are the ingredients (so "biryani" is no longer in the row). `label` snapshots
the human-facing dish name(s) at log time so "how often did I have biryani" is
a one-column lookup. Nullable; older rows stay NULL.

Revision ID: 008
Revises: 007
Create Date: 2026-06-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("meal_log", sa.Column("label", sa.Text(), nullable=True))
    op.create_index(
        "ix_meal_log_user_label", "meal_log", ["user_id", "label"]
    )


def downgrade() -> None:
    op.drop_index("ix_meal_log_user_label", table_name="meal_log")
    op.drop_column("meal_log", "label")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_models_label.py -v`
Expected: PASS (both tests).

- [ ] **Step 6: Commit**

```bash
git add src/backend/db/models.py src/backend/db/migrations/versions/20260619_008_meal_log_label.py tests/test_models_label.py
git commit -m "feat: meal_log.label column for dish-name history retrieval"
```

---

### Task 2: `FoodEntity` composite fields + extraction prompt

**Files:**
- Modify: `src/backend/agent/tools/meals.py` (`class FoodEntity`, lines 89-97)
- Modify: `src/backend/config/tunables.yaml` (`prompts.extraction_system`)
- Test: `tests/test_food_entity_composite.py`

**Interfaces:**
- Produces: `FoodEntity.is_composite: bool` (default `False`, LLM-emitted) and `FoodEntity.source_dish: str | None` (default `None`, set programmatically — never emitted by the LLM).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_food_entity_composite.py
"""FoodEntity carries composite classification + decomposition provenance."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.agent.tools.meals import FoodEntity


def test_defaults_are_atomic_and_unsourced() -> None:
    e = FoodEntity(food_name="apple", qty_g=150, unit="piece")
    assert e.is_composite is False
    assert e.source_dish is None


def test_composite_and_source_dish_round_trip() -> None:
    e = FoodEntity(
        food_name="basmati rice cooked",
        qty_g=150,
        unit="g",
        is_composite=False,
        source_dish="chicken biryani",
    )
    assert e.source_dish == "chicken biryani"
    assert e.model_dump()["source_dish"] == "chicken biryani"


def test_unknown_field_still_rejected() -> None:
    with pytest.raises(ValidationError):
        FoodEntity(food_name="apple", qty_g=1, unit="g", bogus=True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_food_entity_composite.py -v`
Expected: FAIL — `is_composite`/`source_dish` not attributes (or rejected by `extra="forbid"`).

- [ ] **Step 3: Add the fields**

In `src/backend/agent/tools/meals.py`, extend `FoodEntity` (keep `extra="forbid"`):

```python
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
```

- [ ] **Step 4: Update the extraction prompt**

In `src/backend/config/tunables.yaml`, extend `prompts.extraction_system`. Add this block after the `confidence` line (before "CRITICAL — explicit gram values:"):

```yaml
    Also return is_composite (true/false) per item:
      true  — a prepared or multi-ingredient dish with no faithful single USDA
              entry: biryani, fried rice, spaghetti bolognese, curries, stews,
              casseroles, sandwiches/burgers, smoothies, stir-fries, mixed
              salads with dressing.
      false — a whole or standard single item / recognizable USDA staple:
              apple, banana, chicken breast, cooked rice, milk, scrambled eggs,
              a slice of bread.
    When unsure, prefer false (log as a single item).
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_food_entity_composite.py tests/test_config.py -v`
Expected: PASS (entity tests pass; `test_config.py` confirms the YAML still validates against the strict schema).

- [ ] **Step 6: Commit**

```bash
git add src/backend/agent/tools/meals.py src/backend/config/tunables.yaml tests/test_food_entity_composite.py
git commit -m "feat: FoodEntity is_composite + source_dish; extraction prompt classifies dishes"
```

---

### Task 3: `USDAResult.source_dish` + propagation in `usda_batch_node`

**Files:**
- Modify: `src/backend/agent/tools/usda.py` (`class USDAResult`, ~line 61-85)
- Modify: `src/backend/agent/graph.py` (`usda_batch_node`, lines 130-136)
- Test: `tests/test_usda_source_dish.py`

**Interfaces:**
- Consumes: `FoodEntity.source_dish` (Task 2).
- Produces: `USDAResult.source_dish: str | None`; `usda_batch_node` copies each entity's `source_dish` onto the matching result (1:1, order-preserving) so it serializes into `usda_results`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_usda_source_dish.py
"""usda_batch_node propagates per-entity source_dish onto usda_results."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from backend.agent.graph import usda_batch_node
from backend.agent.tools.usda import USDAResult


def _result(food_name: str) -> USDAResult:
    return USDAResult(
        fdc_id=1,
        food_name=food_name,
        qty_g=100,
        kcal=100,
        protein_g=1,
        carbs_g=1,
        fat_g=1,
        fiber_g=1,
        match_confidence=1.0,
    )


async def test_source_dish_propagated_onto_results() -> None:
    state = {
        "entities": [
            {"food_name": "basmati rice", "qty_g": 150, "unit": "g",
             "confidence": 1.0, "is_composite": False,
             "source_dish": "chicken biryani"},
            {"food_name": "apple", "qty_g": 150, "unit": "g",
             "confidence": 1.0, "is_composite": False, "source_dish": None},
        ]
    }
    fake = AsyncMock(return_value=[_result("rice white cooked"), _result("apple raw")])
    with patch("backend.agent.graph.usda_lookup_batch", fake):
        out = await usda_batch_node(state)

    results = out["usda_results"]
    assert results[0]["source_dish"] == "chicken biryani"
    assert results[1]["source_dish"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_usda_source_dish.py -v`
Expected: FAIL — `USDAResult` has no `source_dish` (or KeyError on the dumped dict).

- [ ] **Step 3: Add the field to USDAResult**

In `src/backend/agent/tools/usda.py`, add to `class USDAResult` (after `estimated`):

```python
    source: str = "USDA"
    estimated: bool = False
    # Set by usda_batch_node from the originating FoodEntity when this result
    # came from auto-decomposing a composite dish; None otherwise.
    source_dish: str | None = None
```

- [ ] **Step 4: Propagate in `usda_batch_node`**

In `src/backend/agent/graph.py`, replace `usda_batch_node` body so it copies `source_dish` from each entity onto the 1:1 result:

```python
async def usda_batch_node(state: AgentState) -> dict:
    """Resolve all food entities against USDA FoodData Central (cache-first)."""
    from backend.agent.tools.meals import FoodEntity

    entities = [FoodEntity(**e) for e in state["entities"]]
    results = await usda_lookup_batch(entities)
    for entity, result in zip(entities, results):
        result.source_dish = entity.source_dish
    return {"usda_results": [r.model_dump() for r in results]}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_usda_source_dish.py tests/test_usda_tools.py -v`
Expected: PASS (new test passes; existing usda tests unaffected).

- [ ] **Step 6: Commit**

```bash
git add src/backend/agent/tools/usda.py src/backend/agent/graph.py tests/test_usda_source_dish.py
git commit -m "feat: propagate source_dish from entities onto usda_results"
```

---

### Task 4: `auto_decompose_node` + feature flag + graph wiring

**Files:**
- Modify: `src/backend/config/__init__.py` (add `FeaturesConfig`, wire into `Tunables`)
- Modify: `src/backend/config/tunables.yaml` (add `features:` section)
- Modify: `src/backend/agent/graph.py` (new `auto_decompose_node`; rewire `extract → auto_decompose → usda_batch`)
- Test: `tests/test_auto_decompose.py`

**Interfaces:**
- Consumes: `decompose_to_ingredients(description)` and `extract_entities(text)` from `agent.tools` (existing); `FoodEntity.is_composite`/`source_dish` (Task 2); `get_tunables().features.auto_decompose_enabled`.
- Produces: `auto_decompose_node(state) -> dict` returning `{"entities": [...]}` with composites replaced by their `source_dish`-tagged ingredient entities; graph edge `extract → auto_decompose → usda_batch`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_auto_decompose.py
"""auto_decompose_node breaks only composite entities, per-food, with fallbacks."""

from __future__ import annotations

from unittest.mock import patch

from backend.agent.graph import auto_decompose_node
from backend.agent.tools.meals import ExtractionResult, FoodEntity


def _state(entities: list[dict]) -> dict:
    return {"entities": entities}


def _entity(name: str, composite: bool, qty: float = 200) -> dict:
    return {"food_name": name, "qty_g": qty, "unit": "g",
            "confidence": 1.0, "is_composite": composite, "source_dish": None}


async def test_only_composite_decomposes_order_preserved() -> None:
    state = _state([_entity("chicken biryani", True), _entity("apple", False)])
    sub = ExtractionResult(entities=[
        FoodEntity(food_name="basmati rice cooked", qty_g=150, unit="g"),
        FoodEntity(food_name="chicken thigh", qty_g=120, unit="g"),
    ])
    with patch("backend.agent.graph.decompose_to_ingredients",
               return_value=["150 g basmati rice", "120 g chicken thigh"]), \
         patch("backend.agent.graph.extract_entities", return_value=sub):
        out = await auto_decompose_node(state)

    names = [e["food_name"] for e in out["entities"]]
    assert names == ["basmati rice cooked", "chicken thigh", "apple"]
    assert out["entities"][0]["source_dish"] == "chicken biryani"
    assert out["entities"][2]["source_dish"] is None  # apple untouched


async def test_empty_decompose_keeps_dish() -> None:
    state = _state([_entity("mystery stew", True)])
    with patch("backend.agent.graph.decompose_to_ingredients", return_value=[]):
        out = await auto_decompose_node(state)
    assert [e["food_name"] for e in out["entities"]] == ["mystery stew"]


async def test_flag_off_is_passthrough() -> None:
    state = _state([_entity("chicken biryani", True)])
    with patch("backend.agent.graph._auto_decompose_enabled", return_value=False), \
         patch("backend.agent.graph.decompose_to_ingredients") as deco:
        out = await auto_decompose_node(state)
    deco.assert_not_called()
    assert [e["food_name"] for e in out["entities"]] == ["chicken biryani"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_auto_decompose.py -v`
Expected: FAIL — `auto_decompose_node` / `_auto_decompose_enabled` not defined.

- [ ] **Step 3: Add the feature flag to the config schema + YAML**

In `src/backend/config/__init__.py`, add a config model and wire it into `Tunables`:

```python
class FeaturesConfig(BaseModel):
    auto_decompose_enabled: bool = True

    model_config = ConfigDict(extra="forbid")
```

Add the field to `class Tunables` (alongside `routing`, `prompts`):

```python
    routing: RoutingConfig
    prompts: PromptsConfig
    features: FeaturesConfig
    upper_limits: dict[str, UpperLimitEntry]
```

In `src/backend/config/tunables.yaml`, add a top-level section (place it near `routing:`):

```yaml
features:
  auto_decompose_enabled: true
```

- [ ] **Step 4: Add `auto_decompose_node` + helper to the graph**

In `src/backend/agent/graph.py`, add the two missing module-level imports. `extract_entities` and `log_meal` are already in the `from backend.agent.tools.meals import (...)` block (lines 11-18); add `FoodEntity` to that same block (safe — `workers/tasks.py` does not import `graph`, so there is no cycle), and add the config import below it:

```python
from backend.agent.tools.meals import (
    FoodEntity,
    apply_correction,
    classify_food_image,
    classify_intent,
    extract_entities,
    format_confirmation_card,
    log_meal,
)
from backend.config import get_tunables
```

Add the helper + node (place `auto_decompose_node` right after `extract_node`):

```python
def _auto_decompose_enabled() -> bool:
    """Feature flag for automatic composite-dish decomposition."""
    return get_tunables().features.auto_decompose_enabled


async def auto_decompose_node(state: AgentState) -> dict:
    """Break only is_composite entities into ingredients, per food, in order.

    Composite entities are decomposed via the shared primitive (portion-aware:
    the entity's gram weight is included so ingredients scale), re-parsed into
    ingredient entities tagged with source_dish provenance, and spliced in place.
    Atomic entities pass through untouched. Any failure (empty decompose, empty
    re-extract) degrades to keeping the original dish as a single entity.
    """
    if not _auto_decompose_enabled():
        return {"entities": state["entities"]}

    out: list[dict] = []
    for raw in state["entities"]:
        entity = FoodEntity(**raw)
        if not entity.is_composite:
            out.append(entity.model_dump())
            continue
        desc = f"{entity.qty_g:g} g {entity.food_name}"
        lines = decompose_to_ingredients(desc)
        if not lines:
            out.append(entity.model_dump())
            continue
        try:
            parsed = extract_entities(", ".join(lines)).entities
            sub = [e for e in parsed if e.qty_g > 0]
        except Exception:
            sub = []
        if not sub:
            out.append(entity.model_dump())
            continue
        for ing in sub:
            ing.source_dish = entity.food_name
            out.append(ing.model_dump())
    return {"entities": out}
```

`FoodEntity` resolves via the module-level import added at the start of this step.

- [ ] **Step 5: Rewire the graph edges**

In `build_graph` (`src/backend/agent/graph.py`), register the node and replace the `extract → usda_batch` edge with the two-hop path. Find `workflow.add_node("extract", extract_node)` and add after it:

```python
    workflow.add_node("auto_decompose", auto_decompose_node)
```

Find the existing edge that connects extraction to USDA resolution (the edge whose source is `extract` and target is `usda_batch`) and change it to:

```python
    workflow.add_edge("extract", "auto_decompose")
    workflow.add_edge("auto_decompose", "usda_batch")
```

(Leave the existing `decompose → usda_batch` edge from the manual button intact.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_auto_decompose.py tests/test_config.py tests/test_my_meals_graph.py -v`
Expected: PASS (node behavior; config still validates with the new `features` section; existing routing unaffected).

- [ ] **Step 7: Commit**

```bash
git add src/backend/config/__init__.py src/backend/config/tunables.yaml src/backend/agent/graph.py tests/test_auto_decompose.py
git commit -m "feat: auto_decompose_node — per-food composite breakdown behind a flag"
```

---

### Task 5: `combine_node` + `action == "combine"` routing

**Files:**
- Modify: `src/backend/agent/graph.py` (new `combine_node`; `_route_response`; node + edge registration)
- Test: `tests/test_combine.py`

**Interfaces:**
- Consumes: graph state `entities` with `source_dish` tags; `action == "combine"`.
- Produces: `combine_node(state) -> dict` returning `{"action": None, "entities": [...]}` where every `source_dish`-tagged group is collapsed to a single entity named after the dish (provenance cleared), standalone entities preserved; `_route_response` returns `"combine"` when `action == "combine"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_combine.py
"""combine_node collapses decomposed ingredients back to their dish."""

from __future__ import annotations

from backend.agent.graph import combine_node, _route_response


def _ing(name: str, dish: str | None, qty: float = 100) -> dict:
    return {"food_name": name, "qty_g": qty, "unit": "g",
            "confidence": 1.0, "is_composite": False, "source_dish": dish}


def test_route_response_combine() -> None:
    assert _route_response({"action": "combine", "messages": []}) == "combine"


async def test_combine_collapses_group_keeps_standalone() -> None:
    state = {"entities": [
        _ing("basmati rice cooked", "chicken biryani"),
        _ing("chicken thigh", "chicken biryani"),
        _ing("apple", None),
    ]}
    out = await combine_node(state)
    names = [e["food_name"] for e in out["entities"]]
    assert names == ["chicken biryani", "apple"]
    assert all(e["source_dish"] is None for e in out["entities"])
    assert out["action"] is None


async def test_combine_noop_when_nothing_tagged() -> None:
    state = {"entities": [_ing("apple", None), _ing("banana", None)]}
    out = await combine_node(state)
    assert [e["food_name"] for e in out["entities"]] == ["apple", "banana"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_combine.py -v`
Expected: FAIL — `combine_node` not defined; `_route_response` has no combine branch.

- [ ] **Step 3: Add `combine_node`**

In `src/backend/agent/graph.py`, add after `decompose_node`:

```python
async def combine_node(state: AgentState) -> dict:
    """Collapse every auto-decomposed ingredient group back to its source dish.

    Triggered by the card's "Log as single item" action. Each source_dish group
    becomes a single entity named after the dish (default 1g placeholder qty so
    usda_batch re-resolves it); entities without provenance are kept as-is.
    Falls through to usda_batch → present.
    """
    rebuilt: list[dict] = []
    seen: set[str] = set()
    for raw in state["entities"]:
        dish = raw.get("source_dish")
        if dish is None:
            keep = dict(raw)
            keep["source_dish"] = None
            rebuilt.append(keep)
            continue
        if dish in seen:
            continue
        seen.add(dish)
        rebuilt.append(
            FoodEntity(food_name=dish, qty_g=1, unit="g").model_dump()
        )
    return {"action": None, "entities": rebuilt}
```

Note: the collapsed dish uses a 1g placeholder so `usda_batch` re-resolves the dish directly (USDA match or LLM estimate); the user can adjust the portion on the re-presented card. `FoodEntity` must be importable at module level in this file (added in Task 4).

- [ ] **Step 4: Add the routing branch + wiring**

In `_route_response` (`src/backend/agent/graph.py`), add the combine branch right after the existing decompose branch:

```python
def _route_response(state: AgentState) -> str:
    # "Break into ingredients" takes priority over confirm/correct/reject.
    if state.get("action") == "decompose":
        return "decompose"
    if state.get("action") == "combine":
        return "combine"
    last_human = next(
        ...
```

In `build_graph`, register the node and its edge (next to the `decompose` registrations):

```python
    workflow.add_node("combine", combine_node)
    workflow.add_edge("combine", "usda_batch")
```

And add `"combine": "combine"` to the `_route_response` conditional-edge mapping (the dict that currently contains `"decompose": "decompose"`).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_combine.py tests/test_my_meals_graph.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/backend/agent/graph.py tests/test_combine.py
git commit -m "feat: combine_node + action=combine to revert auto-decomposition"
```

---

### Task 6: Persist the dish `label` (`_meal_label` + `log_meal` + `log_node`)

**Files:**
- Modify: `src/backend/agent/tools/meals.py` (`_meal_label` helper; `log_meal` signature; `_insert_meal_log` INSERT)
- Modify: `src/backend/agent/graph.py` (`log_node`, lines 176-185)
- Test: `tests/test_meal_label.py`

**Interfaces:**
- Consumes: graph state `entities` with `source_dish` (Tasks 2-4); `meal_log.label` column (Task 1).
- Produces: `_meal_label(entities: list[dict]) -> str` (dedups `source_dish` else `food_name`, order-preserving, comma-joined); `log_meal(user_id, usda_results, meal_type="unspecified", label=None)`; `_insert_meal_log(..., label=None)` writes the column.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_meal_label.py
"""_meal_label builds the human-facing dish-name snapshot from entities."""

from __future__ import annotations

from backend.agent.tools.meals import _meal_label


def _e(food_name: str, dish: str | None) -> dict:
    return {"food_name": food_name, "qty_g": 100, "unit": "g",
            "confidence": 1.0, "is_composite": False, "source_dish": dish}


def test_label_dedups_dish_keeps_order() -> None:
    entities = [
        _e("basmati rice cooked", "chicken biryani"),
        _e("chicken thigh", "chicken biryani"),
        _e("apple", None),
    ]
    assert _meal_label(entities) == "chicken biryani, apple"


def test_label_atomic_only() -> None:
    assert _meal_label([_e("apple", None), _e("banana", None)]) == "apple, banana"


def test_label_empty() -> None:
    assert _meal_label([]) == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_meal_label.py -v`
Expected: FAIL — `_meal_label` not defined.

- [ ] **Step 3: Add `_meal_label` + thread `label` through logging**

In `src/backend/agent/tools/meals.py`, add the helper (near the other private helpers):

```python
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
```

Update `_insert_meal_log` to accept and write `label` (add the param, the column, and the bind value):

```python
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
```

Update `log_meal` to accept `label` and pass it through:

```python
async def log_meal(
    user_id: str,
    usda_results: list,
    meal_type: str = "unspecified",
    label: str | None = None,
) -> MealLogResult:
```

and change its `_insert_meal_log` call to:

```python
    meal_id = await _insert_meal_log(user_id, meal_type, resolved, totals, label)
```

- [ ] **Step 4: Compute the label in `log_node`**

In `src/backend/agent/graph.py`, update `log_node` to compute the label from the entities in state and pass it:

```python
async def log_node(state: AgentState) -> dict:
    """Persist confirmed meal to Postgres and Redis."""
    from backend.agent.tools.usda import USDAResult

    from backend.agent.tools.meals import normalize_meal_type, _meal_label

    results = [USDAResult(**r) for r in state["usda_results"]]
    meal_type = normalize_meal_type(state.get("meal_type"))
    label = _meal_label(state["entities"])
    result = await log_meal(state["user_id"], results, meal_type, label=label)
    return {"messages": [AIMessage(content=result.message)]}
```

(`state["entities"]` holds the *described* names + `source_dish` provenance, so
the label reads "chicken biryani, apple" rather than the resolved FDC
descriptions. After combine, `source_dish` is cleared and the dish `food_name`
is used — same result. `_meal_label` is shape-agnostic: it only reads the
`food_name`/`source_dish` keys, which both the entity and usda_result dicts
carry.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_meal_label.py tests/test_meal_tools.py -v`
Expected: PASS (helper tests; existing meal-tool tests unaffected — `label` defaults to `None`).

- [ ] **Step 6: Commit**

```bash
git add src/backend/agent/tools/meals.py src/backend/agent/graph.py tests/test_meal_label.py
git commit -m "feat: persist meal_log.label (dish-name snapshot) on log"
```

---

### Task 7: Embed the dish `label` in history search

**Files:**
- Modify: `src/backend/workers/tasks.py` (`_embed_meal_summary`, ~lines 122-133)
- Test: `tests/test_embed_label.py`

**Interfaces:**
- Consumes: `meal_log.label` (Task 1, 6).
- Produces: `_embed_meal_summary` builds the embedded summary from `meal.label` when present, falling back to the `entities[].food_name` join when `label is None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_embed_label.py
"""embed_meal_summary keeps the dish word by embedding meal_log.label."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from backend.workers.tasks import _embed_meal_summary


def _meal(label, entities) -> SimpleNamespace:
    return SimpleNamespace(meal_type="dinner", label=label, entities=entities,
                           embedding=None)


async def _run_with(meal):
    session = MagicMock()
    session.get = AsyncMock(return_value=meal)
    session.commit = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    captured = {}

    async def fake_embed(text: str):
        captured["text"] = text
        return [0.0] * 768

    with patch("backend.workers.tasks.get_session", return_value=lambda: ctx), \
         patch("backend.workers.tasks.embed_text", side_effect=fake_embed):
        await _embed_meal_summary("meal-1")
    return captured["text"]


async def test_uses_label_when_present() -> None:
    meal = _meal("chicken biryani, apple",
                 [{"food_name": "basmati rice cooked"}, {"food_name": "apple raw"}])
    text = await _run_with(meal)
    assert "chicken biryani" in text and text.startswith("dinner:")


async def test_falls_back_to_food_names_when_label_none() -> None:
    meal = _meal(None, [{"food_name": "apple raw"}, {"food_name": "banana raw"}])
    text = await _run_with(meal)
    assert "apple raw" in text and "banana raw" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_embed_label.py -v`
Expected: FAIL — summary still built only from `food_name`s (label ignored).

- [ ] **Step 3: Use the label in the summary**

In `src/backend/workers/tasks.py`, update `_embed_meal_summary`:

```python
async def _embed_meal_summary(meal_id: str) -> None:
    session_factory = get_session()
    async with session_factory() as session:
        meal = await session.get(MealLog, meal_id)
        if meal is None:
            return

        label = getattr(meal, "label", None)
        if label:
            body = label
        else:
            body = ", ".join(item["food_name"] for item in meal.entities)
        summary = f"{meal.meal_type}: {body}"
        embedding = await embed_text(summary)

        meal.embedding = embedding
        await session.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_embed_label.py tests/test_tasks.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/backend/workers/tasks.py tests/test_embed_label.py
git commit -m "feat: embed meal_log.label so dish identity survives in history search"
```

---

### Task 8: Frontend "Log as single item" action

**Files:**
- Modify: `src/backend/agent/orchestrator.py` (`items` dict in `_handle_meal_logging`, ~lines 210-232)
- Modify: `frontend/src/api/types.ts` (`MealItem`)
- Modify: `frontend/src/components/chat/ConfirmationCard.tsx` (button)
- Modify: `frontend/src/pages/ChatPage.tsx` (combine handler)
- Test: typecheck (`npx tsc --noEmit`) + the backend orchestrator field is covered by existing e2e

**Interfaces:**
- Consumes: `usda_results[].source_dish` (Task 3).
- Produces: response `items[].source_dish: str | null`; a card button posting `action: 'combine'` shown when any item has `source_dish`.

- [ ] **Step 1: Surface `source_dish` in the response items (backend)**

In `src/backend/agent/orchestrator.py`, add `source_dish` to the `items.append({...})` dict in `_handle_meal_logging`:

```python
                        "source": r.get("source", "USDA"),
                        "estimated": r.get("estimated", False),
                        "source_dish": r.get("source_dish"),
```

- [ ] **Step 2: Add the field to the TS type**

`MealItem` in `frontend/src/api/types.ts` is snake_case (`food_name`, `qty_g`, `protein_g`), so the API's snake_case keys are read directly — no mapping. Add the field in the same convention:

```typescript
  source: string
  estimated: boolean
  source_dish?: string | null
```

- [ ] **Step 3: Add the button to `ConfirmationCard.tsx`**

Near the existing "Break into ingredients" button (around line 327-336), add a sibling shown only when any item carries decomposition provenance. Use the same posting mechanism the "Break into ingredients" button uses (it triggers `action: 'decompose'`):

```tsx
{items.some((i) => i.source_dish) && (
  <button
    type="button"
    onClick={onCombine}
    className="press cursor-pointer ..."  // mirror the Break-into-ingredients button classes
  >
    Log as single item
  </button>
)}
```

Add `onCombine` to `ConfirmationCardProps` alongside the existing decompose handler prop.

- [ ] **Step 4: Wire the handler in `ChatPage.tsx`**

Mirror the decompose handler (line 91-96) with a combine one:

```tsx
// "Log as single item" → resume the paused thread with action=combine.
const handleCombine = () => {
  sendMessage.mutate(
    { user_input: 'log as single item', conversation_id: conversationId, action: 'combine' },
    // ...same options as the decompose handler
  )
}
```

Pass `onCombine={handleCombine}` to `<ConfirmationCard />`.

- [ ] **Step 5: Typecheck + build**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: no type errors; build succeeds.

- [ ] **Step 6: Commit**

```bash
git add src/backend/agent/orchestrator.py frontend/src/api/types.ts frontend/src/components/chat/ConfirmationCard.tsx frontend/src/pages/ChatPage.tsx
git commit -m "feat: 'Log as single item' action to revert auto-decomposition"
```

---

### Task 9: Per-dish collapsed rows + focused ingredient popup

When a query has multiple composite dishes (e.g. "biryani, pasta, and a curry"), each dish renders **collapsed** as one row (dish name + summed macros) carrying its own **"Break into ingredients"** button. Clicking it opens a **focused modal** showing only that dish's ingredient lines with an **✕** close button. This is presentation of the `source_dish` grouping the backend already produces (Tasks 3-4, 8) — no backend change. Atomic items (no `source_dish`) keep rendering as normal inline rows. Per-ingredient edits (qty/swap/remove) stay keyed by the original flat item index, so editing inside the modal flows through the existing correction logic.

**Files:**
- Modify: `frontend/src/components/chat/ConfirmationCard.tsx`
- Test: typecheck (`npx tsc --noEmit`) + `npm run build`

**Interfaces:**
- Consumes: `MealItem.source_dish` (Task 8); existing `qtys`/`swaps`/`removed`/`scaled` state keyed by item index.
- Produces: collapsed composite rows + a focused per-dish ingredient modal (frontend-only).

- [ ] **Step 1: Add the grouping helper**

At the top of `ConfirmationCard.tsx` (module scope, below the imports), add:

```tsx
interface ItemGroup {
  dish: string | null   // source_dish; null = a standalone atomic item
  indices: number[]     // original indices into the flat `items` array
}

/** Group consecutive items by source_dish, preserving first-seen order. */
function groupByDish(items: MealItem[]): ItemGroup[] {
  const groups: ItemGroup[] = []
  const pos = new Map<string, number>()
  items.forEach((item, i) => {
    const dish = item.source_dish ?? null
    if (dish === null) {
      groups.push({ dish: null, indices: [i] })
      return
    }
    const at = pos.get(dish)
    if (at === undefined) {
      pos.set(dish, groups.length)
      groups.push({ dish, indices: [i] })
    } else {
      groups[at].indices.push(i)
    }
  })
  return groups
}
```

- [ ] **Step 2: Extract the item row into a reusable renderer**

The existing per-item `<div key={...}>…</div>` block (the JSX currently inside `{items.map((item, i) => { … })}`, lines ~184-289) is rendered in two places now (inline atomic rows + modal ingredient rows). Extract it into a local function inside the component so both call sites share it:

```tsx
const renderItemRow = (i: number) => {
  const item = items[i]
  if (removed.has(i)) return null
  // …exact JSX currently inside items.map, using `item` and `i`…
  return ( /* the existing <div key={`${item.fdc_id}-${i}`}> … </div> */ )
}
```

Keep all existing behavior (stepper, candidate switcher, remove) — only move the JSX, do not change it.

- [ ] **Step 3: Add modal state and render groups**

Add state near the other `useState` hooks:

```tsx
const [openDish, setOpenDish] = useState<string | null>(null)
```

Replace the inline `{items.map((item, i) => …)}` block (the `{/* Items */}` container, lines ~183-290) with group-aware rendering:

```tsx
{/* Items — atomic rows inline; composite dishes collapsed with a per-dish popup */}
<div className="flex flex-col gap-2.5">
  {groupByDish(items).map((group) => {
    if (group.dish === null) return renderItemRow(group.indices[0])
    const visible = group.indices.filter((i) => !removed.has(i))
    if (visible.length === 0) return null
    const sum = (key: 'kcal' | 'protein_g' | 'fiber_g') =>
      visible.reduce((acc, i) => acc + scaled[i][key], 0)
    return (
      <div
        key={`dish-${group.dish}`}
        className="bg-paper rounded-xl border-l-4 border border-sand-border border-l-sage p-3.5 flex items-center justify-between gap-2"
      >
        <div className="min-w-0 flex-1">
          <h4 className="text-[14px] font-medium text-ink leading-snug truncate">
            {group.dish}
          </h4>
          <p className="text-[11px] text-muted mt-0.5">
            {Math.round(sum('kcal'))} kcal · {sum('protein_g').toFixed(0)}g protein ·{' '}
            {sum('fiber_g').toFixed(0)}g fiber · {visible.length} ingredient
            {visible.length === 1 ? '' : 's'}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setOpenDish(group.dish)}
          className="press cursor-pointer shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[12px] font-medium text-sage-deep border border-sand-border hover:border-sage"
        >
          <Sparkles className="w-3.5 h-3.5" />
          Break into ingredients
        </button>
      </div>
    )
  })}
</div>
```

- [ ] **Step 4: Add the focused modal**

Just before the component's closing `</div>` (the outermost card div), add the modal overlay. It reuses `renderItemRow` for the open dish's ingredients and closes with ✕:

```tsx
{openDish !== null && (
  <div
    className="fixed inset-0 z-50 flex items-center justify-center bg-ink/30 p-4"
    onClick={() => setOpenDish(null)}
    role="dialog"
    aria-modal="true"
  >
    <div
      className="w-full max-w-md card-sand p-4 md:p-5 flex flex-col gap-3 rise-in max-h-[80vh] overflow-y-auto"
      onClick={(e) => e.stopPropagation()}
    >
      <div className="flex items-center justify-between pb-2 border-b border-sand-border">
        <h3 className="label-caps !text-sage-deep truncate">{openDish}</h3>
        <button
          type="button"
          onClick={() => setOpenDish(null)}
          aria-label="Close"
          className="press cursor-pointer w-7 h-7 rounded-full flex items-center justify-center text-muted hover:text-ink hover:bg-container"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
      <div className="flex flex-col gap-2.5">
        {groupByDish(items)
          .find((g) => g.dish === openDish)
          ?.indices.map((i) => renderItemRow(i))}
      </div>
    </div>
  </div>
)}
```

- [ ] **Step 5: Typecheck + build**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: no type errors; build succeeds.

- [ ] **Step 6: Manual smoke (if dev server is up)**

Log "chicken biryani and pasta and an apple". Expect: two collapsed dish rows (biryani, pasta) each with "Break into ingredients", plus an inline apple row. Click biryani's button → a focused modal lists biryani's ingredients with ✕; close returns to the card. Confirm logs the ingredient-level macros.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/chat/ConfirmationCard.tsx
git commit -m "feat: collapse composite dishes with per-dish break-into-ingredients popup"
```

---

## End-to-end verification (after all tasks)

- [ ] Run the full backend suite: `uv run pytest -q` — expect green.
- [ ] Manual (needs Redis + Postgres up): log "chicken biryani and an apple" → card shows ingredient lines + apple → "Log as single item" → card shows "chicken biryani" + apple. Confirm; check the `meal_log` row has `label = "chicken biryani, apple"` (or "chicken biryani, apple" → after combine, `label` reflects the collapsed names).
- [ ] Regression: a saved My Meal still short-circuits (no decomposition); an atomic-only message ("an apple") logs unchanged with `label = "apple"`.
- [ ] Toggle `features.auto_decompose_enabled: false` in tunables → composite dishes log as single items (no breakdown).
