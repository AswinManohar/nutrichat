---

description: "Task list for 008 fixed micronutrients"
---

# Tasks: Fixed Micronutrient Set with Estimated Fallback

**Input**: Design documents from `specs/008-fixed-micronutrients/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md)

**Tests**: These are included. The spec makes passing test suites a success
criterion (SC-010), and every user story defines an Independent Test.

**Organization**: Tasks are grouped by user story. Paths are relative to the
repo root, and backend code lives in `src/backend/`.

**Ground rules for every task** (from plan.md's Constitution Check):
- Async I/O only, with SQLite reads via `asyncio.to_thread`.
- Pydantic `extra="forbid"` at boundaries.
- Google docstrings, 88 columns, `black` and `ruff`.
- **Never store a value twice (FR-018)**.
- Unknown is never 0.
- Never trust nutrition sent by the client.
- Commit after each task as the user, push the feature branch, and never
  commit to `production` (memory).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on unfinished tasks)
- **[Story]**: US1, US2 or US3 (spec.md user stories)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the new package and test helpers.

- [X] T001 Create the `src/backend/nutrients/` package with `__init__.py`, `catalog.py`, `resolve.py` and `daily.py`. Each file gets a Google-style module docstring stating its single responsibility (catalogue lookups; per-item resolve and meal summary; per-day totals) and `from __future__ import annotations`.
- [X] T002 [P] Add test factories in `tests/factories_micros.py`. They should provide `make_usda_result(food_name, qty_g, fdc_id, micros={key: (amount|None, source)})` and `make_meal_micros({key: (total, est, known)})`, which later tests reuse.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The catalogue, the new column and the in-memory value type. Every story depends on these.

**⚠️ CRITICAL**: No user-story work can begin until this phase is complete.

- [X] T003 Write `src/backend/config/nutrients.yaml` with the 5 groups (`carbs` "Carbohydrate detail", `fat` "Fat detail", `other` "Other", `vitamins` "Vitamins", `minerals` "Minerals") and the 48 entries from spec FR-001.
  - **Fields per entry**: key, name, unit, group, order, direction, daily_value, usda_names, usda_only, max_per_100g (leave null for now; T014 fills it), column, derived, upper_limit, status (`active`).
  - **Keys** are snake_case with no unit suffix (research R2): `fiber, total_sugars, added_sugars, saturated_fat, monounsaturated_fat, polyunsaturated_fat, trans_fat, alcohol, cholesterol, salt, sodium, water, vitamin_a, thiamin, riboflavin, niacin, pantothenic_acid, vitamin_b6, biotin, folate, vitamin_b12, vitamin_c, vitamin_d, vitamin_e, vitamin_k, arsenic, boron, calcium, chloride, choline, chromium, cobalt, copper, fluoride, iodine, iron, magnesium, manganese, molybdenum, phosphorus, potassium, rubidium, selenium, silicon, sulfur, tin, vanadium, zinc`.
  - **Units**: use the ones in spec FR-001. µg is written `mcg`.
  - **FDA daily values** (`daily_value`): added_sugars 50, saturated_fat 20, cholesterol 300, sodium 2300, fiber 28, vitamin_d 20, calcium 1300, iron 18, potassium 4700, vitamin_a 900, vitamin_c 90, vitamin_e 15, vitamin_k 120, thiamin 1.2, riboflavin 1.3, niacin 16, vitamin_b6 1.7, folate 400, vitamin_b12 2.4, biotin 30, pantothenic_acid 5, phosphorus 1250, iodine 150, magnesium 420, zinc 11, selenium 55, copper 0.9, manganese 2.3, chromium 35, molybdenum 45, chloride 2300, choline 550. Every other entry has `daily_value: null`.
  - **direction `limit`**: saturated_fat, trans_fat, cholesterol, sodium, salt, total_sugars, added_sugars, alcohol.
  - **direction `none`**: monounsaturated_fat, polyunsaturated_fat, arsenic, boron, cobalt, rubidium, silicon, sulfur, tin, vanadium.
  - **direction `target`**: all the rest.
  - **usda_names**: per research R10 (total_sugars = ["Total Sugars", "Sugars, Total"]; folate = ["Folate, DFE", "Folate, total"] in priority order; vitamin_k = ["Vitamin K (phylloquinone)"]; fluoride = ["Fluoride, F"]; alcohol = ["Alcohol, ethyl"]; choline = ["Choline, total"]; minerals use the "<Name>, <Symbol>" form, for example "Iron, Fe").
  - **No USDA name**: added_sugars, arsenic, chloride, chromium, rubidium, silicon, tin, vanadium, salt get `usda_names: []`.
  - **usda_only: true** for exactly arsenic, boron, cobalt, rubidium, silicon, sulfur, tin, vanadium.
  - `fiber` gets `column: fiber_g`. `salt` gets `derived: {from: sodium, factor: 0.0025}`.
  - **upper_limit**: copy the 8 entries verbatim from the `upper_limits:` block of `src/backend/config/tunables.yaml` (sodium, total_sugars, saturated_fat, vitamin_a, vitamin_d, iron, zinc, niacin) as `{value: <ul>, source, url}`.
- [X] T004 Add Pydantic models `NutrientGroup`, `NutrientDef`, `UpperLimit`, `Derived` and `NutrientCatalog`, plus a cached `get_catalog()` loader, to `src/backend/config/__init__.py`. Use `extra="forbid"` and the same loading pattern as `get_tunables()`. Validators must enforce:
  - keys are unique;
  - "At most one of `column` and `derived` is set";
  - an entry with `derived` has no `usda_names` and `usda_only = false`;
  - "`usda_only = true` applies exactly to arsenic, boron, cobalt, rubidium, silicon, sulfur, tin and vanadium";
  - `unit` is one of `g`, `mg` or `mcg`; `group` is one of the 5 group ids; `direction` is one of `limit`, `target` or `none`; `status` is one of `active` or `retired`.
- [X] T005 Implement `src/backend/nutrients/catalog.py`: `key_for_usda_name(name) -> str | None` (alias map that honours the priority order), `stored_keys()` (active keys with neither `column` nor `derived`), `estimable_keys()` (stored keys minus usda_only), `usda_only_keys()`, `resolve_key(name_or_key) -> str | None` (accepts a catalogue key or any USDA alias, used by coaching), and `public_view()` (drops `usda_names`, `max_per_100g` and `column` for the API).
- [X] T006 [P] Write `tests/test_nutrient_catalog.py`. Check: 48 entries; 5 groups; each validator rejects a bad fixture; both sugar spellings map to `total_sugars`; folate prefers DFE; `stored_keys()` excludes fiber and salt; `estimable_keys()` has 38 entries (48 − fiber − salt − 8 USDA-only); `public_view()` hides the server-only fields.
- [X] T007 Create migration `src/backend/db/migrations/versions/20261003_018_meal_micros.py` with `revision = "018_meal_micros"` and `down_revision = "017_rls_new_tables"`. It adds `meal_log.micros JSONB NOT NULL DEFAULT '{}'::jsonb`, and the downgrade drops the column. There is no backfill (FR-012).
- [X] T008 Add `micros: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict)` to `MealLog` in `src/backend/db/models.py`, with a comment pointing to data-model.md §3.
- [X] T009 In `src/backend/agent/tools/usda.py`, add `class MicroValue(BaseModel)` with `amount: float | None` and `source: Literal["usda", "estimated", "unknown"]` (`extra="forbid"`). Add `micros: dict[str, MicroValue] = {}` to `USDAResult`. Keep the existing `nutrients` field for now; T037 removes it.

**Checkpoint**: The catalogue loads and validates, the migration applies (`alembic upgrade head`), and the existing suite still passes (`pytest`).

---

## Phase 3: User Story 1 - Every logged food has the tracked micronutrients (Priority: P1) 🎯 MVP

**Goal**: Each logged meal stores `meal_log.micros` for every tracked nutrient. Values come from USDA first, then estimates, with USDA-only nutrients left unknown, and the server computes them for every logging path. The confirmation card is unchanged.

**Independent Test**: Log a meal with only a food that has no USDA match (for example "mom's rasam"). `meal_log.micros` has every estimable key with `est == total` and no USDA-only key. Log "grilled chicken breast" and `vitamin_c` is `{total: 0, est: 0}`, because USDA zeros are kept. See quickstart scenarios 2–5 and 7–10.

### Tests for User Story 1 ⚠️ (write first, ensure they fail)

- [X] T010 [P] [US1] Write `tests/test_resolve_micros.py` covering:
  - a USDA value wins, including 0;
  - a gap is filled from the pre-computed estimate and marked `estimated`;
  - a USDA-only key with no USDA value is `unknown`, never estimated;
  - an estimate above `max_per_100g` is dropped and becomes `unknown`;
  - "added_sugars.total is at most total_sugars.total";
  - amounts scale by `qty_g/100`;
  - the `Sugars, Total` alias resolves to total_sugars.
  
  Also cover `summarise()`:
  - `total` is the sum of known values, `0 ≤ est ≤ total`, and `1 ≤ known ≤ items`;
  - a key is absent when no item is known;
  - `fiber` and `salt` never appear.
- [X] T011 [P] [US1] Write `tests/test_estimate_micros.py` with a stubbed pydantic-ai agent. Check that:
  - the estimate output with `micros` (per 100 g) produces `USDAResult.micros` scaled to qty;
  - a cache hit on `food_source` returns the same micros with no agent call;
  - an agent exception still returns the macro miss path, with micros all `unknown` (FR-008);
  - the agent is called **once** per food (FR-009).
- [X] T012 [P] [US1] Write `tests/test_meal_micros_write.py` (real test DB). Check that:
  - `log_meal` writes `micros` per data-model §3;
  - client-sent `micros` and `nutrients` on `POST /meals/log-items` are ignored (the server values win);
  - "Log again" parity: logging a meal's stored items again at portion 1 gives an identical `micros`;
  - logging a saved meal through `POST /my-meals/{id}/log` produces `micros`;
  - an estimate failure still logs the meal with `micros == {}`.

### Implementation for User Story 1

- [X] T013 [US1] In `src/backend/scripts/build_usda_db.py`, bump `_SCHEMA_VERSION` to 3 and `PRAGMA user_version = 3`. Add `CREATE TABLE food_micro_estimate (fdc_id INTEGER NOT NULL, key TEXT NOT NULL, per_100g REAL NOT NULL, PRIMARY KEY (fdc_id, key))`. In `src/backend/agent/tools/usda_local.py`, accept schema v2 or v3: if the table is missing, there are simply no gap estimates.
- [X] T014 [US1] Create `src/backend/scripts/compute_micro_caps.py`. For each stored key with at least 30% USDA coverage in `usda_fdc.sqlite3`, compute `max_per_100g = 1.5 × p99.9` of the per-100 g values. For the sparse or USDA-less keys (added_sugars, chloride, chromium, iodine, molybdenum, biotin, fluoride), print the hand-set caps from research R8 for review. Write the results into `max_per_100g` in `src/backend/config/nutrients.yaml`. Add a CLI flag `--write` (the default is print only).
- [X] T015 [US1] *(Uses concurrent standard calls instead of the batch API. Dry run: 13,694 foods, 149,399 pairs, ≈ $1.75. Full run still awaits approval, T050.)* Create `src/backend/scripts/build_micro_estimates.py`. For every food in the bundled SQLite, it sends Gemini 2.5 Flash-Lite (batch API) the food description, the USDA nutrients that food already has, and the **estimable** keys it is missing. The model returns per-100 g values. Values over `max_per_100g`, and added_sugars greater than total sugars, are dropped. The rest are inserted into `food_micro_estimate`. Flags:
  - `--dry-run`: print the food count, missing-key count, token and cost estimate, and make no calls;
  - `--limit N`;
  - `--benchmark N`: pick N foods that have USDA values, hide them, estimate them, and report the share within ±50% (SC-004 needs ≥70%).
  
  Log the rejection rate for each key. **Do not run the full build without explicit user approval.**
- [X] T016 [US1] *(Done via T013 + T017: `usda_local.micro_inputs`/`LocalMatch.micro_estimates_per_100g` return raw rows; the alias mapping lives in `resolve.per_100g_from_usda` to avoid an import cycle.)* In `src/backend/agent/tools/usda_local.py`, add `load_micros_per_100g(conn, fdc_id) -> dict[str, tuple[float, str]]`. It maps the food's USDA nutrients through `catalog.key_for_usda_name` (first alias wins, and a USDA 0 is kept as `usda`), then merges in `food_micro_estimate` rows for keys still missing as `estimated`, skipping `usda_only_keys()`. Add `micros_per_100g` to `LocalMatch` and fill it in `lookup()`.
- [X] T017 [US1] Implement `src/backend/nutrients/resolve.py`:
  - `build_item_micros(per_100g: dict[str, tuple[float, str]], qty_g: float) -> dict[str, MicroValue]`: covers every `stored_keys()` entry, missing means `unknown`, applies the caps and the rule "added_sugars ≤ total_sugars".
  - `async resolve_micros(fdc_id: int, food_name: str, qty_g: float) -> dict[str, MicroValue]`: `fdc_id > 0` uses the local SQLite via `asyncio.to_thread`; `-1` uses the estimate cache (`food_source`, `source_db='LLM_ESTIMATE'`, normalised name); a miss gives all unknown, with no AI call at log time.
  - `summarise(items: list[dict[str, MicroValue]]) -> dict[str, dict]`: produces `{key: {"total", "est", "known"}}`, omits keys with no known value, and rounds to 4 decimals.
- [X] T018 [US1] In `src/backend/agent/tools/usda.py`:
  - add a nested `EstimatedMicros` model to `NutritionEstimate`, with one optional `float | None` field (ge 0) per `estimable_keys()` entry except total_sugars and saturated_fat (those come from `sugar_g` and `sat_fat_g`), as per-100 g values, using `extra="forbid"`;
  - store the per-100 g micros under a `"micros"` key inside the existing `food_source.nutrients` JSONB on cache write, and read them on a cache hit;
  - populate `USDAResult.micros` in `estimate_nutrition_llm` and `_estimate_result` using `build_item_micros` (source `estimated`);
  - keep it to **one** agent call.
- [X] T019 [P] [US1] Update `src/backend/config/prompts/nutrition_estimate_system.md`. Macros stay totals for the given grams. Add a `micros` object of **per-100 g** values for the listed keys, with units from the catalogue. The model should return null when it truly can't estimate, and never invent USDA-only trace elements.
- [X] T020 [US1] In `src/backend/agent/tools/usda.py`, have `_result_from_local` set `micros` from `match.micros_per_100g` via `build_item_micros`. The FDC-API rollback path (`_parse_fdc_response` and `_result_from_cache`) maps its raw nutrients through `catalog.key_for_usda_name`, and its gaps stay `unknown` (research R6).
- [X] T021 [US1] In `src/backend/agent/tools/meals.py` (`log_meal` / `_insert_meal_log`):
  - call `resolve_micros` for every item concurrently (`asyncio.gather`), ignoring any `micros` already on the result;
  - compute `summarise(...)` and insert it into the new `micros` column;
  - add Logfire span attributes `micros.usda`, `micros.estimated`, `micros.unknown` and `micros.rejected` (FR-011).
- [X] T022 [US1] In `src/backend/api/meals.py` (`log_items`) and `src/backend/api/my_meals.py` (`_scaled_result` and the `/{meal_id}/log` route), make sure no client-supplied `micros` or `nutrients` reaches `meal_log.micros`. Everything flows through `log_meal`'s server-side resolve (contracts/meal-micros.md §2). Update the docstrings to say so.
- [X] T023 [US1] In `src/backend/api/my_meals.py`:
  - `_build_ingredients` stores per-ingredient `micros` (`{key: {amount, source}}`) produced server-side by `resolve_micros`, and stores **no** raw `nutrients`;
  - `MyMealDetail` gains `micros_totals`, **computed on read** from the ingredients and never stored on `user_meal` (FR-014a);
  - legacy ingredients without `micros` are resolved on read from `fdc_id` or the name.
- [X] T024 [US1] In `src/backend/agent/tools/saved_meals.py`, make `saved_meal_to_results` carry ingredient `micros` into `USDAResult.micros`, falling back to `resolve_micros` for legacy ingredients. The `_MACROS` behaviour is unchanged.
- [X] T025 [US1] *(Deferred to land with T037 so the Check-up, which still reads card `nutrients` until US2, never goes blind on this branch.)* In `src/backend/agent/orchestrator.py`, the card item payload stops sending `nutrients` and does **not** add `micros` (FR-014, contracts/meal-micros.md §1). Update the "Full breakdown so Save to My Meals preserves micros" comment, because saved meals now resolve on the server (T023).

**Checkpoint**: US1 is complete. New meals store `micros`, and the card is unchanged. The Check-up and Mindful panel still read the old per-item `nutrients`, which remain stored until T037. **Do not release US1 without US2** (FR-019).

---

## Phase 4: User Story 2 - Totals use one consistent nutrient list (Priority: P1)

**Goal**: The catalogue is the only nutrient definition. Every reader (Check-up, Mindful panel, coaching, the new daily-totals endpoint) uses `meal_log.micros` and gives the same numbers. Old per-item storage is then removed.

**Independent Test**: Seed a day with one item whose source uses `Sugars, Total`, one using `Total Sugars`, and one estimated item. `GET /nutrients/daily` sugar equals the sum of all three, and the Check-up and coaching report the same value (SC-005, SC-006). Quickstart scenarios 1, 6, 11–14.

### Tests for User Story 2 ⚠️

- [X] T026 [P] [US2] Write `tests/test_daily_micros.py` covering contracts/daily-totals.md:
  - every day in the range is returned, and a day with no meals has `logged:false`;
  - salt is 0.0025 × sodium;
  - fiber comes from the `fiber_g` column with `est 0`;
  - soft-deleted meals are excluded;
  - the nutrition-day boundary is respected;
  - `to − from > 364` gives 422, and an unknown key gives 422;
  - `meals=true` returns per-meal contributions;
  - a benchmark seeds 90 days × 4 meals and asserts p95 under 1 s (SC-008).
- [X] T027 [P] [US2] Write `tests/test_meta_nutrients.py` covering contracts/nutrients-catalogue.md: public access, the `Cache-Control` header, 48 entries, 5 groups, and no `usda_names`, `max_per_100g` or `column` in the payload.
- [X] T028 [P] [US2] Write `tests/test_reader_consistency.py` (SC-006). For one seeded week, the Check-up aggregates, the Mindful-panel day totals, the coaching micronutrient data ("how much iron this week") and `get_daily_micros` all agree for every key they report.

### Implementation for User Story 2

- [X] T029 [US2] Implement `get_daily_micros(user_id, date_from, date_to, keys, include_meals=False)` in `src/backend/nutrients/daily.py` as **one** SQL pass:
  - `jsonb_each(meal_log.micros)` grouped by `NUTRITION_DATE_SQL`, with `jsonb_array_length(entities)` for `items` and `deleted_at IS NULL`;
  - fiber added from the `fiber_g` column, and salt computed from sodium;
  - every day in the range filled in, with `logged=false` for empty days;
  - Pydantic response models `DailyMicros` and `DailyMicrosResponse` per data-model §5.
- [X] T030 [US2] Create `src/backend/api/nutrients.py` with `GET /nutrients/daily` (authenticated with the existing user dependency, query params and 422 rules per contracts/daily-totals.md), and register the router in `src/backend/main.py`.
- [X] T031 [P] [US2] In `src/backend/api/meta.py`, add `GET /meta/nutrients`, returning `catalog.public_view()` with `version` and `groups`, plus the header `Cache-Control: public, max-age=3600`.
- [X] T032 [US2] *(Check-up display names are now catalogue names, for example "Dietary Fiber", "Total Sugars", "Vitamin B12". Clients render server names, so nothing in the UI depended on the old labels.)* Move the Check-up onto the catalogue:
  - in `src/backend/agent/tools/history.py`, rewrite the Check-up aggregates (`get_nutrient_checkup_aggregates` and helpers) to use `get_daily_micros` and catalogue `daily_value`, and delete `get_micronutrients_for_range`'s one-query-per-nutrient loop;
  - in `src/backend/config/tunables.yaml`, replace `nutrient_checkup.micronutrients` and `nutrient_checkup.rda` with `nutrient_checkup.keys: [protein, fiber, total_sugars, vitamin_c, vitamin_d, iron, calcium, vitamin_b12]`, plus `nutrient_checkup.daily_value_overrides: {total_sugars: 50}` (the existing 50 g proxy, spec FR-001a), and keep `flat_threshold_pct`;
  - in `src/backend/config/__init__.py`, delete `MicronutrientConfig` and update `NutrientCheckupConfig` to match.
- [X] T033 [US2] Move the Mindful panel onto the catalogue:
  - in `src/backend/agent/tools/mindful.py`, read day totals from `get_daily_micros` and safety thresholds from catalogue `upper_limit`;
  - delete the top-level `upper_limits:` block from `src/backend/config/tunables.yaml`, and delete `UpperLimitEntry` and the `upper_limits` field from `src/backend/config/__init__.py` (FR-018).
- [X] T034 [US2] Move coaching onto catalogue keys:
  - in `src/backend/agent/coaching.py`, resolve parsed nutrient names via `catalog.resolve_key`, which accepts keys or USDA aliases, and fetch micros via `get_daily_micros`. `_MACRO_ALIASES` is unchanged, and `_humanize_nutrient_name` uses the catalogue `name`;
  - in `src/backend/config/prompts/query_parse_system.md`, replace "EXACT USDA names" with the catalogue keys (list them).
- [X] T035 [US2] *(Verified, no code change: the worker calls the rewritten aggregates and `test_workers.py` passes.)* Check that the nightly task in `src/backend/workers/tasks.py` (`build_nutrient_checkup`) works with the new aggregates. The `nutrient_checkup` table shape is unchanged (it is a rebuildable cache), and `notable_nutrients` naming uses catalogue names.
- [X] T036 [US2] Update the existing tests that assert the old Check-up, Mindful or coaching shapes or USDA names: `tests/test_nutrient_checkup_api.py`, `tests/test_mindful_api.py`, `tests/test_coaching.py`, `tests/test_workers.py`, `tests/test_trends.py`.
- [X] T037 [US2] *(Also: `log_meal` fills missing `sugar_g`/`sat_fat_g` from server-resolved micros, so the junk flag still works on "Log again". Stored entities also exclude `micros`.)* **Remove the duplicate storage** now that every reader has switched (FR-018, research R12):
  - in `src/backend/agent/tools/meals.py`, the stored `entities` exclude `nutrients`, `sugar_g` and `sat_fat_g`;
  - in `src/backend/agent/tools/usda.py`, remove the `USDAResult.nutrients` field and `NutrientValue` usages from the builders (`_result_from_local`, `_result_from_cache`, `_parse_fdc_response`, `_miss_result`, `_estimate_result`);
  - in `src/backend/api/my_meals.py`, remove the `nutrients` scaling loop in `_scaled_result` and scale `micros` instead.
  
  Keep the in-memory `sugar_g` and `sat_fat_g` for `_is_junk`.
- [X] T038 [US2] Update the remaining tests that build or assert per-item `nutrients`: `tests/test_my_meals_api.py`, `tests/test_my_meals_graph.py`, `tests/test_my_meals_log.py`, `tests/test_log_items.py`, `tests/test_log_items_corrections.py`, `tests/test_meal_tools.py`, `tests/test_usda_tools.py`, `tests/test_usda_local.py`, `tests/test_usda_source_dish.py`, `tests/test_usda_unknown_portions.py`, `tests/test_usda_import.py`, `tests/test_foods_api.py`. Change assertions only where they assume the old shape.

**Checkpoint**: US1 and US2 together form the releasable MVP. One catalogue, one stored summary, and every reader consistent.

---

## Phase 5: User Story 3 - Know how much of a number is estimated (Priority: P2)

**Goal**: The estimated share and completeness are available wherever meal micros leave the backend (meal detail, integration feed, daily totals), ready for the future visualization feature. No new UI.

**Independent Test**: Seed a week where half the iron comes from estimated foods. `GET /nutrients/daily` gives `est / total ≈ 0.5` for iron, and `GET /meals/log/{id}` shows `micros` with `est` and `known` (quickstart 12; contracts/meal-micros.md §3, §5).

### Tests for User Story 3 ⚠️

- [X] T039 [P] [US3] Write `tests/test_meal_micros_exposure.py`. Check that:
  - `GET /meals/log/{id}` includes `micros` with `total`, `est` and `known`, and its `items[]` have no `nutrients`;
  - `GET /v1/integrations/meals` includes `micros` on active meals and none on tombstones;
  - the seeded half-estimated week gives an iron `est/total` of 0.5 ± 0.01 from `/nutrients/daily`.

### Implementation for User Story 3

- [X] T040 [P] [US3] In `src/backend/api/meals.py`, add `micros: dict[str, MealMicro]` to `MealLogDetail` (a Pydantic `MealMicro` with `total: float`, `est: float` and `known: int`, ge 0) and populate it from `row.micros` in `get_meal_log`.
- [X] T041 [P] [US3] In `src/backend/api/integrations.py`, add `micros` to `MealOut` (same `MealMicro` model, imported and not redefined), include `micros` in the feed's SELECT, and omit it for tombstones.
- [X] T042 [P] [US3] In `frontend/src/api/types.ts`, add the types `NutrientDef`, `NutrientCatalog`, `MealMicro`, `DailyMicros` and `DailyMicrosResponse`, plus `micros?: Record<string, MealMicro>` on the meal-detail type. Keep `nutrients?` optional on card items. No UI changes (FR-014; visualization is a later feature).

**Checkpoint**: All three stories are done.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T043 [P] Update the seed scripts so they write the new stored shape (no per-item `nutrients`, a `micros` summary via `summarise`): `src/backend/scripts/seed_debug_user.py`, `seed_history.py`, `seed_my_meals.py`, `seed_my_meals2.py`, `simulate_coaching_users.py`.
- [ ] T044 [P] Add changelog entries:
  - `docs/integration-api.md`: `entities[].nutrients` removed and `micros` added (contracts/meal-micros.md §5);
  - `docs/reference/mobile-api.md`: card `nutrients` removed, server-side micro resolve, `GET /meta/nutrients`, `GET /nutrients/daily`.
- [ ] T045 [P] In `specs/004-micronutrient-analytics/spec.md`, update FR-007 and User Story 3 so "top contributors" are attributed to **meals**, not foods (008 FR-014a), and note that its data source is `GET /nutrients/daily` (008 FR-017).
- [ ] T046 Run `black src/backend tests` and `ruff check src/backend tests --fix`, then fix any remaining lint.
- [ ] T047 Run the full suites (SC-010): `pytest`; `cd frontend && npm test`; `cd android && ./gradlew testDebugUnitTest verifyRoborazziDebug` (screenshot tests prove the card is unchanged, SC-002). Fix regressions, and change tests only where they asserted the old shape.
- [ ] T048 Measure: logging latency on 30 meals before and after, where the median may rise by at most 10% (SC-003); and `build_micro_estimates.py --benchmark 50`, where at least 70% must be within ±50% (SC-004). Record the results in `specs/008-fixed-micronutrients/quickstart.md`.
- [ ] T049 Walk through quickstart scenarios 1–16 against a local backend and record pass or fail for each in `specs/008-fixed-micronutrients/quickstart.md`.
- [ ] T050 **Release gate (needs the user)**:
  - confirm whether life-os reads `entities[].nutrients` from the integration feed (research R13);
  - get approval to run the full `build_micro_estimates.py`, about 13.7k Flash-Lite calls (research R6);
  - confirm the rebuilt `usda_fdc.sqlite3` is committed or shipped with the image.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)** depends on nothing.
- **Foundational (Phase 2)** depends on Setup and blocks every story.
- **US1 (Phase 3)** depends on Foundational.
- **US2 (Phase 4)** depends on Foundational. T029–T036 can run alongside US1, but **T037 and T038 need US1 done** (T021 must write `micros` before the old per-item storage is removed).
- **US3 (Phase 5)** depends on T007 and T008 (column), and its tests need US1's write path (T021).
- **Polish (Phase 6)** depends on all stories. T050 gates release, not implementation.

### User Story Dependencies

- **US1 → US2 (release coupling)**: they can be built independently, but must ship together (FR-019). Without US2, the Check-up would keep reading data that T037 removes.
- **US3**: reads only `meal_log.micros`, so it is independent of US2.

### Within Each User Story

- Tests first, and they must fail.
- Data access (T013, T016) comes before resolve (T017), then the estimate (T018–T020), then the write path (T021), then the API paths (T022–T025).
- Commit and push after each task (memory).

### Parallel Opportunities

- Phase 1: T002 runs alongside T001.
- Phase 2: T006 runs alongside T007–T009 once T003–T005 are done.
- US1: T010, T011 and T012 together; T019 alongside T016–T018.
- US2: T026, T027 and T028 together; T031 alongside T029 and T030.
- US3: T040, T041 and T042 together.
- Polish: T043, T044 and T045 together.

---

## Parallel Example: User Story 1

```bash
# Tests together:
Task: "T010 tests/test_resolve_micros.py"
Task: "T011 tests/test_estimate_micros.py"
Task: "T012 tests/test_meal_micros_write.py"

# Prompt edit runs alongside the data-access work:
Task: "T019 config/prompts/nutrition_estimate_system.md"
Task: "T016 agent/tools/usda_local.py load_micros_per_100g"
```

---

## Implementation Strategy

### MVP (US1 + US2, released together)

1. Phases 1–2 (T001–T009).
2. US1 (T010–T025). Validate with quickstart 2–5 and 7–10. Run `build_micro_estimates.py --dry-run` and `--benchmark 50` only.
3. US2 (T026–T038). Validate with quickstart 1, 6 and 11–14.
4. **Stop**: run T047 (all suites green), then the T050 gate.

### Incremental delivery

- MVP (US1 + US2): new meals carry full micros, and every view is consistent.
- US3: the estimated share and completeness are exposed (meal detail, feed, types), ready for the visualization feature.
- Polish: docs, seeds, spec 004 alignment, measurements.

---

## Notes

- `[P]` means a different file and no dependency on an unfinished task.
- FR-018 is checked at T037 (removing duplicates) and in quickstart 11.
- The full gap-estimate build (T015) is the only task with external cost, and it needs the user's approval (T050).
- Git is currently on `feat/android-app`. Switch to or create the `008-fixed-micronutrients` branch before the first commit.
