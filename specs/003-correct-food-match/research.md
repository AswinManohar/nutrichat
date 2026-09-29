# Research: Correct a Wrong Food Match

All findings are for the code on `feat/android-app` (worktree `~/nutrichat-android`), where this feature will be built.

## R1. Where do search results come from?

- **Decision**: Search the bundled local USDA SQLite database (`src/backend/data/usda_fdc.sqlite3`) through its existing FTS5 index. Don't call the live FDC API for search.
- **Rationale**: The DB is committed to the repo, so it ships in the Railway image. It holds 13,694 generic foods (Foundation, SR Legacy, FNDDS; no branded foods) with `fdc_id`, the main macros, and a compressed ~50-nutrient map. `_fts_candidates` (`usda_local.py:150-176`) is a single bm25-ranked FTS5 query at millisecond scale, so SC-003 (95% of searches under 1 s) is realistic. The live FDC API is cache-first but flaky: its errors turn silently into LLM estimates (see memory "USDA API flaky"), and it has no rate limiter of its own.
- **Alternatives considered**:
  - Live FDC `/foods/search`: rejected. Latency, random 404s, API-key limits.
  - Embedding search over foods: rejected, per the 2026-09-24 ranker decision (keep the lexical ranker).
  - Client-side DB on Android: rejected. 15 MB to ship, and two ranking implementations to keep in sync.
- **Consequence**: branded products never appear. That's acceptable, and FR-009 prefers generic foods anyway.

## R2. Ranking search results (FR-009, SC-004)

- **Decision**: Reuse the matching pipeline: `_normalize_preparation` (the #38 fix), the FTS pool, then `_rank_key`. Return the top N (default 10, max 20) rather than the top 3.
- **Rationale**: Search results and automatic matching then agree, and the existing food-identity eval sets can measure search quality ("correct food in top 5" for SC-004).
- **Dependency (updated 2026-09-28, GitHub #51)**: the Android branch's matcher is behind: 140/177 (79.1%) vs 156/177 (88.1%) on `001-jev-intent-routing`. Three commits exist only there and must be cherry-picked first:
  - `87c9c9d`: generic-first ranking and head-noun pool
  - `f362722`: the 176-case eval set
  - `7769543`: the #38 toast normalisation
  Without them, search inherits "rice → Rice crackers" and "water → Tonic water" style ranking. The review's misses (rice, toast, blueberries, chicken breast, water) become regression cases (task T022a).

## R3. Swap without the assistant (FR-004, SC-002)

- **Decision**: The client swaps the item **locally**, the same way quantity edits and removals already work through `CardEditor`. On selection it fetches the fully built item from a new `GET /foods/{fdc_id}?qty_g=` endpoint, which returns the same item shape the confirm card already uses, with its nutrients scaled server-side.
- **Rationale**: Swapping through the chat takes seconds and can mis-resolve again. `log-items` already accepts client-supplied `fdc_id` plus nutrients (`meals.py:163-182`, `extra="allow"`) and only rescales them. Having the server build the item from the reference DB means the client never computes nutrition, which keeps FR-005 ("log exactly what the card shows") trustworthy.
- **Alternatives considered**:
  - Put full nutrients in every search result: rejected. It makes every search response ~10× larger to serve a single tap.
  - Compute nutrients on the client from per-100 g values: rejected. It duplicates server logic and opens a new trust gap.
  - Keep the chat round trip: rejected. It's the problem this feature solves.

## R4. Stale paused conversation after a local swap

- **Finding**: `POST /meals/log-items` never touches the LangGraph checkpoint, and `GET /meals/pending` (`orchestrator.py:227-258`) returns the paused graph's `usda_results`. A card that was swapped locally and then logged can therefore come back, unswapped, on the next pending recovery. Local quantity edits and removals have the same latent problem today.
- **Decision**: When `log-items` succeeds and the request carries the card's `conversation_id`, the server marks that conversation's pending card resolved. Later `GET /meals/pending` calls return nothing for it. Before a log, local edits live in the singleton `ChatSessionStore` (they survive navigation, not process death, same as quantity edits today). The client-side dedupe from #40 remains as a second safeguard.
- **Open verification (task)**: confirm whether Android already sends `conversation_id` to `log-items` and whether it ignores a recovered card that duplicates a logged one. Add a regression test either way.

## R5. Suggested alternatives with nutrition (Story 2, FR-003)

- **Decision**: Add a `candidate_details` list next to the existing `candidates: list[str]` on each card item. Each detail has `fdc_id`, `name`, `data_type`, and kcal/protein per 100 g. `candidates` stays as-is, so the web app and older Android builds keep working (FR-010 leaves the web app unchanged).
- **Rationale**: The FTS pool already holds these rows (`lookup()` returns per-100 g macros), so this costs no extra queries. The Android DTO already turns richer objects into name strings (`Dtos.kt:136-150`), which shows the extension pattern.
- **Scaling**: the client displays `per_100g × qty_g / 100` purely as a *preview*. The logged numbers still come from `GET /foods/{fdc_id}` (R3).

## R6. Recording corrections (FR-012)

- **Decision**: Add a new `food_correction` table. Rows are written by the server **when the meal is logged** (inside `log-items`), from a `correction` block on each swapped item. There's no separate event call.
- **Rationale**: Only corrections that actually got logged count, so a swap followed by undo or cancel records nothing. No extra network call, no offline queue. The records aren't read by any matching code in this feature (FR-012: they don't change future matching).
- **Deletion**: add `FoodCorrection` to `DELETE /account` (`account.py:69-165`).
- **Migration**: the latest revision on this branch is `013` (device token). `andorid_prod` has a different `014` (coaching), because both branch from `011`. Use revision id `015_food_correction` with `down_revision="013"` to avoid a number clash. The branch merge will still need an Alembic merge revision (already tracked). Migrations are applied manually through Supabase; there's no release step.

## R7. Search-as-you-type on Android

- **Decision**: A ViewModel `MutableStateFlow<String>` for the query, then `debounce(250 ms)`, `distinctUntilChanged`, `filter { it.trim().length >= 2 }`, and `mapLatest { api.searchFoods(...) }`. `mapLatest` cancels in-flight stale requests (edge case "rapid typing"). `ConnectivityObserver` disables the field when offline.
- **Rationale**: There's no debounce utility in the codebase today. The Flow operators are standard and easy to test with `runTest` and virtual time.

## R8. Endpoint protection

- **Decision**: `GET /foods/search` and `GET /foods/{fdc_id}` require `get_current_user_id` and use the Redis `user_rate_limiter` (60/min for search, 30/min for detail; fails open like other routes). They don't consume chat credits or quota, since no LLM is involved.
- **Async rule** (`.claude/CLAUDE.md`: never block the event loop): SQLite reads run through `asyncio.to_thread`, matching how `resolve_local` is called today (verify during implementation).

## R9. What the picker shows when a query is empty or short

- **Decision**: On open, the field is pre-filled with the item's **original phrase** and results show immediately (FR-002). If the phrase isn't available on the item, it falls back to the matched food's name. A task verifies whether the extracted phrase is already on the wire (`food_name` vs matched description); if it isn't, add `input_phrase` to the item.

## Constitution

`.specify/memory/constitution.md` is still the unfilled template, so there are no ratified gates. The standards in the repo's `.claude/CLAUDE.md` (typed Python, Pydantic at boundaries, async I/O, Google docstrings, Black/Ruff; Kotlin/Compose design system in `android/CLAUDE.md`) serve as the working gates. See plan.md.
