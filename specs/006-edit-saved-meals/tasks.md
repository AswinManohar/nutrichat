# Tasks: Edit Saved Meals

**Input**: Design documents from `specs/006-edit-saved-meals/`

**Prerequisites**:
- [plan.md](plan.md)
- [spec.md](spec.md)
- [research.md](research.md) (R1–R12)
- [data-model.md](data-model.md)
- [contracts/my-meals-api.md](contracts/my-meals-api.md)
- [quickstart.md](quickstart.md)

**Tests**: Included. The plan and quickstart list the required automated
tests, and SC-007 requires an LLM eval gate.

**Conventions for every task**:
- Python follows `.claude/CLAUDE.md`:
  - `from __future__ import annotations`, full type hints, Google docstrings;
  - async I/O only, no bare `except`, 88 columns.
- TS follows CLAUDE.md:
  - no `any`, one component per file, components ≤ ~120 lines;
  - data fetching in hooks, `@/` imports.
- Run backend commands with `PYTHONPATH=src`.
- After each task, commit and push `feat/android-app` using the user's git
  identity, with no Claude co-author trailer. Stage only your own hunks.
  Never push to a production branch.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an
  unfinished task)
- **[Story]**: US1–US4 from spec.md

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Small refactors that later phases build on.

- [X] T001 Move the upgrade text into `src/backend/quota.py`:
  - Move `_UPGRADE_MSG` from `src/backend/agent/orchestrator.py:549` to
    `src/backend/quota.py` as a public `UPGRADE_MSG`, with identical text.
  - Import it in `orchestrator.py` and replace all 3 uses (lines ~302, ~496,
    ~586). Keep a module alias `_UPGRADE_MSG = UPGRADE_MSG` only if a test
    imports the old name; check with `grep -rn _UPGRADE_MSG tests/`.
  - Run `pytest tests -q -k "quota or orchestrator"`.
- [X] T002 [P] Give web API errors a structured detail:
  - In `frontend/src/api/client.ts`, extend `ApiError` with a readonly
    `detail: unknown` (constructor `(message, status, detail?)`).
  - Where non-OK responses are handled, parse the JSON body. Pass `body.detail`
    as `detail`, and use it as the message when it is a string.
  - Add a type guard `isErrorCode(detail: unknown, code: string): boolean`
    that returns true when `detail === code` or
    `(detail as {code?: unknown}).code === code`.
  - Extend `frontend/src/api/client.test.ts` with cases for a string detail
    and an object detail.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Server-side ingredient scaling, `updated_at` exposure and error
codes. US1, US2 and US4 all depend on these.

**⚠️ CRITICAL**: Finish this phase before starting any user story.

- [X] T003 Add a shared server-side ingredient builder in
  `src/backend/api/my_meals.py`:
  - Add `target_qty_g: float | None = Field(default=None, gt=0)` to
    `IngredientIn`.
  - Make `kcal` through `fiber_g` `float | None` (default `0.0`) so that an
    unknown `null` is accepted.
  - Add a private `_build_ingredients(items: list[IngredientIn], portion:
    float) -> list[dict]`. For each item:
    - `raw = item.model_dump(exclude={"target_qty_g"})`;
    - `scaled = _scaled_result(raw, item.target_qty_g or item.qty_g,
      portion)`;
    - return `{**raw, **scaled.model_dump()}`. Extra card fields (`unit`,
      `unknown_nutrients`, `source_dish`, …) survive; scaled values win.
  - Change `_totals` to sum over the built dicts with `(d.get(f) or 0.0)`,
    so unknown counts as 0 in totals (data-model.md).
- [X] T004 Expose `updated_at` and switch 409s to error codes in
  `src/backend/api/my_meals.py`:
  - Add `updated_at: datetime` to `MyMealDetail`. Populate it in `get_meal`
    and `save_meal` from `meal.updated_at`, ISO-8601 with microseconds.
  - Change the `POST /my-meals` duplicate-name 409 to
    `HTTPException(409, detail="name_taken")` (research R3).
- [X] T005 [P] Add foundational tests in `tests/test_my_meals_api.py`:
  - `_build_ingredients` scales `qty_g`, the macros and `nutrients[*].amount`
    by `(target_qty_g or qty_g) * portion / qty_g`.
  - A `null` `fiber_g`, or one listed in `unknown_nutrients`, stays `None`.
  - Extra fields pass through.
  - `GET /my-meals/{id}` includes `updated_at`.
  - A duplicate `POST` returns `{"detail": "name_taken"}`.
- [X] T006 [P] Update the web types in `frontend/src/api/types.ts`:
  - Add `updated_at: string` to `MyMealDetail`.
  - Add `target_qty_g?: number` to the save-ingredient type, and `portion?:
    number` to `SaveMealRequest`.
- [X] T007 [P] Add `updatedAt` to the Android DTO: add `@SerialName("updated_at")
  val updatedAt: String? = null` to `MyMealDetailDto` in
  `android/core/data/src/main/kotlin/app/mealsy/data/api/Dtos.kt`. It is
  nullable so older backends still parse.

**Checkpoint**: The backend scales ingredients itself and exposes
`updated_at`. Existing clients behave the same.

---

## Phase 3: User Story 1 - Edit a saved meal from My Meals (Priority: P1) 🎯 MVP

**Goal**: Rename a saved meal, change ingredient grams and remove ingredients,
with live totals and an explicit Save. Every way of using the meal then uses
the edited version.

**Independent Test**: Quickstart scenarios 1–4, 9 and 10. Save a 3-ingredient
meal, edit grams, remove one ingredient, rename it and save. Quick-log it and
recall it in chat by the new name. Both must show the edited version.

### Tests for User Story 1

- [ ] T008 [P] [US1] Add `PUT /my-meals/{id}` tests in
  `tests/test_my_meals_api.py`, mocking the session as the existing tests do:
  - The happy path recomputes the totals and returns a new `updated_at`.
  - Client totals are ignored.
  - `target_qty_g` rescales an ingredient.
  - 404 for a missing, soft-deleted or other-user meal.
  - 409 `{"detail": "name_taken"}` when the name clashes with another live
    meal.
  - The same name with different capitalization is allowed.
  - 409 `{"detail": {"code": "meal_changed", "current": {...}}}` when
    `expected_updated_at` differs.
  - 422 for an empty or whitespace name, a name that is empty after
    normalizing (e.g. `"!!!"`), `ingredients: []`, or `qty_g <= 0`.
- [ ] T009 [P] [US1] Add a rename/recall test in
  `tests/test_my_meals_match.py`: after `name_normalized` changes from
  "chicken biryani" to "biryani", `_best_saved_match("had biryani for lunch",
  meals)` hits, and `_best_saved_match("chicken biryani", meals)` with only
  the renamed meal does not (FR-007).
- [ ] T010 [P] [US1] Add flag tests in `tests/test_my_meals_log.py`:
  - `POST /my-meals/{id}/log` writes `flags.saved_meal_id == meal.id` and
    `label == meal.name`.
  - `list_meals` reports `logged_today=True` for a meal renamed after it was
    logged today (match via flag), and for a legacy log matched only by label.

### Backend for User Story 1

- [ ] T011 [US1] Add an `extra_flags: dict[str, str] | None = None` keyword
  to `persist_meal` and `log_meal` in `src/backend/agent/tools/meals.py`.
  Merge it into the dict from `_junk_flags(...)` before the `INSERT` (line
  ~478). Document the argument. Existing callers don't change.
- [ ] T012 [US1] Stamp saved-meal logs in `src/backend/api/my_meals.py`:
  - In `log_my_meal`, call `log_meal(..., label=meal_name,
    extra_flags={"saved_meal_id": meal_id})`.
  - In `list_meals`, also select `MealLog.flags["saved_meal_id"].astext`
    for today's live logs. Mark a meal `logged_today` when its id is in that
    set **or** `meal.name` is in the label set (research R6).
- [ ] T013 [US1] Implement `PUT /my-meals/{meal_id}` in
  `src/backend/api/my_meals.py` (contract: "NEW: PUT /my-meals/{id}").
  - **Request**: a new `UpdateMealRequest` with `name: str = Field(min_length=1,
    max_length=120)`, `expected_updated_at: datetime`, `ingredients:
    list[IngredientIn] = Field(min_length=1)`, and `extra="forbid"`.
  - **Name**: `normalize_meal_name(req.name)`. An empty result raises
    `422 "Meal name is empty"`.
  - **Load**: `select(UserMeal).where(UserMeal.id == meal_id).with_for_update()`.
    A missing row, another user's row or a soft-deleted row raises
    `404 "Meal not found"`.
  - **Concurrency**: if `meal.updated_at != req.expected_updated_at`, raise
    `HTTPException(409, detail={"code": "meal_changed", "current":
    MyMealDetail(...).model_dump(mode="json")})`.
  - **Name clash**: query another live meal of the same user with the same
    `name_normalized` and `id != meal_id`, and raise
    `409 detail="name_taken"`.
  - **Write**: `meal.name = req.name.strip()`, `meal.name_normalized =
    normalized`, `meal.ingredients = _build_ingredients(req.ingredients,
    1.0)`, then set the totals from `_totals`.
  - **Commit**: commit and refresh. Catch `sqlalchemy.exc.IntegrityError`
    and raise `409 "name_taken"`.
  - **Response**: return `MyMealDetail` with the new `updated_at`.
  - Never touch `meal_log` (FR-009).
- [ ] T014 [US1] Run `pytest tests/test_my_meals_api.py
  tests/test_my_meals_match.py tests/test_my_meals_log.py -q`, then `black
  src/backend` and `ruff check src/backend --fix`. Fix any failures.

### Web for User Story 1

- [X] T015 [P] [US1] Create `frontend/src/lib/meal-math.ts` by extracting the
  scaling and totals math from
  `frontend/src/components/chat/MyMealCustomizer.tsx`:
  - export `scaleItem(item, qtyG)`, which scales macros proportionally and
    keeps `null` as `null`;
  - export `totals(rows)` for kcal, protein_g, carbs_g, fat_g and fiber_g,
    with null counted as 0.
  - Refactor `MyMealCustomizer.tsx` to use it, with no behavior change.
  - Add `frontend/src/lib/meal-math.test.ts`.
- [X] T016 [P] [US1] Add `useUpdateMeal` in `frontend/src/api/hooks.ts`:
  - a `useMutation<MyMealDetail, ApiError, {id: string; body:
    UpdateMealRequest}>` that calls `apiClient.put('/my-meals/${id}', body)`;
  - on success, invalidate `['my-meals']` and `['my-meals', id]`.
  - Add `UpdateMealRequest` (`name`, `expected_updated_at`,
    `ingredients[]` with `target_qty_g?`) to `frontend/src/api/types.ts`.
  - Add `put` to `apiClient` in `frontend/src/api/client.ts` if it is
    missing.
- [X] T017 [P] [US1] Create
  `frontend/src/components/my-meals/my-meal-editor-row.tsx`. It takes the
  food name, an estimate badge when `item.estimated`, a gram input
  (`type="number"`, `min=1`, with an inline error for ≤ 0 or non-numeric) and
  a remove button. The remove button is disabled when it is the last kept row.
  Props interface sits above the component.
- [ ] T018 [US1] Create `frontend/src/components/my-meals/my-meal-editor.tsx`.
  - **Load**: get the meal with `useMyMeal(id)`.
  - **State**: local `{name, baseUpdatedAt, rows: {item, qtyG, removed}[]}`,
    with live totals via `meal-math.totals` (FR-003).
  - **Save is enabled** only when the meal is dirty, the trimmed name has at
    least one letter or digit, every kept row has `qtyG > 0`, and at least one
    row is kept.
  - **Save** calls `useUpdateMeal` with the kept rows as `{...item,
    target_qty_g: qtyG}`.
  - **409 `meal_changed`**: reset the state from `detail.current` and show
    "This meal changed on another device. Showing the latest version."
  - **409 `name_taken`**: show an inline name error.
  - **Other errors**: keep the edits and show the error with Retry (FR-018).
  - **Cancel** discards the edits (FR-005).
  - Split out a subcomponent if the file goes over about 120 lines.
- [ ] T019 [US1] Wire the editor into `frontend/src/pages/MyMealsPage.tsx`.
  Add an "Edit" button (lucide `Pencil`) on each `MealRow`, next to Customize.
  It opens `MyMealEditor` inline for that meal. Only one editor or customizer
  is open at a time.
- [ ] T020 [P] [US1] Add
  `frontend/src/components/my-meals/my-meal-editor.test.tsx` (Vitest + RTL,
  mock hooks). Cover:
  - editing grams updates the totals;
  - remove is disabled on the last row;
  - the Save payload holds only the kept rows with `target_qty_g` and
    `expected_updated_at`;
  - Cancel makes no call;
  - `meal_changed` reloads from `current`;
  - `name_taken` shows the inline error.

### Android for User Story 1

- [ ] T021 [P] [US1] Add the update call to the Android data layer.
  - In `android/core/data/src/main/kotlin/app/mealsy/data/api/Dtos.kt`, add
    `UpdateMealRequest(name, expectedUpdatedAt @SerialName("expected_updated_at"),
    ingredients: List<ItemDto>)`, plus `targetQtyG` serialization on `ItemDto`
    if it is not already emitted for saves.
  - In `android/core/data/src/main/kotlin/app/mealsy/data/api/MealsyApi.kt`,
    add `@PUT("my-meals/{id}") suspend fun updateMyMeal(@Path("id") id:
    String, @Body body: UpdateMealRequest): MyMealDetailDto`.
- [ ] T022 [US1] Add `update(id, name, expectedUpdatedAt, items)` to
  `android/core/data/src/main/kotlin/app/mealsy/data/repo/MyMealsRepository.kt`.
  - It returns a sealed `UpdateMealResult`: `Saved(detail)`,
    `NameTaken`, `Changed(current: SavedMealDetail)`, `NotFound`,
    `Failed(cause)`.
  - Map HTTP 409 by parsing `detail` (string `"name_taken"` vs object
    `code == "meal_changed"`), and 404 to `NotFound`.
  - Call `myMealsRefreshSignal.notifyChanged()` on `Saved`.
  - Add cases to
    `android/core/data/src/test/kotlin/app/mealsy/data/repo/MyMealsRepositoryTest.kt`.
- [ ] T023 [P] [US1] Create
  `android/core/domain/src/main/kotlin/app/mealsy/domain/EditMealState.kt`,
  a pure data class modeled on `CustomizeSheetState`.
  - Fields: `mealId`, `baseUpdatedAt`, `name`, `rows: List<EditRow(item,
    qtyG, removed)>`.
  - Derived: `totals` via `CardEditor.totals`, `isDirty`, `canSave` (same
    rules as T018), `keptItemsForSave()` (each kept item with `targetQtyG =
    qtyG`).
  - Ops: `rename`, `setQty`, `remove`, which refuses the last kept row,
    `undoRemove`, and `reset(from detail)`.
  - Add `android/core/domain/src/test/kotlin/app/mealsy/domain/EditMealStateTest.kt`.
- [ ] T024 [US1] Create
  `android/app/src/main/java/app/mealsy/android/ui/mymeals/EditMealViewModel.kt`
  (Hilt).
  - It loads the detail through the repository into `EditMealState`, exposes
    a `StateFlow`, and has `save()`.
  - It maps `UpdateMealResult`:
    - `Changed` → reset the state and emit the "changed on another device"
      toast;
    - `NameTaken` → an inline name error;
    - `Failed` → keep the state and show a Retry snackbar.
  - Add a test in
    `android/app/src/test/java/app/mealsy/android/ui/mymeals/EditMealViewModelTest.kt`.
- [ ] T025 [US1] Create
  `android/app/src/main/java/app/mealsy/android/ui/mymeals/EditMealScreen.kt`.
  - A full-screen Compose route with a name `OutlinedTextField`, an
    ingredient list (name, estimate chip, gram field, remove icon), a live
    totals row, and a top bar with Cancel and Save. Save is enabled only when
    `canSave`.
  - It must not clip at 200% font scale (follow the #53 fixes in
    `ConfirmCardView.kt`: buttons grow, totals wrap).
- [ ] T026 [US1] Register a route `my-meals/{mealId}/edit` (use the existing
  `ARG_MEAL_ID` / `navArgument` pattern, line ~564) in
  `android/app/src/main/java/app/mealsy/android/ui/AppNav.kt`. Add an "Edit"
  action per meal in
  `android/app/src/main/java/app/mealsy/android/ui/mymeals/MyMealsScreen.kt`
  that navigates there. On return, the My Meals list refreshes through
  `MyMealsRefreshSignal`.
- [ ] T027 [US1] Run `cd android && ./gradlew :core:domain:test
  :core:data:test :app:testDebugUnitTest`, and fix any failures.

**Checkpoint**: US1 works end to end on web and Android. This is the MVP.

---

## Phase 4: User Story 2 - Saving from chat keeps the user's edits on every app (Priority: P1)

**Goal**: "Save as meal" stores the card exactly as the user last saw it:
removed items left out, edited grams kept, and the portion applied. Web and
Android give the same numbers.

**Independent Test**: Quickstart scenario 5, done on web and on Android with
the same edits. The two saved meals must match.

- [ ] T028 [US2] Apply the portion when saving in `src/backend/api/my_meals.py`:
  - Add `portion: float = Field(default=1.0, gt=0)` to `SaveMealRequest`.
  - In `save_meal`, store `_build_ingredients(req.ingredients, req.portion)`
    and compute the totals from the built dicts.
  - Clients that send neither `target_qty_g` nor `portion` must get exactly
    the same stored values as before.
- [ ] T029 [P] [US2] Add save tests in `tests/test_my_meals_api.py`:
  - a `POST` with `target_qty_g=150` (base `qty_g=200`) and `portion=1.5`
    stores `qty_g=225` with macros × 1.125;
  - a `POST` with neither field stores values unchanged (Android
    compatibility);
  - an unknown fibre stays `None`.
- [ ] T030 [US2] Send the edited card in
  `frontend/src/components/chat/ConfirmationCard.tsx` `handleSaveMeal`
  (lines ~207-213):
  - send `saveMeal.mutate({ name, ingredients: finalItems, portion })`, where
    `finalItems` already holds only visible rows with `target_qty_g`;
  - replace the "portion/edits affect logging, not the saved template"
    comment with one explaining that the save matches the card (FR-010).
- [ ] T031 [P] [US2] Add
  `frontend/src/components/chat/confirmation-card-save.test.tsx`: after
  removing a row, editing grams and setting the portion to 1.5, the Save
  payload has only the kept rows with `target_qty_g`, plus `portion: 1.5`.
- [ ] T032 [P] [US2] Add a null-fibre test to
  `android/core/data/src/test/kotlin/app/mealsy/data/api/ItemDtoTest.kt`:
  `toSavedIngredientDto(portion = 1.5)` on an item with `fiberG = null` (or
  `fiber_g` in unknown nutrients) keeps it null or unknown. If it fails, change
  `CardItem.toSavedIngredientDto` in
  `android/core/data/src/main/kotlin/app/mealsy/data/api/Dtos.kt` to send
  `qtyG` and macros unscaled with `targetQtyG` set, and make
  `MyMealsRepository.save` send `portion`. The server then scales (research
  R4).

**Checkpoint**: The same card edits give the same saved meal on web and
Android (SC-003).

---

## Phase 5: User Story 3 - Update a saved meal from a changed log (Priority: P2)

**Goal**: When a meal that came from a saved meal is logged with changed
ingredients or grams, offer "Update ‘<name>’ in My Meals?". Accepting saves
the changes at 1×. Declining changes nothing.

**Independent Test**: Quickstart scenarios 6–7. Recall a saved meal, change
one item, log it and accept: the next recall shows the change. Decline: no
change. Change only the portion: no offer.

### Backend for User Story 3

- [ ] T033 [US3] Add `saved_meal_id: str | None` to `AgentState` in
  `src/backend/agent/graph.py`.
  - `saved_lookup_node` sets it to `meal.id` on a hit and to `None` on a
    miss. Also return `saved_meal_name` and `saved_meal_updated_at` (ISO
    string) in state for the response.
  - In `log_node`, when `state.get("saved_meal_id")` is set, use the saved
    meal's name as the label and pass `extra_flags={"saved_meal_id": ...}`.
- [ ] T034 [US3] Initialize `"saved_meal_id": None` (and the name and
  updated_at fields) in the graph input dict in
  `src/backend/agent/orchestrator.py` (line ~509).
  - Add `"saved_meal": {"id", "name", "updated_at"} | None` to the paused
    response (line ~538) and to `get_pending_card`'s return (line ~409),
    reading from the graph state.
  - Add the field only when the card is paused.
- [ ] T035 [US3] Add `saved_meal_id: str | None = None` to `LogItemsRequest`
  in `src/backend/api/meals.py`. In `log_items`, when it is set, load the
  `UserMeal`. If it belongs to the caller and isn't deleted, use
  `label=meal.name` and `extra_flags={"saved_meal_id": meal.id}`. Otherwise
  ignore it silently.
- [ ] T036 [P] [US3] Add graph tests in `tests/test_my_meals_graph.py`:
  - `saved_lookup_node` sets and clears `saved_meal_id`;
  - the paused response includes `saved_meal` on a hit and `null` otherwise;
  - `log_node` stamps the flag and label.
- [ ] T037 [P] [US3] Add log-items tests in `tests/test_meal_log_api.py`:
  - `saved_meal_id` for the caller's meal stamps the flag and label;
  - a foreign or unknown id logs normally without the flag.

### Shared diff logic

- [ ] T038 [P] [US3] Add `hasRecipeChanges(snapshot: CardItem[], final:
  {item: CardItem; qtyG: number}[]): boolean` to
  `frontend/src/lib/meal-math.ts`, with tests in
  `frontend/src/lib/meal-math.test.ts`. It is true when:
  - the counts differ;
  - an item at the same position has a different `fdc_id` or `food_name`;
  - or `|qtyG − snapshot.qty_g| ≥ 1`.

  It ignores portion and meal type (FR-012).
- [ ] T039 [P] [US3] Add the same logic as `SavedMealDiff.hasRecipeChanges(...)`
  in `android/core/domain/src/main/kotlin/app/mealsy/domain/SavedMealDiff.kt`,
  with
  `android/core/domain/src/test/kotlin/app/mealsy/domain/SavedMealDiffTest.kt`.
  Use the same cases as T038 so the two stay in step.

### Web for User Story 3

- [ ] T040 [P] [US3] Create
  `frontend/src/components/my-meals/update-saved-meal-offer.tsx`.
  - Props: `savedMeal {id, name, updated_at}` and `items` (the final rows at
    1×).
  - It renders "Update ‘<name>’ in My Meals?" with Update and Not now.
  - Update calls `useUpdateMeal` with `{name, expected_updated_at:
    savedMeal.updated_at, ingredients: items}`.
  - On `meal_changed` it shows "This meal changed since — open My Meals to
    edit." On other errors it shows Retry.
- [ ] T041 [US3] In `frontend/src/components/chat/ConfirmationCard.tsx`:
  - when the card response has `saved_meal`, keep a snapshot of the items as
    first shown;
  - send `saved_meal_id` in the `/meals/log-items` request;
  - after a successful log, if `hasRecipeChanges(snapshot, kept rows)`, render
    `UpdateSavedMealOffer` with the final items as `{...item, target_qty_g:
    qty}` (no portion).
  - Add `saved_meal` to the chat response type in `frontend/src/api/types.ts`.
- [ ] T042 [US3] In `frontend/src/components/chat/MyMealCustomizer.tsx`, after
  a successful customized log, compare against the stored detail with
  `hasRecipeChanges`. If it changed, render `UpdateSavedMealOffer` (FR-011,
  acceptance 4).
- [ ] T043 [P] [US3] Add
  `frontend/src/components/my-meals/update-saved-meal-offer.test.tsx` with
  these cases:
  - the offer shows after a gram change;
  - it is hidden after a portion-only change;
  - Update sends a PUT with `expected_updated_at`;
  - Not now sends nothing.

### Android for User Story 3

- [ ] T044 [P] [US3] In
  `android/core/data/src/main/kotlin/app/mealsy/data/api/Dtos.kt`:
  - add a nullable `savedMeal: SavedMealRefDto? @SerialName("saved_meal")`
    (`id`, `name`, `updatedAt`) to the chat and pending response DTOs;
  - add a nullable `savedMealId` to the log-items request DTO.
- [ ] T045 [US3] In
  `android/app/src/main/java/app/mealsy/android/ui/chat/ChatSessionStore.kt`:
  - keep the snapshot of a card's items when it has `savedMeal`;
  - send `savedMealId` with the log;
  - after a successful log, if `SavedMealDiff.hasRecipeChanges(...)`, emit an
    "Update ‘<name>’ in My Meals?" action toast.
  - Accepting calls `MyMealsRepository.update(...)` at 1× with the snapshot's
    `updatedAt`. Map `Changed` to the "changed since" toast.
  - Add tests in the existing ChatSessionStore test file.
- [ ] T046 [US3] In
  `android/app/src/main/java/app/mealsy/android/ui/mymeals/MyMealsViewModel.kt`,
  after a Customize log from `CustomizeSheet`, compare the kept rows with the
  stored detail using `SavedMealDiff`. If it changed, emit the same update
  offer. Extend
  `android/app/src/test/java/app/mealsy/android/ui/mymeals/MyMealsViewModelTest.kt`.

**Checkpoint**: US1–US3 work on both clients. A changed log can update its
saved meal, but only when the user agrees.

---

## Phase 6: User Story 4 - Add or swap ingredients via the LLM (Priority: P3)

**Goal**: In the editor, the user describes a replacement or an extra
ingredient in free text. A single-food structured LLM call followed by the
USDA lookup (with estimate fallback) returns one card item. The editor stores
it on Save.

**Independent Test**: Quickstart scenarios 8–8d, and the eval gate (SC-007)
at 90% or more.

### Backend for User Story 4

- [X] T047 [P] [US4] Create the prompt file
  `src/backend/config/prompts/replace_ingredient_system.md` (research R8).
  - **Input**: the model gets `mode` (swap/add), `meal`, `replacing` (swap
    only) and `user_text`.
  - **Output**: a JSON object `{"foods": [...]}`, each entry `{food_name,
    qty_g, unit, amount_stated}`.
  - **Naming**: copy the food-naming rules verbatim from
    `src/backend/config/prompts/extraction_system.md`.
  - **Relative phrases**: resolve them against `replacing` ("brown" with
    white rice → brown rice; "skim" with milk → skim milk).
  - **`amount_stated`** is true only for an explicit amount or count.
  - **No amount given**: `qty_g` is a typical single portion.
  - **Text that isn't a food** → `foods: []`.
  - **Several foods named** → one entry each, never merged.
  - **Never** decompose a dish or invent ingredients.
  - Include about 6 short examples, covering swap with a name, swap with a
    relative phrase, swap with an amount, add with an amount, add with no
    amount, and two foods.
- [X] T048 [US4] Add `replace_ingredient_system: str` to `PromptsConfig` in
  `src/backend/config/__init__.py`. The loader then requires the `.md` file
  at import. Check with `python -c "import backend.config"`.
- [X] T049 [US4] Create `src/backend/agent/tools/replace_ingredient.py`.
  - **Schemas**:
    - `ReplacementFood(food_name: str, qty_g: float = Field(gt=0), unit: str,
      amount_stated: bool)` with `extra="forbid"`;
    - `ReplacementResult(foods: list[ReplacementFood])`;
    - `ReplacingIngredient(food_name: str, qty_g: float = Field(gt=0), unit:
      str = "g")`.
  - **LLM**: `_replace_llm = make_llm().with_structured_output(ReplacementResult)`.
  - **Exceptions**: `QuotaExhausted`, `RephraseRequired` and
    `ResolveUnavailable`, each with a docstring.
  - **Entry point**: `async def resolve_ingredient(user_id: str, mode:
    Literal["swap", "add"], text: str, meal_name: str, replacing:
    ReplacingIngredient | None, *, consume_credit: Callable[[str],
    Awaitable[bool]] = consume_llm_credit) -> ResolvedIngredient`. The
    `ResolvedIngredient` Pydantic model holds `item: USDAResult`, `unit`,
    `amount_stated` and `kept_previous_qty`. Steps:
    1. `if not await consume_credit(user_id): raise QuotaExhausted`.
    2. Build one `HumanMessage` with the mode, meal, replacing and user text
       as in research R8.
    3. `await asyncio.wait_for(_replace_llm.ainvoke([...]), timeout=10)`.
       Map `TimeoutError` and the Google API errors to `ResolveUnavailable`,
       and `pydantic.ValidationError` or `OutputParserException` to
       `RephraseRequired`.
    4. `len(result.foods) != 1` raises `RephraseRequired`.
    5. Grams rule: for a swap with no stated amount, use `replacing.qty_g` and
       `replacing.unit`, with `kept_previous_qty=True`. Otherwise use the
       model's `qty_g` and `unit`.
    6. `item = (await usda_lookup_batch([FoodEntity(food_name=...,
       qty_g=final_g, unit=unit)]))[0]`.
  - **Logging**: wrap the call in `logfire.span("resolve_ingredient", ...)`
    recording `mode`, `n_foods`, `amount_stated`, `source`, `estimated` and
    `latency_ms`. Never log the user's text beyond its length.
- [ ] T050 [US4] Add `POST /my-meals/resolve-ingredient` to
  `src/backend/api/my_meals.py` (contract section "NEW: POST
  /my-meals/resolve-ingredient").
  - **Rate limit**: register it **before** the `/{meal_id}` routes, with
    `dependencies=[Depends(user_rate_limiter("resolve_ingredient", limit=20,
    window_s=60))]`.
  - **Request**: `ResolveIngredientRequest` with:
    - `mode: Literal["swap","add"]`;
    - `text: str = Field(min_length=1, max_length=200)`, stripped;
    - `meal_name: str = Field(min_length=1, max_length=120)`;
    - `replacing: ReplacingIngredient | None`;
    - `extra="forbid"`;
    - a model validator: `replacing` is required for swap and must be absent
      for add.
  - **Error mapping**:
    - `QuotaExhausted` → `402 {"detail": {"code": "quota_exhausted",
      "message": UPGRADE_MSG}}`;
    - `RephraseRequired` → `422 {"detail": {"code": "rephrase", "message":
      "Describe one food, e.g. 'brown rice' or '1 tbsp ghee'."}}`;
    - `ResolveUnavailable` → `503 {"detail": {"code":
      "resolve_unavailable"}}`.
  - **Response**: `{item, unit, amount_stated, kept_previous_qty}`.
- [ ] T051 [P] [US4] Create `tests/test_replace_ingredient.py`, patching
  `_replace_llm.ainvoke` and `usda_lookup_batch` and injecting
  `consume_credit`.
  - **Service cases**:
    - one food → item returned;
    - a swap with no stated amount keeps the old grams and unit, even when the
      model's grams differ;
    - a swap with a stated amount uses the model's grams;
    - an add with no amount uses the model's grams;
    - `foods=[]` and two foods → `RephraseRequired`;
    - credit refused → `QuotaExhausted` and the LLM is **not** called;
    - timeout → `ResolveUnavailable`;
    - the lookup returning `estimated=True` passes through.
  - **Route cases** (TestClient): 402, 422 rephrase, 422 when `replacing` is
    missing on a swap, and 503 bodies match the contract.
- [ ] T052 [US4] Run `pytest tests/test_replace_ingredient.py
  tests/test_my_meals_api.py -q`, then `black` and `ruff`. Fix any failures.

### Eval gate for User Story 4 (SC-007)

- [X] T053 [P] [US4] Create `eval/cases/ingredient_replace.jsonl` with at least
  40 cases in the research R10 mix (≥10 swap with a full name, ≥8 swap with a
  relative phrase, ≥6 swap with an amount, ≥8 add with an amount, ≥4 add with
  no amount, ≥4 not in USDA, ≥4 reject).
  - Each line: `{"id", "mode", "meal", "replacing"?, "text",
    "expect_name_any": [...], "expect_qty_g", "expect_reject"?,
    "expect_fdc_ids"?}`.
  - Include Indian dishes that match the user base (dal, roti, paneer, ghee,
    idli). Base gram references on USDA household measures.
- [ ] T054 [US4] Add a `score_ingredient_replace(sem)` scorer to
  `eval/gate.py`.
  - It calls `resolve_ingredient(..., consume_credit=_always_true)` for each
    case, so no user credits are spent.
  - **Pass**: the call doesn't raise, and the normalized `food_name` from the
    model contains any `expect_name_any` entry, and the final `item.qty_g` is
    within ±25% of `expect_qty_g`.
  - **Reject cases** pass on `RephraseRequired`.
  - **Non-gating**: also compute `ingredient_replace_fdc_match` (`fdc_id` in
    `expect_fdc_ids`).
  - Register the scorer in `PCT_CATEGORIES`, `ALL_CATEGORIES` and `scorers`,
    with a `TOLERANCES` entry.
  - Add an `ABSOLUTE_FLOORS = {"ingredient_replace": 90.0}` check that fails
    the gate when the mean over runs is below the floor, regardless of
    baseline.
- [ ] T055 [US4] Run `uv run --env-file .env python eval/gate.py --only
  ingredient_replace --runs 5`.
  - Iterate on `replace_ingredient_system.md` (not the cases) until the mean
    reaches ≥ 90%.
  - Save the passing run to `eval/baseline_ingredient_replace.json` with
    `--out`.
  - Record the score and the fdc-match rate in `research.md` under R10.
  - **Blocks T056–T062.**

### Web for User Story 4

- [ ] T056 [P] [US4] Add `useResolveIngredient` (a `useMutation` that posts to
  `/my-meals/resolve-ingredient`) in `frontend/src/api/hooks.ts`, and
  `ResolveIngredientRequest` / `ResolveIngredientResponse` in
  `frontend/src/api/types.ts`. Match the contract.
- [ ] T057 [US4] Create `frontend/src/components/my-meals/ingredient-input.tsx`.
  - Props: `mode`, `mealName`, `replacing?`, `onResolved(item)`, `onCancel`.
  - It has a text input with a submit button, and shows a spinner while
    pending. Errors appear inline and leave the row unchanged:
    - `rephrase` → the server's message;
    - `quota_exhausted` → the upgrade message with a link to `/upgrade`;
    - `resolve_unavailable` / network → Retry.
- [ ] T058 [US4] Integrate it into
  `frontend/src/components/my-meals/my-meal-editor.tsx` and
  `my-meal-editor-row.tsx`:
  - a "Swap" action per row opens `IngredientInput` in swap mode with that
    row as `replacing`. On resolve, replace `row.item` and set `qtyG =
    item.qty_g`.
  - an "Add ingredient" button opens it in add mode. On resolve, append a row.
  - Disable Save while any resolve is pending.
- [ ] T059 [P] [US4] Add `frontend/src/components/my-meals/ingredient-input.test.tsx`
  covering a successful swap, the rephrase message, the quota message, and
  Retry on 503.

### Android for User Story 4

- [ ] T060 [P] [US4] Add the resolve call to the Android data layer.
  - In `android/core/data/src/main/kotlin/app/mealsy/data/api/Dtos.kt`, add
    `ResolveIngredientRequest` / `ResolveIngredientResponse` DTOs.
  - In `MealsyApi.kt`, add `@POST("my-meals/resolve-ingredient") suspend fun
    resolveIngredient(...)`.
  - In `MyMealsRepository.kt`, add `resolveIngredient(...)` returning a sealed
    `ResolveResult`: `Resolved(item)`, `Rephrase(message)`,
    `QuotaExhausted(message)`, `Unavailable`. Map 422/402/503 by
    `detail.code`.
  - Add cases to `MyMealsRepositoryTest.kt`.
- [ ] T061 [US4] Add `swap(index, item)` (replaces the item and sets `qtyG =
  item.qtyG`) and `add(item)` (appends) to `EditMealState` in
  `android/core/domain/src/main/kotlin/app/mealsy/domain/EditMealState.kt`.
  Add tests to `EditMealStateTest.kt`.
- [ ] T062 [US4] Create
  `android/app/src/main/java/app/mealsy/android/ui/mymeals/IngredientInputSheet.kt`
  and wire it into `EditMealScreen.kt` and `EditMealViewModel.kt`.
  - A per-row "Swap" action and an "Add ingredient" button open the sheet.
  - Results map to `EditMealState.swap/add`.
  - Errors show inline: rephrase, upgrade, Retry.
  - Save is disabled while a resolve is pending.
  - Extend `EditMealViewModelTest.kt`.

**Checkpoint**: All four stories work. The eval gate passes at 90% or more.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [ ] T063 [P] Format and lint everything: `black src/backend eval && ruff
  check src/backend eval --fix`, `cd frontend && npx prettier --write src/ &&
  npx eslint src/ --fix && npm test`, and `cd android && ./gradlew
  ktlintCheck test` (or the project's configured lint task).
- [ ] T064 [P] Update the `.claude/CLAUDE.md` project layout. Add
  `agent/tools/replace_ingredient.py`, `agent/tools/saved_meals.py`,
  `api/my_meals.py`, `config/prompts/` and the
  `eval/cases/ingredient_replace.jsonl` gate command under Commands.
- [ ] T065 Run every manual scenario in `specs/006-edit-saved-meals/quickstart.md`
  (1–10, 8b–8d) on web and the Android emulator. Use a **test account**: the
  local backend points at the prod DB. Check that the `resolve_ingredient`
  Logfire spans have p95 ≤ 3 s.
- [ ] T066 Update `specs/006-edit-saved-meals/checklists/requirements.md`
  notes and the project memory status. Then ask the user before any merge or
  deploy to production.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (T001–T002)** → **Foundational (T003–T007)**, which blocks every
  story.
- **US1 (Phase 3)** depends only on Foundational. It is the MVP.
- **US2 (Phase 4)** depends on T003 and T006. It is independent of US1.
- **US3 (Phase 5)** needs US1's `PUT` (T013), `useUpdateMeal` (T016) and the
  Android `update()` (T022). It also needs T011 (`extra_flags`) and T015
  (`meal-math`).
- **US4 (Phase 6)** needs the US1 editor (T018, T025, T023) and T001
  (`UPGRADE_MSG`). Its backend (T047–T052) and eval (T053–T055) can start
  right after Foundational, in parallel with US1 clients. Its client tasks
  (T056–T062) wait for the eval gate (T055).
- **Polish** comes after the stories you plan to ship.

### Within each story

Tests are written first and should fail. Then backend, then web and Android.
Web and Android can proceed in parallel once the backend is done.

### Parallel opportunities

- **Setup**: T001 ∥ T002.
- **Foundational**: T005 ∥ T006 ∥ T007, after T003 and T004.
- **US1**:
  - tests: T008 ∥ T009 ∥ T010;
  - web: T015 ∥ T016 ∥ T017, then T018 → T019 → T020;
  - Android: T021 ∥ T023, then T022 → T024 → T025 → T026.
  - The web and Android tracks run fully in parallel after T013.
- **US2**: T029 ∥ T031 ∥ T032 after T028/T030.
- **US3**: T036 ∥ T037 ∥ T038 ∥ T039 ∥ T040 ∥ T044.
- **US4**: T047 ∥ T053 at the start. T051 runs after T049. T056 ∥ T060 after
  T055.

## Parallel Example: User Story 1

```text
# After T013 (PUT) lands, run both client tracks at once:
Web:      T015 meal-math.ts | T016 useUpdateMeal | T017 editor-row  →  T018 editor → T019 page → T020 tests
Android:  T021 API+DTO | T023 EditMealState  →  T022 repo → T024 VM → T025 screen → T026 nav → T027 tests
```

## Parallel Example: User Story 4

```text
# Right after Foundational, alongside US1 clients:
T047 prompt  |  T053 eval cases
→ T048 config → T049 service → T050 route → T051 tests → T052
→ T054 gate scorer → T055 run gate (≥ 90%)
→ Web T056–T059  |  Android T060–T062
```

## Implementation Strategy

### MVP first (User Story 1)

1. Phases 1–2 (T001–T007).
2. Phase 3 (T008–T027).
3. **Stop and validate** with quickstart scenarios 1–4, 9 and 10. This alone
   lets users fix saved meals.

### Incremental delivery

1. **+ US2** (T028–T032): new saves stop losing edits. It is small; ship it
   with the MVP if possible.
2. **+ US3** (T033–T046): offer to update a saved meal from a changed log.
3. **+ US4** (T047–T062): LLM add/swap. Clients ship only after the eval gate
   passes.

## Notes

- Every API change is a new route or an additive field. The shipped Android
  build and Telegram keep working at every checkpoint.
- No migrations. If any task seems to need one, stop and revisit research R2
  and R6.
- Usage credits go only through `consume_llm_credit` (FR-014b). Don't add
  quota logic anywhere else.
