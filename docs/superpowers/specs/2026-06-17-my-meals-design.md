# My Meals — Ingredient Decomposition & Saved Meals — Design Spec

**Date:** 2026-06-17
**Status:** Approved (Approach A)
**Scope:** Let the agent break a described meal into its individual ingredients
with gram weights (macros/micros still totalled as today), let the user save
that meal to a personal **My Meals** library, and retrieve it on re-mention —
both auto-detected from free text and via an explicit picker.

---

## 1. Overview & decisions (locked with user)

- **Decomposition is per-meal opt-in.** Default logging is unchanged. The
  confirmation card gains a **"Break into ingredients"** action that decomposes
  the current dish (e.g. "chicken biryani" → rice, chicken, ghee, onion, spices)
  into ingredients with grams; each ingredient resolves through the existing
  USDA pipeline and the card re-renders. Totals (carbs/protein/fiber + micros)
  are summed exactly as today.
- **Save is explicit.** A **"Save to My Meals"** action persists the current
  resolved ingredient list + totals under a name (default = the user's phrase,
  editable).
- **Retrieval is both auto + explicit.** (a) Auto-detect: typed text that
  matches a saved meal name prefills the card from the saved ingredients,
  skipping fresh estimation. (b) Explicit: a My Meals dashboard page lists saved
  meals to pick and log.
- **Portioning is both.** The card offers a portion **multiplier** (0.5×/2×/
  custom) that scales every ingredient + totals, *plus* the existing
  per-ingredient gram edits.
- **Approach A:** the decomposition step is a **shared backend primitive** also
  used by the recipe-import feature (same operation, different trigger) — built
  once, not duplicated.

## 2. Architecture (Approach A)

Reuses the LangGraph meal flow, the confirmation card, `usda_lookup_batch`, the
`entities` JSONB shape, and the pgvector pattern. New surface is additive.

**Shared primitive** `decompose_to_ingredients(description: str) -> list[str]`
in a new `backend/agent/tools/decompose.py` (or `recipe.py` if built jointly):
an LLM call that returns ingredient lines ("150 g basmati rice", "120 g chicken
thigh", …). The recipe-import LLM-parse path calls the same primitive. Output
lines feed the existing `extract_entities` → `usda_lookup_batch`, so resolution,
confidence, and the LLM-estimate fallback are unchanged.

## 3. Data model

### 3.1 `user_meal` table (migration `007_user_meals`)
```
id              uuid PK
user_id         uuid FK → user_goal.user_id ON DELETE CASCADE
name            text  NOT NULL              -- display name
name_normalized text  NOT NULL              -- lower/trim/collapse-space, for match
ingredients     jsonb NOT NULL              -- list, same shape as meal_log.entities
                                            --   {food_name, qty_g, fdc_id, source,
                                            --    estimated, nutrients, kcal, protein_g,
                                            --    carbs_g, fat_g, fiber_g}
kcal            float NOT NULL              -- denormalized base totals (1× portion)
protein_g       float NOT NULL
carbs_g         float NOT NULL
fat_g           float NOT NULL
fiber_g         float NOT NULL
embedding       vector(768)  NULL           -- for semantic match (V2; populated async)
created_at      timestamptz default now()
updated_at      timestamptz default now()
deleted_at      timestamptz NULL
UNIQUE (user_id, name_normalized) WHERE deleted_at IS NULL
```
RLS: enable, policy `auth.uid() = user_id` for all ops (matches existing tables).
Index: `ix_user_meal_user_normalized (user_id, name_normalized)` for the
auto-detect lookup; IVFFlat on `embedding` deferred to the semantic-match V2.

### 3.2 ORM
`UserMeal` in `db/models.py` mirroring the columns.

## 4. Backend services & API

New router `backend/api/my_meals.py` (`/my-meals`), auth-required:
- `GET /my-meals` → list (id, name, totals, n_ingredients, created_at).
- `GET /my-meals/{id}` → full record incl. ingredients.
- `POST /my-meals` → body `{name, ingredients[]}`; normalizes name, computes
  totals server-side from ingredients (don't trust client totals), 409 on
  duplicate `name_normalized`. Enqueues embedding (Celery, reuse the meal-embed
  task pattern).
- `DELETE /my-meals/{id}` → soft-delete (`deleted_at`).

**Auto-detect on log** (orchestrator): before fresh extraction in the
meal-logging path, a fast `find_saved_meal(user_id, text)` normalizes the input
and exact-matches `user_meal.name_normalized`. On hit, the graph skips
extract+usda and presents the card built from the saved `ingredients` (flagged
`from_saved=True`, carrying `user_meal_id`). V1 = normalized-exact only (very low
false-match); the stored embedding enables semantic match as a measured V2
(ties into #6). On miss, the normal pipeline runs.

**Decompose on toggle:** new graph node / orchestrator branch invoked by the
card action — runs `decompose_to_ingredients` on the original description →
`usda_lookup_batch` → re-presents the same paused card with the ingredient list.

## 5. Frontend

- **ConfirmationCard** gains: (a) a **"Break into ingredients"** button (when the
  current items look like a single composite dish), (b) a **"Save to My Meals"**
  button + name field, (c) a **portion multiplier** control (scales displayed
  items + totals; the existing per-item gram steppers remain). A "from My Meals"
  badge shows when the card was prefilled from a saved meal.
- **My Meals page** (`/my-meals` route + nav entry): lists saved meals (name,
  macro summary, ingredient count); actions: **Log** (loads onto the chat card,
  with multiplier) and **Delete**. New `MyMealsPage.tsx` + `MyMealCard.tsx`.
- Types + hooks: `MyMeal`, `useMyMeals`, `useSaveMeal`, `useDeleteMeal` in the
  existing `api/types.ts` / `api/hooks.ts`.
- Threading: the existing `onAction`/log request carries an optional
  `user_meal_id` + `portion` so a logged-from-saved meal records provenance and
  the scaled entities.

## 6. Data flow (re-log a saved meal)
typed "chicken biryani" → `find_saved_meal` hit → card prefilled from saved
ingredients (skip LLM/USDA) with "from My Meals" badge → user sets multiplier /
edits grams → confirm → `meal_log` row stores the final scaled `entities`
(unchanged downstream: totals, history, meal-category, embeddings all work).

## 7. Error handling
- Decompose returns nothing / junk → keep the original single item, tell the
  user "couldn't break that down, logging as one item."
- Save duplicate name → 409; frontend offers overwrite (PUT) or rename.
- Partial USDA resolution on decomposed ingredients → per-item "≈ estimated"
  flags (same honest treatment as recipe-import); micros partial.
- Multiplier ≤ 0 / NaN → rejected client-side (reuse the gram-edit guard).

## 8. SDLC / sequencing
1. Migration `007` + `UserMeal` ORM (+ RLS, applied to Supabase before deploy —
   same flow as migration 006).
2. Shared `decompose_to_ingredients` primitive + the "Break into ingredients"
   graph branch.
3. `/my-meals` API + `find_saved_meal` auto-detect.
4. Frontend: card actions (decompose/save/multiplier) → My Meals page.
5. Tests at each step (below); deploy after migration applied.
**Dependency:** shares the decomposition primitive with the recipe-import spec
(`2026-06-16-recipe-import-design.md`) — build the primitive once; if recipe
import isn't built yet, this feature introduces it and recipe import consumes it.

## 9. Testing
| Layer | Tests |
|---|---|
| `decompose_to_ingredients` | mocked LLM → ingredient lines; empty/garbage → graceful single-item fallback |
| `find_saved_meal` | normalized hit/miss; case/whitespace insensitivity; per-user isolation |
| `/my-meals` API | CRUD; 409 on dup name; totals computed server-side; 401 without auth; soft-delete hides row |
| portion scaling | multiplier scales every ingredient + totals; identity at 1× |
| migration | `007` adds table + RLS; existing data unaffected |
| frontend | tsc + lint; card decompose/save/multiplier; My Meals list/log/delete |

## 10. Out of scope (V1)
Semantic/fuzzy auto-match (embedding stored now, used later — #6); sharing meals
between users; auto-save without the explicit action; editing a saved meal's
stored ingredients in place (V1 = delete + re-save).

## 11. File map (indicative)
| File | Change |
|---|---|
| `src/backend/db/migrations/versions/20260617_007_user_meals.py` | New table + RLS |
| `src/backend/db/models.py` | `UserMeal` ORM |
| `src/backend/agent/tools/decompose.py` | Shared `decompose_to_ingredients` |
| `src/backend/agent/graph.py`, `orchestrator.py` | decompose branch + `find_saved_meal` prefill |
| `src/backend/api/my_meals.py` | `/my-meals` CRUD router |
| `src/backend/main.py` | register router |
| `src/backend/config/prompts/decompose_system.md` (post-refactor) or tunables | decompose prompt |
| `src/backend/workers/tasks.py` | embed saved meal (async) |
| `frontend/src/components/chat/ConfirmationCard.tsx` | decompose / save / multiplier actions |
| `frontend/src/pages/MyMealsPage.tsx`, `components/.../MyMealCard.tsx` | My Meals UI |
| `frontend/src/api/types.ts`, `api/hooks.ts` | MyMeal type + hooks |
| `tests/test_decompose.py`, `test_my_meals_api.py`, `test_my_meals_match.py` | tests |
