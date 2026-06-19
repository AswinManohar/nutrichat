# My Meals — Customize & Quick-Log Meal Type — Design Spec

**Date:** 2026-06-19
**Status:** Approved
**Scope:** Let the user log a saved meal straight from the **My Meals** page —
either as a one-tap **Log** with a meal-type picker, or via an inline
**Customize** editor that adjusts the saved ingredient breakdown (grams, removal,
portion) before logging. No round-trip through the chat confirmation card.

Builds on `2026-06-17-my-meals-design.md` (saved meals already store a resolved
`ingredients` JSONB breakdown).

---

## 1. Overview & decisions (locked with user)

- **Customize is inline on the My Meals page.** Each saved-meal row gains a
  **"Customize"** toggle that expands an in-place editor: per-ingredient gram
  steppers + remove, a portion multiplier (0.5×/1×/1.5×/2×), live totals, a
  meal-type picker, and a **"Log this meal"** button. No navigation to chat.
- **Log is a quick path.** The plain **Log** button becomes a small meal-type
  dropdown (breakfast/brunch/lunch/dinner/snack — same set as the confirmation
  card). Picking a category logs the stored meal **at 1× with no edits**.
- **Customize edits are log-only.** They affect the logged `meal_log` row, not
  the saved template. Editing a saved meal's stored ingredients in place stays
  **out of scope** (V1 = delete + re-save), consistent with the My Meals spec.
- **One backend endpoint** serves both Log and Customize, reusing the existing
  `log_meal()` commit primitive so flags, Redis today-totals, and the embedding
  enqueue behave exactly as chat logging does.

## 2. Architecture

Today the only path that writes a `meal_log` row is the chat LangGraph flow
(`handle_message` → confirm → `log_meal`). This feature adds a direct,
graph-free log path for saved meals.

`log_meal(user_id, usda_results, meal_type)` in `agent/tools/meals.py` already
totals macros, inserts the row (`_insert_meal_log` with `_junk_flags`),
increments Redis today-totals (`increment_today`), and enqueues the meal
embedding. The new endpoint reconstructs `USDAResult` objects from the stored
(optionally scaled) ingredient dicts and calls this same primitive — no logic
duplicated.

## 3. Backend service & API

New endpoint in `backend/api/my_meals.py`, auth-required:

`POST /my-meals/{meal_id}/log`

Request body:
```
meal_type    str            -- one of MEAL_CATEGORIES; 422 otherwise
portion      float = 1.0    -- global multiplier, gt 0
ingredients  list | None    -- optional per-ingredient override:
                            --   [{index: int, qty_g: float gt 0}, ...]
                            -- omitted indices keep stored qty; indices absent
                            -- from the list when `ingredients` is provided are
                            -- treated as removed.
```

Behavior:
- Load `UserMeal`; 404 if missing, not owned, or soft-deleted (same guard as
  `get_meal`).
- **Server-side scaling — never trust client macros.** For each kept stored
  ingredient, `scale = (edited_qty_g × portion) / stored_qty_g`. Apply `scale`
  to `qty_g`, the promoted macros (`kcal, protein_g, carbs_g, fat_g, fiber_g,
  sugar_g, sat_fat_g`), **and** every value in the nested `nutrients` dict
  (micros feed `/nutrient-checkup`).
- **Quick Log** sends no `ingredients` and `portion=1.0` → logs the stored meal
  verbatim.
- Reconstruct `USDAResult(**scaled_dict)` per kept ingredient → call
  `log_meal(user_id, results, meal_type)`.
- Returns the existing `MealLogResult` shape (`meal_id`, totals, message).

Validation: unknown `meal_type` → 422; `portion ≤ 0` or any `qty_g ≤ 0` → 422;
empty result set (all removed) → 422.

## 4. Frontend

**My Meals page (`MyMealsPage.tsx`):**
- **Log → meal-type dropdown.** Reuses the same picker UI + `MEAL_CATEGORIES` as
  the confirmation card. Selecting a category calls `useLogMyMeal` at 1×, shows a
  success state, and refetches today-totals.
- **"Customize" toggle.** Expands an inline `MyMealCustomizer` panel that fetches
  full ingredients via `GET /my-meals/{id}` on first expand, then offers:
  per-ingredient gram steppers + remove, portion multiplier, live totals, a
  meal-type picker, and **"Log this meal"** (calls `useLogMyMeal` with the
  edited `ingredients` override + portion + meal_type).
- If a row's body grows past ~120 lines, split `MyMealCustomizer` into its own
  file (keeps `MyMealsPage` focused).

**Types + hooks:** `LogMyMealRequest`/response in `api/types.ts`; `useLogMyMeal`
mutation in `api/hooks.ts` (invalidates today-totals + history on success).

## 5. Code reuse

The meal-type dropdown, portion control, gram-stepper row, and linear scaling
math currently live inside `ConfirmationCard`. Extract the shared pieces so both
the card and the customizer use one copy:
- `MealTypePicker` component (the dropdown + `CATEGORY_LABELS`).
- a `scaleItem`/`scaleNutrients` helper for the per-ingredient scale math.

`ConfirmationCard`'s confirm path (text corrections → graph) is **unchanged**;
only its presentational sub-pieces are factored out.

## 6. Data flow

**Quick Log:** click Log → pick "Lunch" → `POST /my-meals/{id}/log {meal_type:
"lunch"}` → `log_meal` writes row + bumps Redis → today-totals refetch.

**Customize:** expand → `GET /my-meals/{id}` → user drops an ingredient + sets
1.5× → "Log this meal" → `POST /my-meals/{id}/log {meal_type, portion:1.5,
ingredients:[{index,qty_g}…]}` → server scales from stored base → `log_meal`.

## 7. Error handling

- Meal not found / not owned / deleted → 404; frontend toasts and collapses.
- Invalid `meal_type` / `portion ≤ 0` / `qty_g ≤ 0` / all-removed → 422.
- Log mutation failure → toast; the customizer panel stays open with edits intact.
- Client guards portion/qty ≤ 0 before sending (reuse the gram-edit guard).

## 8. SDLC / sequencing

1. Backend: `POST /my-meals/{id}/log` (scaling + `USDAResult` reconstruction +
   `log_meal` reuse) with tests.
2. Frontend: extract `MealTypePicker` + scaling helper from `ConfirmationCard`.
3. Frontend: My Meals Log dropdown + `MyMealCustomizer` + `useLogMyMeal`.
4. tsc + lint; manual QA of quick-log and customized-log totals.

No migration — `user_meal` and `meal_log` schemas are unchanged.

## 9. Testing

| Layer | Tests |
|---|---|
| `POST /my-meals/{id}/log` | quick log (no override) writes a row with stored totals; portion + gram override scales macros **and** nutrients; removed ingredient excluded; per-user isolation (404 on other user's meal); 401 without auth |
| validation | bad `meal_type` → 422; `portion ≤ 0` → 422; `qty_g ≤ 0` → 422; all-removed → 422 |
| reuse | logged row carries `flags.has_junk`; Redis today-totals incremented; embedding enqueued (same as chat log) |
| frontend | tsc + lint; Log dropdown logs at 1×; customizer scaling matches server; today-totals refetch on success |

## 10. Out of scope (V1)

In-place editing of the saved template (still delete + re-save); candidate
("Not the right food?") switching inside Customize; re-resolving ingredients
through USDA on log (scaling is linear from the stored resolved values); saving
a customized variant as a new meal from this panel.

## 11. File map (indicative)

| File | Change |
|---|---|
| `src/backend/api/my_meals.py` | `POST /{meal_id}/log` endpoint + scaling helper |
| `tests/test_my_meals_log.py` | endpoint scaling/validation/auth tests |
| `frontend/src/api/types.ts` | `LogMyMealRequest` + response types |
| `frontend/src/api/hooks.ts` | `useLogMyMeal` mutation |
| `frontend/src/pages/MyMealsPage.tsx` | Log dropdown + Customize expand |
| `frontend/src/components/chat/MealTypePicker.tsx` | extracted shared picker |
| `frontend/src/components/.../MyMealCustomizer.tsx` | inline editor (if split out) |
| `frontend/src/components/chat/ConfirmationCard.tsx` | consume extracted picker + helper |
