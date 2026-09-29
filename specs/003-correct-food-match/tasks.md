---

description: "Task list for Correct a Wrong Food Match (#39)"
---

# Tasks: Correct a Wrong Food Match

**Input**: Design documents from `/specs/003-correct-food-match/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/foods-api.md, contracts/android-picker-ui.md, quickstart.md

**Where the code goes**: every source path below is relative to the **`feat/android-app` worktree at `~/nutrichat-android`** (plan.md, "Source Code"). Backend: `src/backend/`, `tests/`, `eval/`. Android: `android/`.

**Tests**: included. plan.md lists the test files, and the repo's gates (quickstart §5) require pytest, Android unit tests and Roborazzi goldens to pass. Write each story's tests first and confirm they fail.

**Working rules** (from the project's standing instructions):
- Commit after each task or tight group, as the configured git user, with **no Co-Authored-By trailer**.
- **Don't push.** Never touch `production` or `andorid_prod`.
- Run only one Gradle invocation at a time in the worktree.
- Python follows `.claude/CLAUDE.md` (types, Google docstrings, Pydantic at boundaries, async I/O). Compose follows `android/CLAUDE.md` (Design QA checklist).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1 = search for the right food (P1); US2 = compare the suggested alternatives (P2)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: bring in the matching fix this feature depends on.

- [X] T001 Port the matcher work from `001-jev-intent-routing` onto `feat/android-app` in `~/nutrichat-android` (GitHub #51). Cherry-pick, in this order:
  - `87c9c9d` fix(usda): rank generic FDC entries first and keep head-noun rows in the pool
  - `f362722` eval: 176-case food_identity set
  - `7769543` fix(usda): resolve toast to toasted bread (#38)
  Resolve any conflict in `src/backend/agent/tools/usda_match.py` / `src/backend/agent/tools/usda_local.py` / `tests/test_usda_local.py` / `eval/cases/food_identity*.jsonl`, keeping the Android branch's other backend changes. Then run `PYTHONPATH=src uv run python -m pytest tests/ -k usda -q` (must pass) and the offline food-identity eval on `food_identity_expanded.jsonl`. It must reach **≥ 156/177 (88.1%)**, up from 140/177 (79.1%) before the port. Record both numbers in the last commit message.
- [X] T002 Read `src/backend/agent/tools/usda_local.py` (`database_path`, `_fts_candidates`, `_load_row`, `lookup`, `resolve_local`) and record, in a short comment at the top of the new `tests/test_foods_api.py`, how `resolve_local` is called from async code today (is it wrapped in `asyncio.to_thread`?). The new endpoints must follow the same non-blocking pattern (research R8).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: the correction table, the reference-DB read helpers and pending-card resolution. Both stories need these.

**⚠️ CRITICAL**: no user-story work until this phase is complete.

- [X] T003 [P] Add the `FoodCorrection` SQLAlchemy model to `src/backend/db/models.py` (table `food_correction`) with exactly these columns:
  - `id` uuid PK
  - `user_id` uuid not null, indexed
  - `meal_log_id` uuid FK → `meal_log.id` `ON DELETE CASCADE`
  - `original_phrase` text not null
  - `from_fdc_id` int nullable
  - `from_name` text not null
  - `to_fdc_id` int not null
  - `to_name` text not null
  - `method` text, with a check constraint `method IN ('suggestion','search')`
  - `query` text nullable
  - `created_at` timestamptz default `now()`
- [X] T004 Create the Alembic migration `src/backend/db/migrations/versions/20260928_015_food_correction.py` with `revision = "015_food_correction"` and `down_revision = "013"`, creating the table, index and check constraint from T003, with a working `downgrade()`. Add a comment that `andorid_prod` has a different `014`, so a merge revision is needed when the branches join (research R6). Verify with `alembic upgrade head` then `alembic downgrade -1` on a local/throwaway DB only (never prod).
- [X] T005 [P] Add `FoodCorrection` deletion to `DELETE /account` in `src/backend/api/account.py`, next to the existing `MealLog`/`UserMeal` deletes. Extend the existing account-deletion test in `tests/` to assert `food_correction` rows for the user are gone.
- [X] T006 [P] In `src/backend/agent/tools/usda_local.py`, add two typed read helpers with Google docstrings:
  - `search_foods(query: str, limit: int = 10) -> list[LocalFoodHit]`: applies `_normalize_preparation`, uses the FTS5 pool (`pool_size` ≥ `limit`, with substring rescue as in `lookup`), ranks with the existing `_rank_key` (research R2), and returns `fdc_id`, `name`, `data_type`, `kcal_per_100g`, `protein_g_per_100g`.
  - `get_food(fdc_id: int) -> LocalFood | None`: returns per-100 g macros and the decompressed full `nutrients` map from `nutrients_z`.
  Both are sync (SQLite) and fail soft when `is_available()` is false (raise a dedicated `FoodDbUnavailable`).
- [X] T007 [P] Add unit tests to `tests/test_usda_local.py` using the existing fixture DB:
  - `search_foods("toast")` ranks a toasted-bread row above "Shrimp toast"
  - `search_foods` respects `limit` and returns an empty list for gibberish
  - `get_food` returns scaled-ready nutrients for a known `fdc_id` and `None` for an unknown one
  - both raise `FoodDbUnavailable` when the DB path is missing
- [X] T008 Add `resolve_pending(user_id: str, conversation_id: str) -> None` in `src/backend/agent/orchestrator.py`. It marks the paused LangGraph thread `{user_id}:{conversation_id}` resolved, so `get_pending_card` returns nothing for it: update the graph state past the `present` interrupt, or clear the checkpoint, whichever `get_pending_card` (orchestrator.py ~227-258) treats as "not pending". It must be idempotent and a no-op if nothing is paused (research R4).
- [X] T009 Call `resolve_pending` from `POST /meals/log-items` in `src/backend/api/meals.py` after the meal rows commit successfully, when the request carries a `conversation_id`. If `LogItemsRequest` doesn't have a `conversation_id` field yet, add it as optional. Also check in `android/core/data/src/main/kotlin/app/mealsy/data/api/MealsyApi.kt` / `Dtos.kt` whether Android sends it; note the answer for T027.
- [X] T010 [P] Add a regression test in `tests/test_log_items_corrections.py`: a paused conversation shows a card via `GET /meals/pending`; after `POST /meals/log-items` with that `conversation_id`, `GET /meals/pending` returns no card; logging again with the same `client_request_id` stays idempotent.

**Checkpoint**: the table exists, the reference-DB helpers are tested, and logged cards can't come back through pending recovery.

---

## Phase 3: User Story 1 - Search for the right food (Priority: P1) 🎯 MVP

**Goal**: from **Not the right food?**, the user searches foods (pre-filled with their words), sees kcal and protein for the item's grams, picks one, and the item swaps in place in under 1 s, with Undo. The logged meal matches the card, and the correction is recorded.

**Independent Test**: with a pending card containing "Shrimp toast, 28 g" (from "2 eggs and toast"), open the picker, search "white bread toasted", pick a toasted-bread result. The card updates (name, 28 g, new kcal, totals) and the other items are unchanged. Confirm & log: the meal holds the chosen food, a `food_correction` row exists, and `GET /meals/pending` is empty (quickstart §1–§4).

### Tests for User Story 1 ⚠️ (write first, must fail)

- [X] T011 [P] [US1] Contract tests in `tests/test_foods_api.py` for `GET /foods/search` per `contracts/foods-api.md`:
  - auth required (401)
  - `q` "trimmed length 2–100", shorter → 422
  - `qty_g` "> 0, ≤ 5000", default 100
  - `limit` "1–20, default 10"
  - response keys `query`, `normalized_query`, `results[]` with `fdc_id`, `name`, `data_type`, `kcal_per_100g`, `protein_g_per_100g`, `kcal`, `protein_g`, with `kcal == round(kcal_per_100g * qty_g / 100, 1)`
  - empty `results` for no match (200)
  - 503 `{"detail": "food_search_unavailable"}` when the DB is unavailable
- [X] T012 [P] [US1] Contract tests in `tests/test_foods_api.py` for `GET /foods/{fdc_id}`:
  - `qty_g` required, "> 0, ≤ 5000"
  - 200 returns the existing card-item shape scaled to `qty_g`, with `source == "usda_local"`, `estimated == false`, `match_confidence == 1.0`, `candidates == []`, `candidate_details == []`
  - 404 for an unknown `fdc_id`
  - 503 when the DB is unavailable
- [X] T013 [P] [US1] Tests in `tests/test_log_items_corrections.py` for the `correction` item field:
  - valid correction writes exactly one `food_correction` row with `original_phrase` "(1–200)", `from_name` "(1–300)", `method` "`suggestion` | `search`", `query` "(≤ 200)"
  - `to_fdc_id` ≠ item `fdc_id` → 422
  - a replayed `client_request_id` writes no new row
  - items without `correction` behave exactly as before
  - the correction row is deleted when its meal is deleted (FK cascade)
- [X] T014 [P] [US1] Android unit tests in `android/app/src/test/java/app/mealsy/android/ui/chat/FoodPickerViewModelTest.kt` (virtual time):
  - the initial query equals the item's original phrase and results load on open
  - typing triggers a search only after 250 ms and only for trimmed length ≥ 2
  - a newer query cancels an older in-flight one, so a stale result never overwrites a newer one
  - offline state disables search
  - a 503 or network error maps to the "Can't search right now" state
- [X] T015 [P] [US1] Android unit tests in `android/app/src/test/java/app/mealsy/android/ui/chat/ChatViewModelTest.kt` (or a new `CardSwapTest.kt`) for the local swap:
  - selecting a result calls `getFood(fdcId, qtyG)` and replaces only that item, keeping `qtyG`/`targetQtyG` and the meal type, and updating totals
  - Undo restores the previous item exactly and drops the pending correction
  - selecting the current match is a no-op
  - a failed `getFood` leaves the card unchanged
  - Confirm & log sends `correction` with `from_*` = the **originally matched** food even after two swaps

### Implementation for User Story 1 (backend)

- [X] T016 [P] [US1] Pydantic models in the new `src/backend/api/foods.py`:
  - `FoodSearchResult` (fields per data-model.md, `data_type` enum `foundation`|`sr_legacy`|`survey_fndds`, floats ≥ 0)
  - `FoodSearchResponse` (`query`, `normalized_query`, `results`)
  - `class Config: extra = "forbid"` per repo standards
- [X] T017 [US1] Implement `GET /foods/search` in `src/backend/api/foods.py`:
  - auth via `get_current_user_id`
  - Redis `user_rate_limiter` at 60/min/user (fail open like other routes)
  - run `usda_local.search_foods` via `asyncio.to_thread`
  - scale preview `kcal`/`protein_g` to `qty_g`
  - map `FoodDbUnavailable` → 503 `food_search_unavailable`
  - log query length, result count and latency (no raw query text at INFO level)
- [X] T018 [US1] Implement `GET /foods/{fdc_id}` in `src/backend/api/foods.py`:
  - auth, rate limit 30/min/user
  - `usda_local.get_food` via `asyncio.to_thread`
  - build the response by reusing the existing card-item / `USDAResult` construction and scaling in `src/backend/agent/tools/usda.py` (don't duplicate the scaling math); set `source="usda_local"`, `estimated=False`, `match_confidence=1.0`, empty candidates
  - 404 when `None`, 503 when unavailable
- [X] T019 [US1] Register the foods router in `src/backend/main.py` with the same prefix and dependency conventions as the other routers.
- [X] T020 [US1] Extend `POST /meals/log-items` in `src/backend/api/meals.py`:
  - add an optional `correction: CorrectionIn | None` to `LogItemIn`, with the field rules from data-model.md
  - validate `correction.to_fdc_id == item.fdc_id` (422 otherwise)
  - insert one `FoodCorrection` per corrected item, in the same transaction as its `MealLog` row, using that row's id for `meal_log_id` and the item's final `food_name` as `to_name`
  - skip inserts on an idempotent replay
  - update the `LogItemsRequest` docstring (meals.py ~165-167), which currently says swaps must go through chat
- [X] T021 [US1] If the item's original phrase isn't already on card items (compare `food_name` from extraction with the matched description in `src/backend/agent/tools/usda.py` / `src/backend/agent/orchestrator.py` ~213), add an optional `input_phrase: str | None` to the card item output, set from the extracted entity name (research R9). Assert it in an existing card-shape test in `tests/`.
- [X] T022a [US1] Add regression cases from #51 to `eval/cases/food_identity_expanded.jsonl` (and unit cases in `tests/test_usda_local.py`) for both automatic matching and search: `rice` (not "Rice crackers"), `toast` (not "Shrimp toast"), `blueberries` (not "Blueberry juice"), `chicken breast` (not "Chicken breast roll"), `water` (not "Tonic water"). Mark any still failing after T001 as known misses (`xfail` with a reason), so they don't block the gate and aren't forgotten.
- [X] T022 [US1] Add a search mode to the offline food-identity eval (`eval/` harness used for `eval/cases/food_identity*.jsonl`): for each case, call `usda_local.search_foods(<the case's expected food phrase, not the whole meal sentence>, limit=5)` and report the top-5 hit rate. Document the command in `quickstart.md` §1 and record the baseline number (SC-004 target ≥ 90%).

### Implementation for User Story 1 (Android)

- [X] T023 [P] [US1] DTOs in `android/core/data/src/main/kotlin/app/mealsy/data/api/Dtos.kt`:
  - `FoodSearchResponseDto` / `FoodSearchResultDto`
  - `CorrectionDto` (`original_phrase`, `from_fdc_id`, `from_name`, `to_fdc_id`, `method` "suggestion"|"search", `query`)
  - optional `correction` on the log-items item DTO
  - optional `input_phrase` on `ItemDto`
  All are nullable/defaulted so older servers still parse.
- [X] T024 [US1] Retrofit calls in `android/core/data/src/main/kotlin/app/mealsy/data/api/MealsyApi.kt`: `@GET("foods/search") searchFoods(q, qtyG, limit)` and `@GET("foods/{fdcId}") getFood(fdcId, qtyG): ItemDto`.
- [X] T025 [US1] New `FoodRepository` in `android/core/data/src/main/kotlin/app/mealsy/data/repo/FoodRepository.kt` (Hilt `@Singleton`, following `MyMealsRepository`). It exposes `search(q, qtyG): FoodSearchOutcome`, a sealed type `Results` / `Empty` / `Unavailable` / `Offline` / `Error`, and `getFood(fdcId, qtyG): CardItem`, mapping DTOs to domain. Add `FoodRepositoryTest` in `android/core/data/src/test/kotlin/app/mealsy/data/repo/` covering 200/empty/503/IOException.
- [X] T026 [US1] Domain additions in `android/core/domain/src/main/kotlin/app/mealsy/domain/CardItem.kt`: `inputPhrase: String?` and `pendingCorrection: FoodCorrection?` (a domain type with `originalPhrase`, `fromFdcId`, `fromName`, `toFdcId`, `method`, `query`). Keep `:core:domain:test` green.
- [X] T027 [US1] Local swap in `android/app/src/main/java/app/mealsy/android/ui/chat/CardEditor.kt` and `ChatSessionStore.kt`, following the existing local `editQty`/`removeItem`/`undoRemove` pattern (ChatSessionStore ~393-455):
  - `swapItem(index, newItem: CardItem, method, query)` keeps the old item's `qtyG`/`targetQtyG`, sets `pendingCorrection` with `from_*` = the **first** matched food (preserved across repeat swaps), and recomputes totals
  - `undoSwap(index)` restores the previous item
  - the existing `onSwapCandidate` chat path stays only for "Describe it differently"
  - if T009 found that Android doesn't send `conversation_id` to log-items, add it in the log-items request built by `ChatRepository.kt`
  - send `correction` for swapped items on Confirm & log
- [X] T028 [US1] New `FoodPickerViewModel` in `android/app/src/main/java/app/mealsy/android/ui/chat/FoodPickerViewModel.kt` (Hilt, assisted by the item's index / phrase / qtyG / current fdcId):
  - query `MutableStateFlow` initialised to the item's `inputPhrase ?: foodName`
  - `debounce(250)` → `distinctUntilChanged` → `filter { trim().length >= 2 }` → `mapLatest { repo.search(...) }`
  - offline via `android/app/src/main/java/app/mealsy/android/util/ConnectivityObserver.kt`
  - `select(fdcId, method)` calls `repo.getFood`, then emits a `SwapReady(item)` or `SwapFailed` event
  (makes T014 pass)
- [X] T029 [US1] Redesign `android/core/ui/src/main/java/app/mealsy/android/design/components/CandidatePickerSheetContent.kt` to match `contracts/android-picker-ui.md`:
  - title "Pick the right food" and subtitle "Currently: {matched name}"
  - `PillInput` search field with the TalkBack label "Search foods", clear button, IME action Search, disabled with "You're offline"
  - a Results section with row skeletons while loading, "No foods found for '{q}'", and "Can't search right now"
  - result rows: one merged semantics node reading "{name}, {kcal} kilocalories, {protein} grams protein", role Button, min height 48 dp, "{kcal} kcal · {protein} g protein" formatted with the existing number formatting (thousands separator)
  - keep the "Describe it differently" and "None of these — remove it" rows
  - a polite live-region announcement of the result count
  - the sheet opens fully expanded (`skipPartiallyExpanded = true`, as in #48)
  Keep the composable stateless (state + callbacks in, events out). Add strings to `android/app/src/main/res/values/strings.xml` (or the core/ui strings file used by the current sheet).
- [X] T030 [US1] Wire the picker in `android/app/src/main/java/app/mealsy/android/ui/chat/ConfirmCardView.kt` (and `ConfirmCardCallbacks.kt`):
  - opening "Not the right food?" creates the `FoodPickerViewModel` for that item
  - `SwapReady` closes the sheet, calls `swapItem`, and shows InkToast "Swapped to {name}" with **Undo** → `undoSwap`, plus the confirm haptic from the core/ui haptics helper
  - `SwapFailed` keeps the sheet open with the inline "Couldn't switch foods. Try again."
  - tapping the current match closes the sheet with no toast
  - the picker isn't reachable on Logged/Discarded cards
- [X] T031 [US1] Roborazzi goldens for the new sheet: loaded results, loading skeleton, empty, unavailable and offline states, in light and dark, plus a 2.0 font-scale variant of loaded results. Put them in the existing golden test for the confirm card / candidate sheet under `android/app/src/test/java/app/mealsy/android/ui/chat/` (or core/ui's component golden tests). Record them, inspect the PNGs, and re-record only the confirm-card goldens that changed intentionally.

**Checkpoint**: US1 works end to end. Search, swap, Undo, log with correction, and no stale pending card (quickstart §1–§4 steps 1, 3–8).

---

## Phase 4: User Story 2 - Compare the suggested alternatives (Priority: P2)

**Goal**: the picker's suggestions show kcal and protein for the item's grams, the current match is marked, and picking a suggestion swaps instantly through the same local path as US1.

**Independent Test**: open the picker on any item with alternatives. Each suggestion shows nutrition for the current grams and the current match is checked. Tap an alternative and the card updates in < 1 s without the "coach is typing" indicator. Logging records `method = suggestion` (quickstart §4 steps 2 and 4).

### Tests for User Story 2 ⚠️ (write first, must fail)

- [X] T032 [P] [US2] Backend test (extend an existing card-shape test in `tests/`, e.g. the orchestrator/usda card tests): card items carry `candidate_details`, a list of `{fdc_id, name, data_type, kcal_per_100g, protein_g_per_100g}` whose names equal `candidates` "in the same order". It is `[]` for estimated items and for the live-FDC path, and `candidates: list[str]` is unchanged.
- [X] T033 [P] [US2] Android tests: `ItemDto` parses `candidate_details` (and tolerates its absence) in `android/core/data/src/test/...`. `FoodPickerViewModel` exposes suggestions with preview kcal = `kcal_per_100g * qtyG / 100` and marks the current match. Selecting a suggestion records `method = suggestion`.

### Implementation for User Story 2

- [X] T034 [US2] Backend: populate `candidate_details` in `src/backend/agent/tools/usda.py` (`USDAResult` gains `candidate_details: list[CandidateDetail] = []`) from the rows already in the local FTS pool in `usda_local.lookup`/`resolve_local` (no extra queries), in the same order as `candidates`. Leave it empty on the live-FDC and estimate paths. Make sure `src/backend/agent/orchestrator.py` (~213) passes it through to the card JSON.
- [X] T035 [P] [US2] Android: add a `CandidateDetailDto` and optional `candidate_details` to `ItemDto` in `android/core/data/src/main/kotlin/app/mealsy/data/api/Dtos.kt`, and map it to `CardItem.candidateDetails: List<CandidateDetail>` in `android/core/domain/src/main/kotlin/app/mealsy/domain/CardItem.kt`. Keep the existing name-string degradation (Dtos.kt ~136-150) working.
- [X] T036 [US2] Android: in `FoodPickerViewModel.kt`, expose `suggestions` (from `candidateDetails`, preview-scaled to the item's grams, current match flagged). Render a Suggestions section above Results in `CandidatePickerSheetContent.kt`, using the same row composable as results, with a check and ", selected" semantics on the current match. Selecting a suggestion goes through `select(fdcId, method = "suggestion")` → `getFood` → the same local swap as US1. Remove the old chat-based `onSwapCandidate` wiring for suggestion taps in `ConfirmCardView.kt`.
- [X] T037 [US2] Update or add the Roborazzi golden for the sheet with suggestions plus results (light/dark), and re-verify the US1 goldens.

**Checkpoint**: US1 and US2 both work on their own.

---

## Phase 5: Polish & Cross-Cutting Concerns

- [X] T038 [P] Run the full backend suite in `~/nutrichat-android`: `PYTHONPATH=src uv run python -m pytest tests/ -q`. Only the pre-existing `test_chat_history_isolation` 401 failure may remain.
- [X] T039 Run the full Android gates in `android/`: `./gradlew ktlintCheck testDebugUnitTest :core:domain:test verifyRoborazziDebug :app:lintDebug` and then `:app:assembleDebug`. Don't use plain `./gradlew test`; its release-variant Robolectric tests fail on unmodified HEAD.
- [X] T040 Run the food-identity search eval from T022 and confirm the top-5 hit rate is ≥ 90% (SC-004). If it's lower, list the misses in the commit message and stop for review. Don't retune the ranker (2026-09-24 decision).
- [X] T041 Walk through `specs/003-correct-food-match/quickstart.md` §1–§4 on the emulator against the local backend (ask the user before relaunching the emulator; this host gets memory-reaped). Record SC-002/SC-003 timings from okhttp logs.
- [X] T042 [P] Check the Design QA checklist in `android/CLAUDE.md` for the new sheet: one olive element, pastels only in icon circles/tags, Geist + tabular numerals for kcal/protein, 48 dp targets, semantics on every row. Fix any deviations in `CandidatePickerSheetContent.kt`.
- [X] T043 [P] Update the GitHub issue: comment on #39 (`gh issue comment 39 --repo AswinManohar/nutrichat`) with the commits and what's out of scope (remember-corrections and the web picker are follow-ups). Ask the user before closing it.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (T001–T002)**: start immediately. T001 blocks T006/T007 (search needs `_normalize_preparation`).
- **Foundational (T003–T010)**: T003 → T004 → T005; T006 → T007; T008 → T009 → T010. Blocks both stories.
- **US1 (T011–T031)**: after Foundational. Backend tests T011–T013 before T016–T022. Android tests T014–T015 before T023–T030. Android T024–T025 need the backend contract (T017–T018) at least stubbed. T029 before T030 → T031.
- **US2 (T032–T037)**: after Foundational. Its swap path reuses US1's T025/T027/T028, so start it after those are merged, but it can be demoed on its own.
- **Polish (T038–T043)**: after the stories you want to ship.

### User Story Dependencies

- **US1 (P1)**: depends only on Foundational.
- **US2 (P2)**: depends on Foundational plus US1's swap plumbing (T025, T027, T028). Its own value (suggestions with nutrition, instant swap) can be tested without the search field being used.

### Parallel Opportunities

- T003, T005 (after T004), T006 are different files.
- T011, T012, T013, T014, T015 are all test files.
- T016 alongside T023 (backend models vs Android DTOs).
- T032, T033; T035 alongside T034.
- T038, T042, T043.
- ⚠️ **Gradle constraint**: Android tasks can be *written* in parallel, but only one Gradle run may execute at a time in the worktree.

---

## Parallel Example: User Story 1

```bash
# Tests first, together:
Task: "Contract tests for GET /foods/search in tests/test_foods_api.py"                     # T011
Task: "Contract tests for GET /foods/{fdc_id} in tests/test_foods_api.py"                   # T012 (same file: write sequentially if one agent)
Task: "log-items correction tests in tests/test_log_items_corrections.py"                   # T013
Task: "FoodPickerViewModelTest in android/app/src/test/.../FoodPickerViewModelTest.kt"      # T014

# Then backend models and Android DTOs side by side:
Task: "Pydantic models in src/backend/api/foods.py"                                         # T016
Task: "DTOs in android/core/data/.../api/Dtos.kt"                                           # T023
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 (cherry-pick #38) → Phase 2 (table, helpers, pending resolution).
2. Phase 3 (US1): search, local swap, Undo, correction on log.
3. **Stop and validate**: quickstart §1–§4, SC-002/SC-003 timings, SC-004 eval.
4. This alone closes the core complaint in #39.

### Incremental Delivery

1. Foundation → US1 (MVP) → validate → commit.
2. US2 (suggestions with nutrition plus instant suggestion swaps) → validate → commit.
3. Polish → hand back to the user for emulator sign-off, then decide whether to push or close #39.

---

## Notes

- Constraints from data-model.md are quoted in the tasks (T003, T011, T012, T013, T023). Don't loosen them at implementation time.
- `candidates: list[str]` must stay unchanged: the web app (FR-010) and older Android builds depend on it.
- `food_correction` is write-only in this feature (FR-012). Don't read it for matching.
