# Quickstart: validating fixed micronutrients

Each scenario below proves one requirement from the spec. Shapes and
contracts are defined in [data-model.md](./data-model.md) and
[contracts/](./contracts/).

## Prerequisites

- A local Postgres (tests: `127.0.0.1:5411/nutrichat`; see `tests/conftest.py`)
  migrated to head: `alembic upgrade head`.
- `GOOGLE_API_KEY` set, for estimate scenarios only.
- The bundled SQLite rebuilt with gap estimates (schema v3, research R6). Run
  `PYTHONPATH=src python -m backend.scripts.build_micro_estimates --dry-run`
  first to see the cost and count, then without `--dry-run`. **The full run
  needs the user's approval.**
- Backend: `uvicorn backend.main:app --reload --port 8000`.

## Automated suites (SC-010)

```bash
pytest                                   # backend, all 70+ test files
cd frontend && npm test                  # vitest
cd android && ./gradlew testDebugUnitTest verifyRoborazziDebug   # unit + screenshots
```

All must pass. Tests change only where they asserted the old per-item
`nutrients` shape.

## Scenarios

| # | Proves | Steps | Expected |
|---|---|---|---|
| 1 | Catalogue (FR-015, SC-009) | `GET /meta/nutrients` | 48 entries in 5 groups. Salt has `derived`. 8 entries have `usda_only` |
| 2 | Unmatched food (US1-1) | Log "mom's rasam" in chat, then confirm | `meal_log.micros` has all estimable keys with `est == total`. No USDA-only keys |
| 3 | Full USDA match (US1-2) | Log "1 banana" | Keys USDA reports have `est == 0`. `added_sugars` comes from the pre-computed estimate (`est == total`). No AI call during the log (check the Logfire span) |
| 4 | USDA zero kept (Clarification) | Log "grilled chicken breast" | `vitamin_c.total == 0`, `est == 0` |
| 5 | Card unchanged (FR-014, SC-002) | Render the card on web and Android | No micronutrient rows. Android screenshot tests unchanged |
| 6 | Sugars aliases (SC-005) | pytest: a fixture item with `Sugars, Total` plus one with `Total Sugars` | `total_sugars.total` equals the sum of both |
| 7 | Implausible estimate (FR-007) | pytest: a stubbed estimate with iron at 5000 mg/100 g | `iron` is absent (unknown), and the rejected count is 1 |
| 8 | Estimate failure (FR-008) | pytest: the estimate call raises | The meal is logged with macros, and `micros == {}` |
| 9 | Log again (FR-019) | Android: open a logged meal, tap "Log again" at portion 1 | The new meal's `micros` equals the original's |
| 10 | Saved meal edit (FR-014a) | `PUT /my-meals/{id}` removing one ingredient | `micros_totals` drops by that ingredient's amounts. No totals are stored in `user_meal` |
| 11 | No duplication (FR-018) | Inspect the stored `meal_log.entities` | No `nutrients`, `sugar_g` or `sat_fat_g` on stored items. No `fiber` or `salt` key in `micros` |
| 12 | Daily totals (FR-017) | `GET /nutrients/daily?from=…&to=…` across a day with no meals | That day has `logged:false`. Salt is 2.5 × sodium / 1000 |
| 13 | Performance (SC-008) | pytest benchmark: seed 90 days × 4 meals, request all keys | p95 under 1 s |
| 14 | Consistency (SC-006) | Compare Check-up, coaching ("how much iron this week") and `/nutrients/daily` | Same totals |
| 15 | Logging speed (SC-003) | `python eval/probe_jev_latency.py`-style timing on 30 logs, before and after | Median increase of 10% or less |
| 16 | Estimate accuracy (SC-004) | `build_micro_estimates --benchmark 50`: force estimates for 50 USDA foods | At least 70% of values within ±50% of USDA |

## Results (2026-10-03, branch `008-fixed-micronutrients`)

### Measurements (T048)

| Check | Result |
|---|---|
| Logging overhead of server-side resolve (3-item USDA meal, 30 runs) | median **3.9 ms**, p95 5.5 ms |
| Card estimate call, live, 8 foods (old → new) | median 0.91 s → **0.76 s** (unchanged; micros moved off this call) |
| Background micro call, live, 8 foods | median **3.6 s** (max 4.7 s); **36 of 36** micros per food |
| SC-004 benchmark, 50 foods / 498 values, **gap-fill mode** (how USDA gaps are filled) | **74%** within ±50% → **PASS** |
| SC-004 benchmark, **no-context mode** (unmatched foods, name only) | 61% → below 70% (vitamin C 12/50 and folate 19/49 are the weak keys) |
| Full gap-fill build cost (dry run) | 13,694 foods, 149,399 values, ≈ **$1.75**, **not run** (needs approval) |

### Automated suites (T047)

| Suite | Result |
|---|---|
| Backend `pytest` (after per-item switch) | 717 passed, 1 xfailed, **1 failed**: `test_e2e_meals.py::test_chat_history_isolation`, which calls real Gemini with the dummy key. It fails the same way on `feat/android-app` before this work |
| Web `vitest` | 41 / 41 passed; `tsc` clean |
| Android `:core:data` + `:core:domain` tests | passed |
| Android `:app` unit + Roborazzi | **blocked by a failure already on `feat/android-app`**: the app's test fakes don't implement `MealsyApi.updateMyMeal` (8 files). This branch changes no Android files |

### Scenario walk-through (T049)

| # | Evidence | Status |
|---|---|---|
| 1 | `tests/test_meta_nutrients.py`, `tests/test_nutrient_catalog.py` | ✅ |
| 2 | `test_estimate_micros.py`, `test_resolve_micros.py::test_resolve_estimate_without_cached_micros_awaits_background`, plus the live micro call (36 of 36) | ✅ |
| 3 | `test_resolve_micros.py::test_resolve_from_bundled_usda`. Gap estimates still need the full build (T050) | ⚠️ gaps stay unknown until the build runs |
| 4 | `test_resolve_micros.py::test_resolve_usda_zero_for_chicken` | ✅ |
| 5 | Card payload drops `nutrients` and has no `micros` (`orchestrator.py`); web card is unchanged | ✅ web / ⚠️ Android screenshots blocked (see above) |
| 6 | `test_resolve_micros.py::test_resolve_sugars_total_alias`, `test_reader_consistency.py` | ✅ |
| 7 | `test_resolve_micros.py::test_implausible_estimate_is_rejected` | ✅ |
| 8 | `test_meal_micros_write.py::test_estimate_failure_logs_meal_with_empty_micros` | ✅ |
| 9 | `test_meal_micros_write.py::test_log_items_ignores_client_micros_and_log_again_matches` | ✅ |
| 10 | `test_meal_micros_write.py::test_saved_meal_stores_ingredient_micros_and_computes_totals` | ✅ |
| 11 | `test_meal_micros_write.py::test_log_meal_stores_compact_micros_on_each_item`; no summary column, no raw `nutrients` | ✅ |
| 12 | `test_daily_micros.py` | ✅ |
| 13 | `test_daily_micros.py::test_90_days_all_keys_under_one_second` | ✅ |
| 14 | `test_reader_consistency.py::test_all_readers_agree` | ✅ |
| 15 | Measurements above (card unchanged; resolve +4 ms) | ✅ with a caveat: confirming within about 3.6 s waits for the background call |
| 16 | Benchmark above | ✅ gap-fill / ⚠️ no-context at 61% |
