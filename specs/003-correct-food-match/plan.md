# Implementation Plan: Correct a Wrong Food Match

**Branch**: `003-correct-food-match` (spec docs; this repo's `001-jev-intent-routing` checkout) → **code lands on `feat/android-app`** (worktree `~/nutrichat-android`) | **Date**: 2026-09-28 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/003-correct-food-match/spec.md`

## Summary

The Android "Not the right food?" picker becomes a real correction tool (GitHub #39):

- **Search**: free-text search over the bundled USDA reference DB, pre-filled with the user's words.
- **Nutrition previews**: kcal and protein for each suggestion and result, scaled to the item's grams.
- **Instant local swap**: the server builds the chosen item and the client swaps it in place, with no assistant round trip. An Undo is offered.

Corrections are recorded at log time for later analysis and the planned "remember my corrections" follow-up. Logging a card also resolves its paused conversation, so recovery can't bring back a stale card. The web app is unchanged.

Technical approach (details in [research.md](research.md)):

- **New backend endpoints**:
  - `GET /foods/search`: FTS5 + existing ranker over `usda_fdc.sqlite3`
  - `GET /foods/{fdc_id}?qty_g=`: builds a ready-to-log item server-side
- **Additive card fields**: `candidate_details`, and `input_phrase` if needed.
- **log-items extension**: an optional `correction` per item, which writes to the new `food_correction` table, plus pending-card resolution.
- **Android**: a redesigned picker sheet with a debounced `mapLatest` search, and a local swap in `CardEditor`/`ChatSessionStore` that follows the existing quantity-edit and remove pattern.

## Technical Context

**Language/Version**: Python 3.13 (project `.venv`), Kotlin 2.x / Jetpack Compose (Compose BOM 2024.09.03)

**Primary Dependencies**:
- Backend: FastAPI, Pydantic v2, SQLAlchemy async, Alembic, sqlite3 (stdlib, FTS5), Redis (rate limiting)
- Android: Retrofit/OkHttp, Hilt, Kotlin Coroutines/Flow, Material 3, the project's `core/ui` design system

**Storage**:
- Postgres (Supabase): new `food_correction` table
- Read-only SQLite `src/backend/data/usda_fdc.sqlite3`: food reference
- LangGraph checkpoint tables: pending-card resolution

**Testing**: pytest (`PYTHONPATH=src uv run python -m pytest`), offline food-identity eval (`eval/cases/food_identity*.jsonl`), Android JUnit + Robolectric + Turbine-style Flow tests, Roborazzi goldens, ktlint, Android lint

**Target Platform**: Railway (Linux) backend; Android API 28+ (tested on the API 36 emulator)

**Project Type**: Mobile app + API (plus an unchanged web frontend)

**Performance Goals**:
- `GET /foods/search` p95 < 300 ms server-side (UI target < 1 s, SC-003)
- `GET /foods/{fdc_id}` p95 < 200 ms
- Swap visible on the card in < 1 s (SC-002)

**Constraints**:
- No blocking I/O on the event loop: SQLite runs via `asyncio.to_thread`.
- Backward compatible: the web app and older Android builds ignore the new fields.
- Migrations are applied manually on Supabase.
- One Gradle run at a time per worktree.

**Scale/Scope**:
- Reference DB: ~13.7k generic foods.
- Search: ≤ 20 results per query.
- Android: 1 sheet redesign plus the swap path.
- Backend: 2 endpoints, 1 table, 1 request-field extension, the pending-resolution hook.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` is the **unfilled template**, so there are no ratified principles to gate on. The repo's standing engineering rules act as the working gates:

| Gate (source) | Pre-design | Post-design |
|---|---|---|
| Typed, documented Python; Pydantic at every boundary (`.claude/CLAUDE.md`) | ✅ planned | ✅ contracts define Pydantic models for search result, candidate detail and correction |
| All I/O async; never block the loop (`.claude/CLAUDE.md`) | ✅ | ✅ SQLite wrapped in `asyncio.to_thread` (R8) |
| No wildcard imports, Black/Ruff defaults (`.claude/CLAUDE.md`) | ✅ | ✅ |
| Android design system + Design QA checklist: one olive element, 48 dp targets, semantics (`android/CLAUDE.md`) | ✅ | ✅ picker contract specifies semantics, 48 dp rows, skeletons, InkToast |
| Keep lexical ranker; no embeddings/LLM rerank (2026-09-24 decision) | ✅ | ✅ search reuses `_rank_key` (R2) |
| Web app unchanged (spec FR-010) | ✅ | ✅ additive fields only |
| Branch policy: work on `feat/android-app`, never `production`/`andorid_prod` | ✅ | ✅ |

**Result**: PASS. No violations, so Complexity Tracking is empty.

## Project Structure

### Documentation (this feature)

```text
specs/003-correct-food-match/
├── plan.md              # This file
├── research.md          # Phase 0: R1–R9 decisions
├── data-model.md        # Phase 1: entities, table, card-item state machine
├── quickstart.md        # Phase 1: validation guide
├── contracts/
│   ├── foods-api.md         # GET /foods/search, GET /foods/{fdc_id}, card + log-items additions
│   └── android-picker-ui.md # Picker sheet UX/a11y contract
├── checklists/requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks — not created here)
```

### Source Code (in the `feat/android-app` worktree `~/nutrichat-android`)

```text
src/backend/
├── agent/tools/
│   ├── usda_match.py        # (cherry-pick 87c9c9d + #38) ranker + _normalize_preparation; + search ranking helper
│   ├── usda_local.py        # + search(q, limit) and get_food(fdc_id) read helpers
│   └── usda.py              # + candidate_details on USDAResult
├── api/
│   ├── foods.py             # NEW: GET /foods/search, GET /foods/{fdc_id}
│   ├── meals.py             # log-items: correction handling + pending resolution
│   └── account.py           # delete FoodCorrection rows
├── agent/orchestrator.py    # resolve_pending(user_id, conversation_id)
├── db/models.py             # + FoodCorrection
├── db/migrations/versions/20260928_015_food_correction.py   # NEW
└── main.py                  # include foods router
tests/
├── test_foods_api.py        # NEW
├── test_log_items_corrections.py  # NEW
└── test_usda_local.py       # + search/get_food cases
eval/                        # + search-mode top-5 check for food_identity sets

android/
├── core/data/src/main/kotlin/app/mealsy/data/
│   ├── api/MealsyApi.kt     # + searchFoods, getFood; log-items correction field
│   ├── api/Dtos.kt          # + FoodSearchResultDto, CandidateDetailDto, CorrectionDto
│   └── repo/FoodRepository.kt   # NEW
├── core/domain/src/main/kotlin/app/mealsy/domain/
│   └── CardItem.kt          # + candidateDetails, inputPhrase, pendingCorrection
├── core/ui/src/main/java/app/mealsy/android/design/components/
│   └── CandidatePickerSheetContent.kt  # redesigned per contract
└── app/src/main/java/app/mealsy/android/ui/chat/
    ├── FoodPickerViewModel.kt   # NEW: debounced search state
    ├── ChatSessionStore.kt      # local swap + undo, correction bookkeeping
    ├── CardEditor.kt            # swapItem / undoSwap
    └── ConfirmCardView.kt       # wiring
```

**Structure Decision**: Mobile + API. The backend lives in `src/backend` and the Android app in `android/` (modules `app`, `core/ui`, `core/data`, `core/domain`), both in the `feat/android-app` worktree. The spec docs stay in this repo's `specs/` so they sit next to specs 001/002.

## Implementation Order (for /speckit-tasks)

1. **Foundation**:
   - Cherry-pick the matcher work onto `feat/android-app` (#51): `87c9c9d` ranker, `f362722` eval set, `7769543` #38 toast fix. Gate: ≥ 156/177 on the food-identity set.
   - Add the migration and model.
   - Add `usda_local` search and get helpers, with tests.
2. **Backend Story 1**:
   - Add the two `/foods` endpoints.
   - Add `correction` handling to log-items, and resolve the pending card on log.
   - Add the account deletion row.
   - Add the eval search mode.
3. **Backend Story 2**: add `candidate_details` (and `input_phrase` if needed) to card items.
4. **Android Story 1**:
   - DTOs and repository.
   - Picker ViewModel (debounce/mapLatest/offline).
   - Redesigned sheet.
   - Local swap and undo.
   - Correction on log.
5. **Android Story 2**: show suggestions with nutrition, and swap from a suggestion through the same local path.
6. **Polish**: goldens, a11y checks, quickstart run on the emulator, SC-004 eval gate.

## Complexity Tracking

No constitution violations to justify.
