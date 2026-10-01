# Implementation Plan: Edit Saved Meals

**Branch**: `006-edit-saved-meals` (spec directory only). Work happens on
`feat/android-app`, following the production-branch rule in project memory.
**Date**: 2026-10-01 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/006-edit-saved-meals/spec.md`

## Summary

Saved meals become editable: rename, change grams, remove, add and swap
ingredients. This needs one new backend route, `PUT /my-meals/{id}`, which
replaces the whole meal and uses `updated_at` for optimistic concurrency.
Ingredients are sent as card items with an optional `target_qty_g`. The server
rescales them with the existing `_scaled_result`, which keeps unknown
nutrients unknown, and recomputes the totals. Chat recall needs no change
because it reads `name_normalized` live.

**Add/swap (US4)** go through a second new route,
`POST /my-meals/resolve-ingredient`. It runs the same steps as chat logging
with different context: a structured LLM call
(`ReplacementResult` → exactly one food), then the server's grams rule, then
the existing `usda_lookup_batch` with its estimate fallback. It gets only the
user's text, the meal name and the row being replaced. It costs 1 usage
credit through the shared `consume_llm_credit`. It is stateless, so the
editor stores the result only on Save. Its accuracy is gated by a new eval
category, `ingredient_replace` (≥ 90% over 5 live runs, SC-007).

Three supporting changes, all additive:
1. **Save-from-chat parity**: `POST /my-meals` scales server-side from
   `target_qty_g` and `portion`. Web then sends the edited items. This fixes
   the gap the user found.
2. **Update offer**: the chat card response carries `saved_meal` so clients can
   offer "Update in My Meals" after a changed log.
3. **Logged today**: logs from a saved meal stamp `flags.saved_meal_id`, so
   the "logged today" marker survives a rename.

There is no migration and no new dependency. There is one new prompt file.

## Technical Context

**Language/Version**: Python 3.13 (backend) · TypeScript / React 19 (web) ·
Kotlin / Jetpack Compose (Android)

**Primary Dependencies**: FastAPI, SQLAlchemy async, LangGraph (one state
field), LangChain Gemini (`make_llm().with_structured_output`, already used
for extraction), TanStack Query (web), Retrofit + kotlinx.serialization
(Android). No new dependencies.

**Storage**: Supabase Postgres. Existing `user_meal` (ingredients JSONB,
`updated_at`, `name_normalized` + its partial unique index) and `meal_log.flags`
JSONB. **No migration** ([data-model.md](data-model.md)).

**Testing**:
- pytest + pytest-asyncio: extend `tests/test_my_meals_*.py`, and add
  `tests/test_replace_ingredient.py` with the LLM, quota and lookup mocked.
- Vitest: web editor, save payload, ingredient input.
- JUnit: Android `:core:domain` for `EditMealState`, `:core:data` for DTOs.
- Live LLM eval: `eval/gate.py --only ingredient_replace --runs 5`.

**Target Platform**: Railway `web` (API) · Netlify (web) · Android app (feat/android-app).

**Project Type**: Web service + web app + Android app.

**Performance Goals**:
- `PUT` is one locked read and one write, so it takes about the same time as
  the existing `POST /my-meals`.
- The editor's live totals are computed on the client with no network calls.
- `resolve-ingredient` p95 ≤ 3 s (one Flash call with thinking off, plus a
  local DB lookup; R9). Hard timeout 10 s.
- SC-001: an edit saved in under 30 s.

**Constraints**:
- Every API change is a new route or an additive field, because the shipped
  Android build and Telegram must keep working.
- The server never trusts client totals, or the model's grams on a swap
  without a stated amount.
- Usage credits go only through `consume_llm_credit`; the quota model is a
  placeholder that will change.
- Past logs are never changed (FR-009).
- Name rules are shared with `POST`.

**Scale/Scope**: About 5 backend files changed (`api/my_meals.py`,
`api/meals.py`, `agent/graph.py`, `agent/orchestrator.py`, `quota.py`). 1 new
tool module, 1 new prompt, 1 eval case file and 1 gate category. On web, 3 new
components and 2 changed. On Android, 1 new screen, 1 new state class, and
changes to the repository, API and DTOs.

No NEEDS CLARIFICATION remain. R1–R12 in [research.md](research.md) resolve
every unknown. The add/swap design (R7–R10) follows the 2026-10-01
clarifications in the spec. One scope choice (R5: the update offer ignores
the portion) is listed under research's "Open items".

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` is still the unfilled template, so no
constitutional gate can fail. As in 001 and 002, the plan is checked against
`.claude/CLAUDE.md` and project memory:

| Rule | Pre-design | Post-design |
|---|---|---|
| Pydantic for all boundary data, `extra="forbid"` on requests | ✅ planned | ✅ `UpdateMealRequest` forbids extra fields. Ingredient items stay `extra="allow"`, as in `IngredientIn` today, so card fields are stored as sent |
| All I/O async, no blocking calls | ✅ | ✅ only async SQLAlchemy |
| Specific exceptions, no bare except | ✅ | ✅ `IntegrityError` → 409 `name_taken` |
| Type annotations + Google docstrings | ✅ | ✅ |
| TS: no `any`, one component per file, components under ~120 lines, data fetching in hooks | ✅ | ✅ editor, row and ingredient input split; `useUpdateMeal`/`useResolveIngredient` hooks; shared `meal-math.ts` |
| Surface errors, never swallow (TS standards; #52/#55 precedent) | ✅ | ✅ 409 `meal_changed` reloads with a notice; network failure keeps the edits and shows Retry |
| Never commit/push to production without explicit say-so | ✅ | ✅ work on `feat/android-app` |
| Prod DB reachable from the local backend (memory) | ⚠️ noted | ✅ the quickstart says to use a test account only |
| Simplicity: no migration unless needed | ✅ | ✅ reuses `updated_at` and `flags` JSONB |
| Prompts live in `config/prompts/*.md`, validated at import | ✅ | ✅ new `replace_ingredient_system.md` + `PromptsConfig` field |
| LLM behaviour gated by eval (001 routing-gate precedent) | ✅ | ✅ `ingredient_replace` gate category, absolute floor of 90% (R10) |
| Observability: Logfire, not LangSmith (memory) | ✅ | ✅ `resolve_ingredient` span (R9) |

No violations, so Complexity Tracking is empty.

## Project Structure

### Documentation (this feature)

```text
specs/006-edit-saved-meals/
├── spec.md
├── plan.md              # this file
├── research.md          # R1–R12
├── data-model.md
├── quickstart.md
├── contracts/
│   └── my-meals-api.md
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks (not created here)
```

### Source Code (repository root)

```text
src/backend/
├── api/my_meals.py          # + PUT /{id}; POST target_qty_g/portion; updated_at;
│                            #   name_taken/meal_changed 409s; logged_today via flags;
│                            #   log_my_meal stamps saved_meal_id + label
├── api/meals.py             # LogItemsRequest.saved_meal_id → flags + label;
│                            #   /meals/pending passes saved_meal through
├── agent/graph.py           # AgentState.saved_meal_id; saved_lookup_node sets it;
│                            #   log_node labels with the saved name + stamps the flag
├── agent/orchestrator.py    # response + get_pending_card add `saved_meal`
├── agent/tools/meals.py     # persist_meal/log_meal accept extra flags (saved_meal_id)
├── agent/tools/replace_ingredient.py  # NEW: ReplacementResult schema, resolve_ingredient()
│                            #   (credit → LLM → 1-food check → grams rule → usda_lookup_batch)
├── config/prompts/replace_ingredient_system.md  # NEW prompt
├── config/__init__.py       # PromptsConfig.replace_ingredient_system
└── quota.py                 # UPGRADE_MSG moved here (shared with orchestrator)

eval/
├── cases/ingredient_replace.jsonl  # NEW ≥40 cases (R10)
└── gate.py                  # + ingredient_replace category, absolute-floor check

tests/
├── test_replace_ingredient.py  # NEW: 1/0/2 foods, 402, 503, grams rule, estimate flag
├── test_my_meals_api.py     # PUT, POST scaling, 409s, 404s, logged_today, resolve route
├── test_my_meals_graph.py   # saved_meal_id in state + response; rename → recall
└── test_my_meals_log.py     # flags.saved_meal_id on all log paths

frontend/src/
├── api/hooks.ts             # + useUpdateMeal, useResolveIngredient
├── api/types.ts             # + updated_at, SavedMealRef, UpdateMealRequest
├── lib/meal-math.ts         # NEW: shared scale + totals (from MyMealCustomizer)
├── components/my-meals/
│   ├── my-meal-editor.tsx       # NEW (US1, US4)
│   ├── my-meal-editor-row.tsx   # NEW
│   └── ingredient-input.tsx     # NEW (US4): free text, swap or add, inline errors
├── components/chat/ConfirmationCard.tsx  # save finalItems+portion (US2); update offer (US3)
├── components/chat/MyMealCustomizer.tsx  # use meal-math; update offer after a customized log
└── pages/MyMealsPage.tsx                 # Edit entry point

android/
├── core/domain/.../EditMealState.kt         # NEW pure state + tests
├── core/data/.../api/MealsyApi.kt, Dtos.kt  # updateMyMeal, resolveIngredient, updated_at, saved_meal
├── core/data/.../repo/MyMealsRepository.kt  # update(), resolveIngredient(); 409/402/422 mapping
├── app/.../ui/mymeals/EditMealScreen.kt     # NEW route (US1)
├── app/.../ui/mymeals/IngredientInputSheet.kt  # NEW (US4)
├── app/.../ui/mymeals/MyMealsScreen.kt      # Edit entry point
└── app/.../ui/chat/ChatSessionStore.kt      # snapshot + update offer (US3)
```

**Structure Decision**: These are the existing backend, web and Android
layouts, with no new top-level modules. Web My Meals components move into a
new `components/my-meals/` folder, because the editor is not a chat component.

## Delivery order (each slice can ship on its own)

1. **Backend P1**: `PUT`, `updated_at`, `POST` scaling, 409 codes, and tests.
   Nothing changes for current clients.
2. **Web P1**: save-from-card parity (US2) and the editor without add/swap
   (US1).
3. **Android P1**: `EditMealScreen` (US1). US2 already works on Android, so
   only add the null-fibre test from research R4.
4. **P2 (US3)**: `saved_meal_id` in the graph and response, flag stamping, and
   the update offer on both clients.
5. **P3 (US4)**:
   1. The backend `resolve_ingredient` and prompt, plus unit tests.
   2. The eval cases and gate; iterate on the prompt until it reaches ≥ 90%.
   3. Then the web `ingredient-input` and the Android `IngredientInputSheet`.

   The clients wait until the gate passes.

## Complexity Tracking

No constitution violations to justify.
