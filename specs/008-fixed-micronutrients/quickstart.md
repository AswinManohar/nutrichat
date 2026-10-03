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
