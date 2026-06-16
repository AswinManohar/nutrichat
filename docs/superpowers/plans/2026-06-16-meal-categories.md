# Meal Category Feature Implementation Plan

> **For agentic workers:** Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Associate every logged meal with a user-picked category (breakfast / brunch /
lunch / dinner / snack), then surface per-category macro breakdowns and pattern history.

**Architecture:** The category is selected on the confirmation card (pre-filled by the
browser's local time, fully user-overridable via a dropdown). It rides along with the
confirm/correct request, is injected into LangGraph state on resume, and lands in the
existing `meal_log.meal_type` column. Analytics aggregate on read over existing indexes,
cached in Redis. **No new tables, no migration, zero added hot-path latency.**

**Tech Stack:** FastAPI · LangGraph · PostgreSQL (existing `meal_log`) · Redis · React + TS

---

## Canonical categories

`breakfast · brunch · lunch · dinner · snack` — defined once in backend
(`MEAL_CATEGORIES` tuple + `Literal`) and frontend (`MealCategory` union). Validated in
Pydantic; not a Postgres enum (adding a category later needs no migration).

Local-time → default mapping (frontend, deterministic — not agent inference):
`5–10:30 breakfast · 10:30–12 brunch · 12–15 lunch · 15–17 snack · 17–22 dinner · else snack`.

Server-side fallback (`normalize_meal_type`) reuses the same hour→category map via
`_DAY_TZ`, used only when a request arrives with a missing/invalid category (e.g. Telegram).

---

## Phase 1 — Capture the category (user-picked)

**Files:**
- Modify: `src/backend/agent/tools/meals.py` (add `MEAL_CATEGORIES`, `normalize_meal_type`, `_meal_type_from_hour`)
- Modify: `src/backend/agent/graph.py` (`log_node` already reads `state["meal_type"]` — normalize it)
- Modify: `src/backend/agent/orchestrator.py` (`handle_message` + `_handle_meal_logging` accept `meal_type`, inject into state on resume)
- Modify: `src/backend/api/meals.py` (`LogMealRequest.meal_type`)
- Modify: `frontend/src/api/types.ts` (`MealCategory`, `LogMealRequest.meal_type`)
- Modify: `frontend/src/components/chat/ConfirmationCard.tsx` (category dropdown)
- Modify: `frontend/src/components/chat/ChatThread.tsx` (`onAction` signature)
- Modify: `frontend/src/pages/ChatPage.tsx` (`handleSend` threads `mealType`)
- Test: `tests/test_meal_categories.py` (pure `_meal_type_from_hour` + `normalize_meal_type`)

- [ ] Backend constants + normalizer with hour-boundary tests
- [ ] Orchestrator threads `meal_type` into graph state on resume
- [ ] API request field
- [ ] Frontend dropdown (button shows current category → click opens scroll list of the rest)
- [ ] `onAction(text, mealType?)` plumbed through ChatThread → ChatPage → request
- [ ] `tsc` + `pytest` green

## Phase 2 — Per-category macro breakdown

**Files:**
- Modify: `src/backend/agent/tools/history.py` (`get_category_breakdown(user_id, days)`)
- Modify: `src/backend/api/meals.py` (`GET /meals/categories/breakdown?days=30`, Redis-cached)
- Frontend: a per-category panel in the dashboard

Query (one indexed GROUP BY over `ix_meal_log_user_logged_at`):
```sql
SELECT meal_type, COUNT(*) n, AVG(kcal), AVG(protein_g), AVG(carbs_g), AVG(fat_g), AVG(fiber_g)
FROM meal_log
WHERE user_id = :uid AND logged_at >= :since AND deleted_at IS NULL
GROUP BY meal_type
```
Cache key `mealcat:breakdown:{user_id}:{days}`, TTL 300s, busted on new log.

## Phase 3 — Pattern history

**Files:**
- Modify: `src/backend/agent/tools/history.py` (`get_category_patterns(user_id, days)`)
- Modify: `src/backend/api/meals.py` (`GET /meals/categories/patterns?days=30`, Redis-cached)
- Frontend: compact per-category timeline/frequency viz

Per category: meals/day frequency, avg kcal, and week-over-week trend. Same indexed
query shape grouped additionally by week bucket. Same caching idiom.

---

## Scaling notes
- Per-user meal volume is naturally tiny (~a few rows/day). Read-time aggregation over
  existing indexes is cheap and avoids write amplification + staleness.
- Every query keys on `user_id` → shards/replicas cleanly.
- **Deferred (YAGNI):** precomputing per-category daily rollups in the
  `aggregate_daily_summary` worker. Only if a user accumulates huge history.
