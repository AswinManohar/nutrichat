# Meal Logging Agent — Design Spec
**Date:** 2026-04-05
**Status:** Approved
**Scope:** Phase 1 — text + image meal logging with correction loop

---

## 1. Architecture

Strict sequential graph — LLM only does NLP, Python nodes handle all tool calls.

```
user input
    │
    ▼
[router] ──── text ────► [extract]
    │                        │
    └──── image ──► [classify] ──► [extract]
                                       │
                                   [usda_batch]
                                       │
                                   [present]  ◄─────────────────┐
                                       │   ◄── INTERRUPT         │
                              ─────────┼─────────                │
                             │         │         │               │
                          confirm   correct    reject             │
                             │         │         │               │
                          [log]   [apply_correction]            END
                                       │
                                  re-runs usda_batch
                                  for changed entities ──────────┘
```

**Nodes:**

| Node | Type | Model |
|---|---|---|
| `router` | Python | — |
| `classify` | LLM | Flash-Lite, structured output |
| `extract` | LLM | Flash-Lite, structured output |
| `usda_batch` | Python | — |
| `present` | Python formatter | — |
| `apply_correction` | LLM | Flash-Lite, structured output |
| `log` | Python | — |

**State:**
```python
class AgentState(TypedDict):
    messages:     Annotated[Sequence[BaseMessage], add_messages]
    user_id:      str
    image_b64:    Optional[str]
    entities:     list[dict]       # populated by extract
    usda_results: list[dict]       # populated by usda_batch
    meal_type:    Optional[str]
```

**Interrupt:** After `present`, graph pauses. Next user message is classified as confirm / correct / reject by a lightweight keyword check (no LLM).

---

## 2. Prompts & Tool Contracts

### LLM Prompts

**`extract` — Flash-Lite, structured output**
```
Extract all food items from the meal description.
Return: food_name (USDA-style), qty_g, unit, confidence (0–1).
Vague quantities ("some", "a bit") get confidence < 0.6.

Conversions: 1 large egg=61g, 1 tbsp=14g, 1 cup oats cooked=234g,
1 slice bread=28g, 1 medium banana=118g, 1 cup milk=244g.
```
Output: `ExtractionResult { entities: list[FoodEntity] }`

**`classify` — Flash-Lite, structured output, multimodal**
```
Identify every distinct food item and ingredient visible.
If no food present, set is_food=false and explain why.
```
Output: `ImageClassification { is_food, food_items, ingredients, reason }`
After classify, `food_items + ingredients` concatenated → fed into `extract`.

**`apply_correction` — Flash-Lite, structured output**
```
Update this food entity list based on the user correction.
Current entities: {entities_json}

Rules:
- Quantity change → update qty_g
- Addition → append new entity
- Removal → drop matching entity
- Substitution → replace food_name, keep qty_g
- Multiple corrections in one message → apply all

Return the complete updated list.
```
Output: `ExtractionResult { entities: list[FoodEntity] }`

**`present` — pure Python, no LLM**
```
• 2 scrambled eggs (122g) — 182 kcal · 12g protein · 1g fiber
• Whole wheat toast (28g) — 86 kcal  · 5g protein  · 2g fiber

Total: 268 kcal · 17g protein · 9g carbs · 7g fat · 3g fiber

Does this look right? Confirm, correct any item, or cancel.
```
Low-confidence items marked with ⚠. Ambiguous matches show top-3 FDC candidates.

### Tool Contracts

**`usda_lookup_batch(entities: list[FoodEntity]) → list[USDAResult]`**

```python
class NutrientValue(BaseModel):
    amount: float
    unit: str           # g, mg, mcg, kcal

class USDAResult(BaseModel):
    fdc_id:           int
    food_name:        str
    qty_g:            float
    match_confidence: float
    candidates:       list[str]    # top-3 FDC descriptions

    # Promoted macros (scaled to qty_g)
    kcal:      float
    protein_g: float
    carbs_g:   float
    fat_g:     float
    fiber_g:   float
    sugar_g:   float
    sat_fat_g: float

    # Full USDA nutrient breakdown (~50 nutrients, scaled to qty_g)
    nutrients: dict[str, NutrientValue]
```

Postgres `food_source` cache checked first. FDC API called on miss, result cached.

**`log_meal(user_id, entities, meal_type) → MealLogResult`**
- INSERT into `meal_log` (entities JSONB stores full `USDAResult` per item)
- `increment_today()` → Redis pipeline
- Queues Celery tasks: `embed_meal_summary`, `extract_and_store_facts`

### Nutrient storage

| Layer | Content |
|---|---|
| `food_source.nutrients` JSONB | Full FDC nutrients per 100g (cache) |
| `meal_log.entities` JSONB | Full `USDAResult` per entity, scaled to qty_g |
| Redis `TodayTotals` | kcal, protein_g, carbs_g, fat_g, fiber_g, n_meals only |
| Dashboard | Aggregated from `meal_log.entities` JSONB |

Micronutrients surfaced on user request only ("how much vitamin C today?") — not in confirmation card.

---

## 3. Error Handling

| Failure | Recovery |
|---|---|
| USDA miss (0 results) | Flag item, ask user to rephrase or skip. Other items proceed normally. |
| Low confidence (`< 0.6`) | Show ⚠ in card with estimated weight. User corrects via normal flow. |
| Ambiguous match (`confidence < 0.85`) | Show top-3 candidates in card. User says "use rotisserie" → correction flow. |
| Image not food | Route to END immediately. "Couldn't identify food — describe the meal instead?" |
| FDC timeout/5xx | Retry once (1s backoff). On second failure: fuzzy Postgres cache check. Still fails → flag as unresolved. |

`log_meal` never called with unresolved entities. Correction loop has no iteration limit.

---

## 4. Testing Strategy

### Notebook cells (validate prompts before wiring)

| Cell | Test | Pass criteria |
|---|---|---|
| 1 | `extract` — varied inputs | Vague quantities → `confidence < 0.6` |
| 2 | `classify` — food/non-food images | `is_food=false` on non-food |
| 3 | `apply_correction` — qty/add/remove/substitute | Entity list matches intent |
| 4 | `usda_lookup_batch` — cache miss → FDC → hit | Nutrients scaled to `qty_g` |
| 5 | Full text round-trip | Card correct, DB row written, Redis incremented |
| 6 | Full image round-trip | classify → extract → batch → card |
| 7 | Correction loop | Correct → re-present → confirm → DB row verified |

### Integration tests (after wiring into NutriChat)
```bash
# text log
curl -X POST localhost:8000/meals/log \
  -d '{"user_input": "2 scrambled eggs and toast"}'

# correction in same thread
curl -X POST localhost:8000/meals/log \
  -d '{"user_input": "actually 3 eggs", "conversation_id": "<thread_id>"}'

# micronutrient query
curl -X POST localhost:8000/meals/log \
  -d '{"user_input": "how much vitamin C did I get today?"}'
```

**Eval target (PRD §11):** Entity F1 ≥ 0.88 on 50-item test set — run after notebook prompt is stable.

---

## 5. Notebook → NutriChat migration path

1. Iterate prompts in `entity_agent.ipynb` until Cell 7 passes consistently
2. Port prompts verbatim into `src/backend/agent/tools/meals.py` and `usda.py`
3. Wire graph nodes in `src/backend/agent/graph.py` (replace dummy node)
4. Wire `build_context()` system prompt into `call_model` node
5. Run integration tests against live FastAPI + Postgres + Redis stack
