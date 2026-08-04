# Automatic Selective Ingredient Decomposition — Design Spec

**Date:** 2026-06-19
**Status:** Approved
**Scope:** Make ingredient decomposition automatic and *selective*. The agent
classifies each described food as **composite** (a prepared/multi-ingredient
dish USDA has no good single entry for — biryani, pasta dishes, curries) or
**atomic** (a whole/standard single item — apple, chicken breast, milk), and
auto-breaks only the composite ones into ingredients. Saved My Meals always win
over decomposition. A "Log as single item" action reverts an unwanted breakdown.

Builds directly on the My Meals work
([2026-06-17-my-meals-design.md](2026-06-17-my-meals-design.md)): same
`decompose_to_ingredients` primitive, same confirmation card, same `entities`
JSONB shape, same action→node routing pattern.

---

## 1. Decisions (locked with user)

- **Per-food granularity.** Extraction splits a message into foods first; each
  food is classified and decomposed independently. `"chicken biryani and an
  apple"` → `[rice, chicken, ghee, onion…]` + `[apple]`.
- **Detection = a flag emitted during extraction.** The existing extraction LLM
  (Gemini Flash-Lite) emits a per-entity `is_composite` boolean alongside
  `food_name`/`qty_g`. No extra LLM call, full context, generalizes to any
  cuisine. The composite-vs-atomic policy lives in the tunable extraction
  prompt.
- **Saved My Meals take absolute priority.** `saved_lookup` runs first and
  short-circuits to the card on a hit — no extraction, no classification, no
  decomposition. Auto-decompose only exists on the saved-meal-*miss* path.
- **Recovery = a single global "Combine" action.** The card offers **"Log as
  single item"** that collapses every auto-generated ingredient line back to its
  source dish and re-resolves the dish directly against USDA. Per-dish combine
  is deferred (YAGNI).
- **The manual "Break into ingredients" button stays.** It is the opposite
  override — force-decompose a food the extractor classified atomic.
- **Feature-flagged.** A tunable `auto_decompose_enabled` gates the whole
  behavior; when off, logging behaves exactly as today.

---

## 2. Flow

```
router → saved_lookup ──hit──→ present              (My Meal: verbatim, no decompose)
                    └─miss──→ extract → auto_decompose → usda_batch → present
```

- **`saved_lookup_node`** (unchanged): whole-input normalized match against
  `user_meal`. Hit → prefill `usda_results`/`entities`, route straight to
  `present`.
- **`extract_node`** (changed): each `FoodEntity` now carries `is_composite`.
- **`auto_decompose_node`** (new): for each composite entity, decompose into
  ingredient entities tagged with provenance; atomic entities pass through.
- **`usda_batch_node` / `present_node`** (unchanged) resolve and render the
  combined entity list.

On resume (after the confirmation interrupt), `_route_response` gains a
`combine` branch alongside the existing `decompose`/confirm/correct/cancel.

---

## 3. Data model changes

### 3.1 `FoodEntity` (`agent/tools/meals.py`)

Add two fields (model keeps `extra="forbid"`):

```python
is_composite: bool = Field(
    default=False,
    description="True for a prepared/multi-ingredient dish to break into "
                "ingredients; false for a whole/standard single food.",
)
# Internal provenance, set by auto_decompose_node (NOT emitted by the LLM):
# the composite dish this ingredient was broken out of. Drives the Combine
# action and any "broke X into…" affordance.
source_dish: str | None = None
```

`is_composite` is produced by the extraction LLM. `source_dish` is set
programmatically after re-extraction (it is not part of the extraction prompt,
so atomic/top-level entities leave it `None`).

### 3.2 Persistence — dish identity survives as one column

**`is_composite` and `source_dish` are transient** — they live only in graph
state to drive decomposition, the Combine action, and the card. They are **never
persisted as a "composite" flag.** Once logged, a decomposed dish is just a
normal `meal_log` row whose `entities` are the ingredients.

But the **dish name must survive logging** so "how often did I have biryani?"
is a one-column lookup, not a vector search over `[rice, chicken, ghee…]` (which
no longer contains the word "biryani"). Today `meal_log` has no name/label
column and `embed_meal_summary` derives its searchable text from
`entities[].food_name` — so a decomposed dish's identity is lost entirely.

**Add `meal_log.label text NULL`** (migration `008_meal_log_label`): a clean,
human-facing list of the dishes/foods *as described*, built at log time from
provenance:

- entities with `source_dish` set → use the `source_dish` (deduplicated),
- entities without → use the `food_name`.

So `"chicken biryani and an apple"` (biryani decomposed) logs
`label = "chicken biryani, apple"`. This single column powers dish-name history
("how often did I have biryani" → `WHERE label ILIKE '%biryani%'`) and is also
the text fed to the meal embedding, so semantic history keeps the dish identity
too. Index: `ix_meal_log_user_label (user_id, label)` for the lookup. Backfill is
unnecessary (older rows simply have `label = NULL`; readers tolerate it, per the
`rda_pct` default-None precedent).

---

## 4. Components

### 4.1 Extraction prompt (`PromptsConfig.extraction_system`)

Extend the prompt to set `is_composite` per entity:

- **true** — prepared/multi-ingredient dishes with no faithful single USDA
  entry: biryani, fried rice, pasta dishes (spaghetti bolognese), curries,
  stews, casseroles, sandwiches/burgers, smoothies, stir-fries, mixed salads
  with dressing.
- **false** — whole or standard single items and recognizable USDA staples:
  apple, banana, chicken breast, cooked rice, milk, scrambled eggs, a slice of
  bread.

The boundary cases (scrambled eggs, plain oatmeal, green salad) are encoded in
the prompt so the policy is tunable without code edits.

### 4.2 `auto_decompose_node` (new, `agent/graph.py`)

```
for entity in state["entities"]:
    if not entity.is_composite or not auto_decompose_enabled:
        keep entity as-is
    else:
        desc = f"{entity.qty_g:g} g {entity.food_name}"      # portion-aware
        lines = decompose_to_ingredients(desc)               # reuse primitive
        if not lines: keep entity as-is            # graceful no-op fallback
        else:
            sub = extract_entities(", ".join(lines)).entities  # re-parse to grams
            sub = [e for e in sub if e.qty_g > 0]
            if not sub: keep entity as-is
            else: tag each sub.source_dish = entity.food_name; splice in
return {"entities": [all entities, composites replaced by their ingredients]}
```

Notes:
- Decomposition input is a **gram-aware description** built from the entity
  (`f"{qty_g:g} g {food_name}"`), not the raw whole message — that is what makes
  it per-food *and* preserves the portion (`"2 plates of biryani"` scales its
  ingredients). The card's portion multiplier still lets the user adjust after.
- Order is preserved so the card reads naturally
  (`rice, chicken, …, apple`).
- Wrapped to never raise (decompose/extract failures degrade to the original
  composite entity), consistent with the existing nodes.

### 4.3 `combine_node` (new, `agent/graph.py`)

Triggered by `action == "combine"` from the card. Collapses provenance:

```
groups = group entities by source_dish (None = standalone, untouched)
new_entities = [standalone entities] + [FoodEntity(food_name=dish) for each group]
# re-resolve the reconstructed dishes directly against USDA
return {"action": None, "entities": [...], "source_dish cleared"}
→ usda_batch → present
```

Reuses the `decompose_node` structure (action consumed, falls through to
`usda_batch → present`). Mirrors the existing manual-decompose round trip.

### 4.4 Routing (`_route_response`, `agent/graph.py`)

```python
if state.get("action") == "decompose":
    return "decompose"
if state.get("action") == "combine":     # NEW
    return "combine"
# …existing confirm / correct / cancel…
```

Add `workflow.add_node("combine", combine_node)`,
`workflow.add_edge("combine", "usda_batch")`, and the `"combine": "combine"`
entry to the `_route_response` edge map. Insert `auto_decompose` between
`extract` and `usda_batch`: `extract → auto_decompose → usda_batch` (replacing
the current `extract → usda_batch` edge).

### 4.5 Frontend — per-dish popup + "Log as single item" (`frontend/`)

**Per-dish collapsed rows + focused popup.** Items are grouped by `source_dish`.
Each composite dish renders **collapsed** as a single row (dish name + summed
macros) with its own **"Break into ingredients"** button; clicking opens a
**focused modal** that lists only that dish's ingredient lines with an **✕**
close button. This matters when a query has multiple composite dishes (biryani +
pasta + curry) — each gets its own button and its own popup. Atomic items (no
`source_dish`) render as normal inline rows. Per-ingredient edits stay keyed by
the original flat item index, so editing inside the modal flows through the
existing correction logic. This is presentation of the `source_dish` grouping
the backend already produces — no backend change.

**"Log as single item".** A global action, shown whenever any line has
`source_dish` set, posts the meal-action shape with `action: "combine"` (same
channel as "Break into ingredients"/"Save to My Meals") to collapse every
decomposed group back to its dish.

---

### 4.6 `log_meal` + `embed_meal_summary` — persist & embed the dish name

- **`log_meal` (`agent/tools/meals.py`)** computes `label` from the final
  entities (dedup `source_dish` where set, else `food_name`, preserving order)
  and writes it to `meal_log.label`. A small `_meal_label(entities) -> str`
  helper keeps this testable in isolation.
- **`embed_meal_summary` (`workers/tasks.py`)** uses `meal.label` when present
  for the summary text (`f"{meal_type}: {label}"`), falling back to the current
  `entities[].food_name` join when `label is None` (older rows). This keeps the
  dish word ("biryani") in the embedded text instead of only its ingredients.

## 5. Channels & edge cases

- **Telegram + web both** get decomposed cards, since `auto_decompose_node` runs
  server-side regardless of channel. The "Combine" button is web-only; Telegram
  users revert via a chat correction (existing `apply_correction` path).
- **Empty decomposition** (`decompose_to_ingredients` → `[]`) → keep the dish as
  one atomic entity. No user-visible error.
- **Re-extraction yields nothing usable** (all `qty_g <= 0`) → keep the dish as
  one atomic entity.
- **Feature flag off** → `auto_decompose_node` is a pass-through; behavior is
  identical to today.
- **Saved-meal hit** never reaches `auto_decompose` (priority guaranteed by the
  graph topology).
- **Multiple composites in one message** → all decompose; one "Combine" reverts
  every provenance group at once.

---

## 6. Testing

- **Unit — classification:** extraction returns `is_composite=true` for biryani,
  spaghetti bolognese, chicken sandwich; `false` for apple, chicken breast,
  milk. (Tunable-prompt behavior; assert on a small fixed set, allow for LLM
  via the existing extraction test pattern / mock.)
- **Unit — `auto_decompose_node`:** mixed input decomposes only composites,
  preserves order, tags `source_dish`; empty-decompose and empty-reextract both
  fall back to the original entity; flag-off passes through.
- **Unit — `combine_node`:** collapses tagged groups to their dishes, leaves
  standalone entities, clears `source_dish`, leaves the entity list re-resolvable
  by `usda_batch`.
- **Routing:** `action=="combine"` routes to `combine`; `decompose`/confirm/
  correct/cancel still route as before.
- **Unit — `_meal_label`:** dedups `source_dish`, falls back to `food_name`,
  preserves order → `"chicken biryani, apple"`.
- **Integration:** "chicken biryani and an apple" → card shows ingredient lines
  + apple; the logged row has `entities=[ingredients…, apple]` **and**
  `label="chicken biryani, apple"`; "Combine" → card shows biryani + apple;
  totals consistent both ways.
- **Persistence/retrieval:** logging a decomposed dish sets `meal_log.label`;
  the embedding summary contains the dish word; `label IS NULL` rows still embed
  via the food-name fallback.
- **Regression:** saved-meal hit still short-circuits; atomic-only messages are
  untouched.

---

## 7. Out of scope (YAGNI)

- Per-dish (rather than global) Combine.
- Persisting `is_composite`/`source_dish` themselves (they stay transient; only
  the human-facing `label` is stored — §3.2).
- A dedicated "how often did I have X" query feature — existing history retrieval
  consumes the new `label`/embedding; no new endpoint here.
- Backfilling `label` on pre-existing `meal_log` rows.
- Semantic/embedding-based composite detection.
- A Telegram inline button for Combine (chat correction covers it).
