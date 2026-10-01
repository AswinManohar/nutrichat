# Data Model: Edit Saved Meals

**No migration.** Every change below uses columns that already exist
(`user_meal.updated_at`, `user_meal.name_normalized`, `meal_log.flags` JSONB).

## SavedMeal (`user_meal`, existing)

| Field | Type | Change | Rules |
|---|---|---|---|
| `id` | uuid | none | |
| `user_id` | uuid | none | Owner. Every read and write is filtered by it (FR-017). |
| `name` | text | **editable** | Trimmed. Must not be empty after `normalize_meal_name`. |
| `name_normalized` | text | **recomputed on rename** | Unique per user among live rows (the partial index `ix_user_meal_user_normalized` already enforces this). Chat recall matches on it. |
| `ingredients` | jsonb list | **replaced on edit** | At least 1 item. Each item is a SavedIngredient (below). |
| `kcal`, `protein_g`, `carbs_g`, `fat_g`, `fiber_g` | float | **recomputed server-side** on every write | The sum of the ingredients' macros. Unknown counts as 0 in totals, the same as today. |
| `updated_at` | timestamptz | **now exposed in the API** | The optimistic-concurrency token (research R2). |
| `deleted_at` | timestamptz | none | A soft-deleted row can't be edited (404) and is never brought back. |
| `embedding` | vector | none | Unused. Left as is. |

**Lifecycle**: created by `POST` (save), then modified any number of times by
`PUT` (edit). Each `PUT` replaces the name and ingredients completely. It ends
with `DELETE` (soft delete). A meal keeps no history of earlier versions.

## SavedIngredient (an element of `user_meal.ingredients`, existing shape)

This is the same shape as a `meal_log.entities` item / `USDAResult`:
`food_name`, `qty_g` (> 0), `kcal`, `protein_g`, `carbs_g`, `fat_g`,
`fiber_g`, `sugar_g`, `sat_fat_g` (any non-kcal value may be `null` = unknown),
`unknown_nutrients[]`, `nutrients{}`, `fdc_id` (-1 for an estimate), `source`,
`estimated`, `match_confidence`, `candidates[]`.

**On write**, the client sends each ingredient as a card item plus an optional
`target_qty_g`. The server stores
`_scaled_result(item, target_qty_g or qty_g, portion)`, which scales `qty_g`,
every macro and every `nutrients[*].amount` by the same ratio. A `null` or
listed-unknown macro stays unknown (FR-004). `estimated` and `source` pass
through unchanged (FR-015).

## MealLog (`meal_log`, existing). Flags are additive only.

| Field | Change |
|---|---|
| `flags.saved_meal_id` | **new optional key.** Set when the log came from a saved meal through any path (research R6). |
| `label` | For logs from a saved meal, it is the saved meal's current name at log time. |

A logged row is never updated when its saved meal is edited (FR-009).

**"Logged today"** for a saved meal M is true when a live log from today has
`flags->>'saved_meal_id' = M.id`, or when its `label = M.name` (legacy rows).

## Graph state (`AgentState`, `src/backend/agent/graph.py`)

| Field | Change |
|---|---|
| `saved_meal_id: str \| None` | **new.** Set by `saved_lookup_node` on a hit and cleared on a miss. Read by the chat response builder, by `log_node` (flag + label), and by `GET /meals/pending`. |

## ReplacementResult (LLM structured output, not stored)

| Field | Type | Rules |
|---|---|---|
| `foods` | list[ReplacementFood] | The model may return 0..n items. The server accepts **exactly 1**; otherwise the response is `422 rephrase` (FR-014a) |
| `foods[].food_name` | str | USDA-style specific name. It is the input to `usda_lookup_batch` |
| `foods[].qty_g` | float > 0 | Grams for the stated amount, or the model's typical portion |
| `foods[].unit` | str | The original unit as said ("cup", "tbsp", "slice", "g", "serving") |
| `foods[].amount_stated` | bool | True only when the user's text gives an explicit amount or count |

**Derived entity → lookup**: `{food_name, qty_g: final_g, unit}` with
`final_g = replacing.qty_g` for a swap with no stated amount, otherwise
`qty_g`. The result of `usda_lookup_batch` is the returned card `item`. That
is a SavedIngredient-shaped item, so the editor can insert it as it is, and
`PUT` stores it like any other ingredient.

## Client edit state (web `my-meal-editor`, Android `EditMealState`)

`{ mealId, baseUpdatedAt, name, rows: [{ item, qtyG, removed }], dirty }`

- `totals` is derived the same way `CardEditor.totals` does on Android and
  through the shared web `meal-math`.
- **Save** is enabled only when the meal is dirty, the name normalizes to a
  non-empty value, every kept row has `qtyG > 0`, and at least one row is
  kept.
- **Swap** replaces `row.item` with the resolved item and sets `qtyG` from
  `item.qty_g` (the server already applied the grams rule). **Add** appends a
  row from the resolved item. While a resolve is in flight, that row (or the
  add box) is busy. Save is disabled until it finishes.
