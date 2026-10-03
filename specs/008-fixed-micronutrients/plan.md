# Implementation Plan: Fixed Micronutrient Set with Estimated Fallback

**Branch**: `008-fixed-micronutrients` | **Date**: 2026-10-03 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/008-fixed-micronutrients/spec.md`

## Summary

Define one catalogue of 48 tracked nutrients (`config/nutrients.yaml`). Every
logged meal gets a summary for each nutrient. Values come from USDA first.
Gaps in USDA matches come from estimates **pre-computed at build time** in
the bundled SQLite. Foods with no USDA match get their nutrients from the
existing single AI estimate call, extended. Eight trace elements are
USDA-only.

The summary is computed on the server for every item at log time, and stored
once on `meal_log.micros`, the only new column. Saved meals keep values per
ingredient and compute their totals when read. Raw per-item `nutrients` stop
being stored anywhere.

The confirmation card is unchanged. A catalogue endpoint and a per-day totals
endpoint prepare the ground for the future visualization feature. All
existing readers move over in the same release: Check-up, Mindful panel,
coaching, Android "Log again", meal detail and the integration feed.

## Technical Context

**Language/Version**: Python 3.12 (backend). TypeScript and React 19 (web,
type-only change). Kotlin (Android, no code change expected).

**Primary Dependencies**: FastAPI, SQLAlchemy async and Alembic, Pydantic v2,
pydantic-ai (Gemini 2.5 Flash-Lite estimate agent), Logfire, Celery (nightly
Check-up).

**Storage**: PostgreSQL 16 (`meal_log.micros` JSONB, new). The bundled SQLite
`usda_fdc.sqlite3` gets a new `food_micro_estimate` table (schema v3).
Redis is unchanged.

**Testing**: pytest + pytest-asyncio (real local Postgres via
`tests/conftest.py`), vitest (web), Gradle unit + Roborazzi screenshots
(Android).

**Target Platform**: Railway Linux services (web, worker, bot), plus the web
and Android clients.

**Project Type**: Web service with web and mobile clients.

**Performance Goals**: Log latency median +10% at most (SC-003). Per-day
totals for 90 days and 48 nutrients under 1 s at p95 (SC-008). No extra AI
call on the USDA-match path (research R6).

**Constraints**: FR-018 single source of truth (user rule, saved to memory).
Unknown is never stored as 0. No backfill. Client-supplied nutrition is never
trusted. The micronutrient estimate shares the existing single call (FR-009).

**Scale/Scope**: Dev scale (7 users, ~290 meals). The bundled catalogue has
13,694 foods. About 15 backend modules, 1 migration, 1 build script, 2 new
endpoints and about 20 test files are touched.

No NEEDS CLARIFICATION remains. One **open external question** does not
block design: whether life-os reads `entities[].nutrients` from the
integration feed (research R13). It blocks release, not implementation.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` is still the unfilled template, so the
gates come from `.claude/CLAUDE.md` coding standards and the user's
standing rules (memory).

| Gate | Pre-design | Post-design |
|---|---|---|
| All I/O async, no blocking calls (CLAUDE.md) | ✅ SQLite lookups stay in `asyncio.to_thread` (existing pattern) | ✅ `resolve_micros` reuses `usda_local` via `to_thread` |
| Pydantic at every boundary, `extra="forbid"` | ✅ | ✅ Catalogue, `MicroValue`, `DailyMicros`, `NutritionEstimate.micros` |
| Google-style docstrings, type annotations, 88 columns | ✅ | ✅ |
| No data stored twice (user rule, FR-018) | ✅ | ✅ fiber stays in its column only, salt is derived, saved-meal totals are computed when read, raw nutrients are dropped. The only deliberate copy is a logged-meal snapshot, justified in spec FR-018 |
| Config over hard-coding (tunables pattern) | ✅ | ✅ `nutrients.yaml` replaces the Check-up's private lists |
| Don't break shipped features (user rule) | ✅ FR-019 lists every reader | ✅ [contracts/meal-micros.md](./contracts/meal-micros.md) covers each interface |
| Ask before big or costly runs (memory) | ⚠️ the gap-estimate batch costs a few dollars | ⚠️ `--dry-run` first, full run only on approval |
| Never commit to the production branch (memory) | ✅ work on `008-fixed-micronutrients` | ✅ |

No unjustified violations. The ⚠️ is a process gate (approval), not a design
violation.

## Project Structure

### Documentation (this feature)

```text
specs/008-fixed-micronutrients/
├── spec.md
├── plan.md              # this file
├── research.md          # Phase 0: R1–R16 decisions
├── data-model.md        # Phase 1
├── quickstart.md        # Phase 1: 16 validation scenarios
├── contracts/
│   ├── nutrients-catalogue.md   # GET /meta/nutrients (new)
│   ├── daily-totals.md          # GET /nutrients/daily (new)
│   └── meal-micros.md           # every changed existing payload
├── checklists/requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks; not created here)
```

### Source Code (repository root)

```text
src/backend/
├── config/
│   ├── nutrients.yaml                 # NEW catalogue (48 entries)
│   ├── __init__.py                    # + NutrientCatalog model, get_catalog()
│   ├── tunables.yaml                  # − nutrient_checkup.micronutrients/rda; + .keys
│   └── prompts/
│       ├── nutrition_estimate_system.md   # + per-100 g micros
│       └── query_parse_system.md          # catalogue keys instead of USDA names
├── nutrients/                         # NEW package
│   ├── __init__.py
│   ├── catalog.py                     # alias→key map, caps, USDA-only set
│   ├── resolve.py                     # resolve_micros(), summarise() (R9)
│   └── daily.py                       # get_daily_micros() (R11)
├── agent/tools/
│   ├── usda.py                        # USDAResult.nutrients → micros; estimate + micros
│   ├── usda_local.py                  # read food_micro_estimate; map to keys
│   ├── meals.py                       # log_meal: resolve + summarise, strip stored fields
│   ├── history.py                     # micronutrient readers → get_daily_micros
│   ├── mindful.py                     # → catalogue + meal summaries
│   └── saved_meals.py                 # ingredients carry micros
├── agent/coaching.py                  # nutrient names → catalogue keys (aliases)
├── agent/orchestrator.py              # card payload: drop nutrients
├── api/
│   ├── meta.py                        # + GET /meta/nutrients
│   ├── nutrients.py                   # NEW GET /nutrients/daily
│   ├── meals.py                       # detail + micros; log-items ignores client micros
│   ├── my_meals.py                    # ingredient micros; micros_totals computed on read
│   └── integrations.py                # MealOut + micros
├── scripts/
│   ├── build_usda_db.py               # schema v3, food_micro_estimate table
│   ├── build_micro_estimates.py       # NEW batch gap-fill (--dry-run, --benchmark)
│   └── seed_*.py                      # new stored shape
├── db/
│   ├── models.py                      # MealLog.micros
│   └── migrations/versions/20261003_018_meal_micros.py   # NEW
└── main.py                            # include nutrients router

tests/                                  # update ~17 files; add test_nutrient_catalog,
                                        # test_resolve_micros, test_daily_micros,
                                        # test_meal_micros_compat
frontend/src/api/types.ts               # nutrients? stays optional; add catalogue types
docs/integration-api.md, docs/reference/mobile-api.md   # changelog entries
```

**Structure Decision**: Keep the existing `src/backend` layout. New
nutrient logic goes into one small `backend/nutrients/` package (catalogue
lookup, resolve, daily totals), so the summary rule has exactly one
implementation that every log path and reader calls. No Android code change
is planned. The Android screenshot tests act as the regression check for the
"card unchanged" requirement.

## Implementation order (input for /speckit-tasks)

1. **Catalogue**: `nutrients.yaml`, the Pydantic model, `GET /meta/nutrients`,
   and catalogue tests.
2. **Bundled data**: SQLite schema v3, plus the `build_micro_estimates.py`
   dry run and benchmark (SC-004). **The full run waits for approval.**
3. **Resolve and summarise**: `resolve_micros`, `summarise`, the extended
   estimate call, and the plausibility caps.
4. **Write path**: migration 018, `log_meal` (summary, stripped entities, span
   counts), `log-items` and the saved-meal log path ignoring client micros.
5. **Saved meals**: ingredient `micros`, `micros_totals` computed on read.
6. **Readers**: `get_daily_micros` and `GET /nutrients/daily`; the Check-up,
   Mindful panel and coaching switch over in the same change (FR-019).
7. **Compatibility**: meal detail and integration feed `micros`, docs, seed
   scripts, card payload cleanup.
8. **Verification**: all suites green (SC-010), and quickstart scenarios
   1–16.

## Complexity Tracking

No constitution violations to justify.
