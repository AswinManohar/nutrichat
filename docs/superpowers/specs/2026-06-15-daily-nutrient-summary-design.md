# Daily Nutrient Summary vs RDA Baseline — Design Spec
**Date:** 2026-06-15
**Status:** Approved
**Scope:** Extend the existing 7-day Nutrient Check-up with RDA-baseline comparison, a
generated narrative summary, and three delivery surfaces (dashboard, Telegram, chat nudge)

---

## 1. Overview

`build_nutrient_checkup` already computes, nightly, a 7-day rolling average and
week-over-week trend for 8 nutrients (Protein, Fiber, Sugar, Vitamin C, Vitamin D, Iron,
Calcium, Vitamin B-12) per user (`agent/tools/history.py:get_nutrient_checkup_aggregates`,
`workers/tasks.py:_build_nutrient_checkup`).

This feature adds a second comparison — **against a generic adult RDA baseline** — and
turns the result into a short, plain-English summary that's surfaced in three places:

1. The web dashboard's existing "Weekly Nutrient Check-up" card.
2. A proactive Telegram message (only when something is notably off-target).
3. A one-time nudge in the web chat thread (only when something is notably off-target).

No new daily schedule is introduced — everything piggybacks on the existing 01:30
`build_nutrient_checkup` job, plus one new ~07:00 job for the Telegram push.

---

## 2. RDA baselines

New section in `config/tunables.yaml`, alongside the existing
`nutrient_checkup.micronutrients`:

```yaml
nutrient_checkup:
  # Generic adult daily values (FDA 2016 Daily Values where available).
  # Sugar has no official DV; we use 50g as a WHO "free sugars" proxy —
  # documented here because it's a judgment call, not a regulatory figure.
  rda:
    Protein: 50          # g
    Fiber: 28            # g
    Sugar: 50            # g (proxy, see comment above)
    "Vitamin C": 90       # mg
    "Vitamin D": 20       # mcg
    Iron: 18              # mg
    Calcium: 1300         # mg
    "Vitamin B-12": 2.4   # mcg
```

Loaded into `config/__init__.py`'s tunables model the same way
`nutrient_checkup.micronutrients` is today (a `dict[str, float]` keyed by display name —
the same keys already used in `_CHECKUP_MACROS` / `_CHECKUP_MICRONUTRIENTS`).

This is intentionally a single generic baseline for all users (no age/sex personalization)
— consistent with the project's existing "generic goals" approach to `UserGoal`.

---

## 3. Computation changes

### 3.1 `get_nutrient_checkup_aggregates` (`agent/tools/history.py`)

For each of the 8 nutrients, add:

```python
rda = _CHECKUP_RDA[display_name]
rda_pct = (cur_avg / rda) * 100 if rda else None
```

Result dict per nutrient becomes `{avg, prev_avg, unit, trend_pct, direction, rda_pct}`.

### 3.2 New helper: `summarize_nutrient_checkup(nutrients)` (`agent/tools/history.py`)

Pure function, no I/O — easy to unit test.

- A nutrient is **notable** if `rda_pct < 70` (under) or `rda_pct > 150` (over).
- Sort notable nutrients by how far they are from 100% (descending), take the top 2.
- Build a one-line template string from the top 1–2:
  - Single nutrient: `"This week, your {name} intake is at {rda_pct:.0f}% of the daily
    target — {phrase}."`
  - Two nutrients: `"This week: {name1} is at {pct1:.0f}% and {name2} is at {pct2:.0f}%
    of their daily targets — {phrase}."`
  - `phrase` is `"consider eating more {food hint}"` for under, `"you're well above the
    daily target"` for over. Food hints come from a small static
    `_NUTRIENT_FOOD_HINTS` dict (e.g. Fiber → "whole grains, legumes, or vegetables";
    Protein → "lean meat, eggs, beans, or dairy"). Over-target nutrients get no food
    hint, just the "well above" phrasing.
- Returns `(notable: list[dict], summary_text: str | None)` — `summary_text` is `None`
  when `notable` is empty.

### 3.3 `_build_nutrient_checkup` (`workers/tasks.py`)

After computing `nutrients` via `get_nutrient_checkup_aggregates`, call
`summarize_nutrient_checkup(nutrients)` and upsert two new columns:

```python
stmt = pg_insert(NutrientCheckup).values(
    user_id=user_id,
    date=target_date,
    nutrients=nutrients,
    notable_nutrients=notable,
    summary_text=summary_text,
)
```

### 3.4 Schema migration (`db/models.py` + alembic `..._005_nutrient_summary.py`)

Add to `NutrientCheckup`:
```python
notable_nutrients: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
telegram_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
chat_nudge_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```
`on_conflict_do_update` in `_build_nutrient_checkup` must also reset
`telegram_sent_at`/`chat_nudge_seen_at` to `NULL` when `notable_nutrients` is non-empty
and the row is being regenerated for a new day (i.e. only carry these forward via
`ON CONFLICT` when the date is unchanged — in practice each date gets one row, so a
fresh `date` always starts with `NULL`, no special-casing needed).

---

## 4. Dashboard (`api/nutrient_checkup.py`, `NutrientCheckupCard.tsx`)

- `NutrientCheckupResponse` (backend + `frontend/src/api/types.ts`) gains:
  ```typescript
  rda_pct: number | null   // on each NutrientCheckupItem
  notable: string[]        // nutrient names, on the response root
  summary_text: string | null  // on the response root
  ```
- `NutrientCheckupCard`: if `summary_text` is present, render it as a short intro
  paragraph above the nutrient rows (sage-deep text, `text-sm`).
- `NutrientBar`: add a second tick mark for the RDA target. The backend already sends
  `rda_pct = avg / rda * 100`, so the RDA amount in the same units is
  `rdaAmount = avg / (rda_pct / 100)` (skip the tick if `rda_pct` is `null` or `avg` is
  `0`). Extend the existing `max = Math.max(item.avg, item.prev_avg, rdaAmount)` and
  position the tick at `(rdaAmount / max) * 100`%. Style it distinctly from the "last
  week" tick (e.g. `bg-sage-deep/50` vs the existing `bg-ink-soft/50`), with
  `title="Daily recommended target"`.

---

## 5. Telegram push (`workers/tasks.py`, `telegram/`)

New Celery task `send_daily_summary_telegram`, scheduled at `crontab(hour=7, minute=0)`
(after the 01:30 build):

```python
async def _send_daily_summary_telegram(target_date: date) -> None:
    # SELECT nutrient_checkup JOIN telegram_link
    #   WHERE date = target_date AND summary_text IS NOT NULL
    #   AND telegram_sent_at IS NULL
    # for each row: bot.send_message(chat_id, summary_text); UPDATE telegram_sent_at = now()
```

Uses the same `Bot(TELEGRAM_BOT_TOKEN)` construction pattern as `telegram/bot.py`. One
bot instance per task run, closed at the end (`async with Bot(...) as bot:`).

---

## 6. Chat nudge (`api/nutrient_checkup.py`, `ChatPage.tsx`)

- `GET /nutrient-checkup/pending-nudge` → `{summary_text: string} | {summary_text: null}`.
  Looks up today's (or most recent) `nutrient_checkup` row for the user; returns
  `summary_text` only if `chat_nudge_seen_at IS NULL`.
- `POST /nutrient-checkup/pending-nudge/ack` → sets `chat_nudge_seen_at = now()`.
- New hook `usePendingNudge()` (TanStack Query, `staleTime: Infinity`, fetched once on
  mount).
- `ChatPage`: on mount, if `usePendingNudge()` returns a non-null `summary_text` **and**
  `conversationId` is `null` (no active paused thread), prepend it as the first agent
  message in the thread (via `addMessage`), then call the ack mutation.

---

## 7. Testing

- `tests/test_history.py` (or new `tests/test_nutrient_summary.py`):
  - `get_nutrient_checkup_aggregates` includes correct `rda_pct` for known inputs.
  - `summarize_nutrient_checkup`: under/over/flat thresholds, top-2 selection, `None`
    when nothing notable, single- vs two-nutrient template wording.
- `tests/test_tasks.py`: `_build_nutrient_checkup` persists `notable_nutrients` /
  `summary_text`; `_send_daily_summary_telegram` sends only to notable+unsent rows
  (mocked `Bot.send_message`), sets `telegram_sent_at`.
- `tests/test_api.py`: `/nutrient-checkup` includes new fields; pending-nudge
  get/ack round-trip.
- Frontend: type-check + lint; visual check of intro line + RDA tick via the existing
  Playwright flow.

---

## 8. Out of scope

- Personalized RDA (age/sex/weight-based DRI tables).
- LLM-generated narrative text (deterministic templates only).
- User-configurable notification thresholds or channel opt-outs (Telegram delivery is
  already implicitly opt-in via account linking).
- Daily summary for users with no `telegram_link` row (dashboard + chat nudge only).
