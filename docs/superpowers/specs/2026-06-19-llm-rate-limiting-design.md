# LLM Rate Limiting Design

**Date:** 2026-06-19  
**Revised:** 2026-06-21 (post code-review, post-implementation corrections)  
**Status:** Implemented — branch `feat/llm-quota`  
**Author:** AswinManohar

---

## Problem

New users have unlimited access to LLM calls with no monetisation gate. We need
a per-user lifetime quota that degrades gracefully when exhausted, and that
unlocks a higher cap when users upgrade to a paid tier.

---

## Decision

Use a **Postgres-only atomic counter** on the existing `user_goal` table.

Alternatives considered:

| Option | Verdict |
|---|---|
| Redis counter (like `today:{user_id}`) | Rejected — Redis eviction silently resets a lifetime counter, creating a quota bypass. Requires Postgres backup anyway. |
| FastAPI middleware | Rejected — wrong granularity. One request can trigger 1–2 LLM calls; middleware counts per-request, causing systematic under-count (quota bypass). |
| Postgres atomic counter | **Chosen** — single atomic upsert eliminates TOCTOU race, ACID guarantees the counter cannot be reset by infrastructure faults, and lifetime counters never justify a cache layer. |

---

## Quotas

```python
FREE_QUOTA = 50    # default for all new users
PAID_QUOTA = 150   # set by billing on upgrade
```

These constants live in `src/backend/quota.py` and are the single source of
truth for all quota comparisons.

| Tier | Limit |
|---|---|
| Free (new users) | 50 LLM inferences |
| Paid | 150 LLM inferences |

The limit is a **lifetime cap** — it never resets. Upgrading bumps the cap from
50 → 150 without resetting the counter, so a free user who consumed 30 credits
has 120 remaining after upgrading.

### What counts as one inference

The limit is **per LLM inference** at the orchestrator level, with one explicit
exception for the coaching path:

| Call site | Credits consumed |
|---|---|
| Intent classifier (`_intent_llm.ainvoke`) | 1 per ambiguous turn (keyword-matched turns: 0) |
| Coaching turn (`_handle_coaching` in `orchestrator.py`) | **1 per turn** — not per internal LLM call |
| Meal-extraction graph (extraction node) | 1 |
| `apply_correction` node | 0 — exempt (see below) |
| `decompose_to_ingredients` node | 0 — exempt (see below) |

**Coaching credit rule:** `CoachingAgent.handle()` makes two internal LLM calls
(parse query + generate response). These are treated as **one credit** because
from the user's perspective a coaching question is one interaction. The guard is
placed in `_handle_coaching()` in `orchestrator.py`, not inside `coaching.py`.

**Exempt calls — `apply_correction` and `decompose_to_ingredients`:** These are
user-initiated within an already-confirmed meal-logging flow (the user tapped
"Fix" or "Break into ingredients" after seeing the confirmation card). Gating
them would interrupt a flow the user explicitly started, creating a confusing
mid-flow wall. They are not gated.

---

## Data Model

Two columns added to `user_goal` (Alembic migration required):

```sql
llm_requests_used  INTEGER NOT NULL DEFAULT 0
llm_quota          INTEGER NOT NULL DEFAULT 50
```

Both have server defaults so all existing rows get `0 / 50` automatically. No
backfill required.

---

## Quota Guard

A new module `src/backend/quota.py` exposes one function and the quota
constants:

```python
FREE_QUOTA = 50
PAID_QUOTA = 150

async def consume_llm_credit(user_id: str) -> bool:
    """Atomically increment the LLM request counter if under quota.

    Uses an upsert so new users without a user_goal row are initialised
    automatically with FREE_QUOTA. Returns True if a credit was consumed
    (caller may proceed). Returns False if the user is at or over quota
    (caller must degrade gracefully).

    Emits a Logfire event on both credit consumed and quota exhausted.
    """
```

### Underlying query — upsert

```sql
INSERT INTO user_goal (user_id, llm_requests_used, llm_quota)
VALUES ($1, 1, $FREE_QUOTA)
ON CONFLICT (user_id) DO UPDATE
  SET llm_requests_used = user_goal.llm_requests_used + 1
  WHERE user_goal.llm_requests_used < user_goal.llm_quota
RETURNING llm_requests_used
```

Returns one row if a credit was consumed, zero rows if the user is at or over
quota. The upsert ensures a missing `user_goal` row (brand-new user, not yet
onboarded) never silently blocks them — it creates the row with defaults and
counts the first credit.

### Observability

`consume_llm_credit()` emits two Logfire events using the existing
`logfire.span()` pattern:

- `quota_credit_consumed` — attributes: `user_id`, `used`, `limit`
- `quota_exhausted` — attributes: `user_id`, `limit` (fired when the function
  returns `False`)

These feed the product analytics funnel (how many users hit the wall, conversion
rate to paid).

---

## Hook Points

`consume_llm_credit()` is called at three sites only:

1. **Intent classifier** — in `_classify_intent()` (`orchestrator.py`), before
   `_intent_llm.ainvoke()`. Over-quota: skip the LLM, use keyword-only result;
   default to `"log_meal"` if no keyword matches. No credit consumed in this
   case (the guard is not reached when keyword routing succeeds).

2. **Coaching turn** — in `_handle_coaching()` (`orchestrator.py`), before
   calling `_coaching_agent.handle()`. One credit per turn regardless of how
   many internal LLM calls `CoachingAgent.handle()` makes.

3. **Meal-extraction graph** — in `_handle_meal_logging()` (`orchestrator.py`),
   before `graph.ainvoke()`. Over-quota: short-circuit before the graph runs and
   return the upgrade-prompt message in the standard response envelope. The guard
   lives in the orchestrator, **not** inside `graph.py`.

The keyword pre-filter (`_LOG_SIGNALS` / `_QUERY_SIGNALS`, lines 54–60 of
`orchestrator.py`) always runs before any LLM call and is never gated.

---

## Graceful Degrade Behaviour

| Site | Over-quota response |
|---|---|
| Intent classifier | Keyword-only routing; defaults to `log_meal` if ambiguous. Free — no credit consumed. |
| Coaching agent (web) | `"You've used all your free AI requests. Upgrade at nutrichat.app/upgrade to keep getting coaching insights."` |
| Coaching agent (Telegram) | `"You've used all your free AI requests. Visit nutrichat.app/upgrade to continue."` |
| Meal-extraction graph | Same upgrade-prompt string (web variant), returned in the standard `{status: "success", paused: false, items: []}` envelope — no frontend special casing needed. |

The response channel (web vs Telegram) is determined by the caller. The
orchestrator's `handle_message()` already accepts a `source` parameter (or the
Telegram handler calls it directly); the over-quota message string is selected
based on this at the call site.

---

## Upgrade Path

When a user pays, `POST /billing/upgrade` issues a plain `UPDATE user_goal SET llm_quota = :paid_quota WHERE user_id = :user_id` and returns 404 if no row exists (the user has not completed onboarding, so billing is not applicable). `llm_requests_used` is left untouched — a free user who consumed 30 credits has 120 remaining after upgrading to the paid tier.

> **Why UPDATE instead of upsert:** The upsert design in the original spec was revised after code review. An `INSERT … ON CONFLICT` that omits `dietary_prefs` and `streak_days` would fail at the DB level for any user without an existing row, because those columns have ORM-level defaults only, not server-side `DEFAULT` clauses in the DDL. A pure `UPDATE` is both simpler and correct — billing only makes sense after onboarding.

The `tier` field on `GET /quota` is derived at read time using the named
constants:

```python
from backend.quota import FREE_QUOTA, PAID_QUOTA

tier = "paid" if user_goal.llm_quota >= PAID_QUOTA else "free"
```

Note: this derivation is intentionally simple for the current two-tier model.
If a third tier is added, a dedicated `tier` enum column on `user_goal` should
replace this comparison. Until then, `FREE_QUOTA` and `PAID_QUOTA` are the
single definition point — changing them here propagates everywhere.

---

## Quota Status API

New router at `src/backend/api/quota.py`, registered in `main.py` via
`app.include_router(quota.router)` alongside the existing routers.

The endpoint uses `Depends(get_current_user_id)` from `backend.auth.supabase`
— same auth pattern as all other protected endpoints.

```
GET /quota
Authorization: Bearer <token>
```

Response:

```json
{
  "used": 34,
  "limit": 50,
  "remaining": 16,
  "exhausted": false,
  "tier": "free"
}
```

- `remaining` is computed server-side as `max(0, limit - used)` to handle any
  edge-case overflow without surfacing a negative number to clients.
- `exhausted` is `used >= limit`, giving the frontend a clean boolean to branch
  on for UI state without integer comparison.

Reads directly from `user_goal`; no cache.

---

## Security Properties

- **No TOCTOU race** — check and increment are one atomic DB operation.
- **ACID durability** — the counter survives Redis evictions, server restarts,
  and infrastructure faults.
- **No bypass via cache flush** — Postgres is the only store; there is no cache
  layer to clear.
- **Correct granularity** — checked per LLM inference, not per HTTP request,
  so concurrent calls within one user turn each consume a credit independently.
- **New-user safety** — the upsert initialises the quota row on first use;
  a missing row never silently blocks a user or grants unlimited access.

---

## Files Touched

| File | Change |
|---|---|
| `src/backend/db/models.py` | Add `llm_requests_used`, `llm_quota` to `UserGoal` |
| `src/backend/db/migrations/versions/*.py` | Alembic migration for the two columns |
| `src/backend/quota.py` | New — `FREE_QUOTA`, `PAID_QUOTA`, `consume_llm_credit()` |
| `src/backend/agent/orchestrator.py` | Call `consume_llm_credit()` in `_classify_intent()` and `_handle_coaching()` |
| `src/backend/api/quota.py` | New router — `GET /quota` endpoint with auth dependency |
| `src/backend/main.py` | `app.include_router(quota.router)` and `app.include_router(billing.router)` |
| `src/backend/api/billing.py` | `POST /billing/upgrade` — pure UPDATE, 404 if not onboarded |

Notes:
- `src/backend/agent/graph.py` is **not** in this list — the meal-extraction guard is in `orchestrator.py:_handle_meal_logging`, not inside the graph.
- `src/backend/agent/coaching.py` is **not** in this list — the coaching guard is in `orchestrator.py:_handle_coaching`, not inside the agent.

### Double-credit on ambiguous turns (by design)

An ambiguous message (one that matches neither `_LOG_SIGNALS` nor `_QUERY_SIGNALS`) triggers the LLM intent classifier, consuming 1 credit. If the classifier returns `"log_meal"`, the extraction graph then consumes a second credit — **2 credits total for that turn**. This is intentional: the spec counts per LLM inference, not per user turn, and an ambiguous message genuinely requires two separate LLM calls.

User-facing copy should say "AI requests" (= LLM inferences) not "messages" to avoid confusion.
