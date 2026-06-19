# LLM Rate Limiting Design

**Date:** 2026-06-19  
**Status:** Approved  
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
| Postgres atomic counter | **Chosen** — single atomic `UPDATE…RETURNING` eliminates TOCTOU race, ACID guarantees the counter cannot be reset by infrastructure faults, and lifetime counters never justify a cache layer. |

---

## Quotas

| Tier | Limit |
|---|---|
| Free (new users) | 50 LLM inferences |
| Paid | 150 LLM inferences |

The limit is **per LLM inference**, not per user turn. A single user message can
trigger up to two LLM calls (intent classifier + main model), each consuming one
credit. The keyword pre-filter in `_classify_intent()` runs for free and never
consumes a credit.

The limit is a **lifetime cap** — it never resets. Upgrading bumps the cap from
50 → 150 without resetting the counter, so a free user who consumed 30 credits
has 120 remaining after upgrading.

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

A new module `src/backend/quota.py` exposes one function:

```python
async def consume_llm_credit(user_id: str) -> bool:
    """Atomically increment the LLM request counter if under quota.

    Returns True if a credit was consumed (caller may proceed with the LLM
    call). Returns False if the user is over quota (caller must degrade).

    The UPDATE is atomic — check and increment are one operation, eliminating
    any TOCTOU race under concurrent requests.
    """
```

The underlying query:

```sql
UPDATE user_goal
SET    llm_requests_used = llm_requests_used + 1
WHERE  user_id = $1
  AND  llm_requests_used < llm_quota
RETURNING llm_requests_used
```

Returns `True` if exactly one row was updated, `False` if zero rows matched
(user is at or over their quota).

---

## Hook Points in `orchestrator.py`

`consume_llm_credit()` is called **before each LLM inference site**:

1. **Intent classifier** — `_classify_intent()`, before `_intent_llm.ainvoke()`.
   Over-quota behaviour: skip the LLM, use keyword-only result. If no keyword
   matches, default to `"log_meal"`. No credit is consumed in this case.

2. **Coaching agent** — `CoachingAgent.handle()`, before the coaching LLM call.
   Over-quota behaviour: return static upgrade-prompt message.

3. **Meal-extraction graph** — inside `graph.py`, before the extraction LLM node.
   Over-quota behaviour: return static upgrade-prompt message via the standard
   `handle_message()` response shape (`status: "success"`, `paused: false`,
   `items: []`) so the frontend requires no special casing.

---

## Graceful Degrade Behaviour

| Site | Over-quota response |
|---|---|
| Intent classifier | Keyword-only routing; defaults to `log_meal` if ambiguous. Free — no credit consumed. |
| Coaching agent | `"You've used all your free AI requests. Upgrade to keep getting coaching insights."` |
| Meal-extraction graph | Same upgrade-prompt string, returned in the standard response envelope. |

The keyword pre-filter (`_LOG_SIGNALS` / `_QUERY_SIGNALS` checks on lines 54–60
of `orchestrator.py`) always runs before any LLM call and is never gated by the
quota. Users over-quota retain keyword-matched routing at zero cost.

---

## Upgrade Path

When a user pays, `billing.py` sets `llm_quota = 150` on the `user_goal` row.
`llm_requests_used` is left untouched. Counter never resets on upgrade.

The `tier` field on `GET /quota` is derived at read time:

```python
tier = "paid" if user_goal.llm_quota == 150 else "free"
```

No separate tier column needed.

---

## Quota Status API

New endpoint:

```
GET /quota
Authorization: Bearer <token>
```

Response:

```json
{
  "used": 34,
  "limit": 50,
  "tier": "free"
}
```

Used by the frontend to render a usage indicator. Reads directly from
`user_goal`; no cache.

---

## Security Properties

- **No TOCTOU race** — check and increment are one atomic DB operation.
- **ACID durability** — the counter survives Redis evictions, server restarts,
  and infrastructure faults.
- **No bypass via cache flush** — Postgres is the only store; there is no cache
  layer to clear.
- **Correct granularity** — checked per LLM inference, not per HTTP request,
  so concurrent calls within one user turn each consume a credit independently.

---

## Files Touched

| File | Change |
|---|---|
| `src/backend/db/models.py` | Add `llm_requests_used`, `llm_quota` to `UserGoal` |
| `src/backend/db/migrations/versions/*.py` | Alembic migration for the two columns |
| `src/backend/quota.py` | New — `consume_llm_credit()` |
| `src/backend/agent/orchestrator.py` | Call `consume_llm_credit()` before intent LLM |
| `src/backend/agent/coaching.py` | Call `consume_llm_credit()` before coaching LLM |
| `src/backend/agent/graph.py` | Call `consume_llm_credit()` before extraction node |
| `src/backend/api/quota.py` | New router — `GET /quota` endpoint |
| `src/backend/main.py` | Register the quota router |
| `src/backend/api/billing.py` | Set `llm_quota = 150` on upgrade |
