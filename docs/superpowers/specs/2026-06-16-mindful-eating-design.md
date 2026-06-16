# Mindful Eating Mode — Design Spec
**Date:** 2026-06-16
**Status:** Approved
**Scope:** A second tracking mode where users log everything but see only absolute
amounts consumed — no targets, no rings — plus proactive safety alerts when intake
exceeds Tolerable Upper Intake Levels (UL) from NASEM/WHO/FDA.

---

## 1. Overview

NutriChat currently assumes every user has explicit daily targets (kcal, protein, fiber).
Mindful Eating is a goal-free mode: users still log meals and receive full macro + micro
nutrient data, but the UI shows only what was consumed (no "X% of goal", no rings, no
progress bars). The agent drops all goal-framing language.

Critically, the mode does **not** mean ignoring safety. When a user's daily intake
approaches or exceeds a research-backed Tolerable Upper Intake Level (UL), a cited
safety alert fires: the alert names the nutrient, the intake, the limit, and links
to the authoritative source (NASEM DRI, WHO, or FDA).

---

## 2. Entry Points

| Surface | Behaviour |
|---|---|
| **Onboarding** | New "mode choice" screen before the existing Step 1 (goals). "Set goals" leads to the current flow; "Mindful eating" skips goal steps, keeps dietary-prefs step, creates a `UserGoal` row with `tracking_mode='mindful'` and null targets. |
| **Settings page** | Toggle between modes. Switching to goal mode requires setting goals (redirect to goal-creation flow). Switching back to mindful clears targets, keeps logged data. |

---

## 3. Data Model

### 3.1 `user_goal` table (migration `006_mindful_eating.sql`)

Add one nullable column and make the three goal columns nullable:

```sql
ALTER TABLE user_goal
  ADD COLUMN tracking_mode TEXT NOT NULL DEFAULT 'goals',
  ALTER COLUMN kcal_goal    DROP NOT NULL,
  ALTER COLUMN protein_goal DROP NOT NULL,
  ALTER COLUMN fiber_goal   DROP NOT NULL;

ALTER TABLE user_goal
  ADD CONSTRAINT user_goal_tracking_mode_check
  CHECK (tracking_mode IN ('goals', 'mindful'));
```

A mindful user row: `tracking_mode='mindful'`, all three goal columns `NULL`.
A goal-mode user row: `tracking_mode='goals'`, all three goal columns set.

### 3.2 Backend Pydantic models

`GoalCreate` and `GoalUpdate` make `kcal_goal / protein_goal / fiber_goal` optional
when `tracking_mode='mindful'`. A `GoalSummary` gains `tracking_mode: str`.
`build_system_prompt()` in `context.py` skips the "Goals: X kcal…" line when
`tracking_mode='mindful'`.

---

## 4. Safety Limits

### 4.1 `tunables.yaml` — new `upper_limits:` block

```yaml
upper_limits:
  Sodium:
    usda_name: "Sodium, Na"
    unit: mg
    ul: 2300
    source: "WHO — Sodium intake for adults (2012)"
    url: "https://www.who.int/publications/i/item/9789241504836"
  "Total Sugars":
    usda_name: "Total Sugars"
    unit: g
    ul: 50
    source: "WHO — Sugars intake for adults and children (2015)"
    url: "https://www.who.int/publications/i/item/9789241549028"
  "Saturated Fat":
    usda_name: "Fatty acids, total saturated"
    unit: g
    ul: 22          # FDA: <10% of 2200 kcal diet
    source: "FDA Dietary Guidelines for Americans 2020-2025"
    url: "https://www.dietaryguidelines.gov"
  "Vitamin A":
    usda_name: "Vitamin A, RAE"
    unit: mcg
    ul: 3000
    source: "NASEM DRI — Vitamin A (2001)"
    url: "https://www.ncbi.nlm.nih.gov/books/NBK222318/"
  "Vitamin D":
    usda_name: "Vitamin D (D2 + D3)"
    unit: mcg
    ul: 100
    source: "NASEM DRI — Vitamin D (2011)"
    url: "https://www.ncbi.nlm.nih.gov/books/NBK56070/"
  Iron:
    usda_name: "Iron, Fe"
    unit: mg
    ul: 45
    source: "NASEM DRI — Iron (2001)"
    url: "https://www.ncbi.nlm.nih.gov/books/NBK222309/"
  Zinc:
    usda_name: "Zinc, Zn"
    unit: mg
    ul: 40
    source: "NASEM DRI — Zinc (2001)"
    url: "https://www.ncbi.nlm.nih.gov/books/NBK222317/"
  Niacin:
    usda_name: "Niacin"
    unit: mg
    ul: 35
    source: "NASEM DRI — Niacin (1998)"
    url: "https://www.ncbi.nlm.nih.gov/books/NBK114304/"
  Calcium:
    usda_name: "Calcium, Ca"
    unit: mg
    ul: 2500
    source: "NASEM DRI — Calcium (2011)"
    url: "https://www.ncbi.nlm.nih.gov/books/NBK56070/"
```

All values are conservative adult defaults. The `ul` field is the only numeric
threshold — no tolerance band, no age stratification in V1.

### 4.2 Typed loader

`backend/config/tunables.py` gains `UpperLimitEntry` and `UpperLimitsConfig`
Pydantic models; `get_tunables()` returns `tunables.upper_limits` as a
`dict[str, UpperLimitEntry]`. No raw dict access.

---

## 5. Backend Services

### 5.1 `backend/agent/tools/mindful.py` (new file)

Two public async functions:

**`get_daily_intake(user_id: str, date: date) -> list[NutrientAmount]`**
- Computes bounds for the given date using `current_day_bounds()` (respects the 01:00 Oslo rollover).
- Sums macro columns from `meal_log` (kcal, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sat_fat_g).
- Calls `get_micronutrients_for_range()` for every `usda_name` in `upper_limits` + the existing `micronutrients` block.
- Returns `list[NutrientAmount]` (name, amount, unit). LLM-estimated items contribute macros but not micros (already the behaviour of `get_micronutrients_for_range`).

**`evaluate_safety(intake: list[NutrientAmount]) -> list[SafetyAlert]`**
- Loads `upper_limits` from tunables.
- For each limit, if the corresponding intake amount ≥ UL, emits a `SafetyAlert` (nutrient, amount, limit, unit, source, url).
- Returns empty list when no limit is exceeded.

Pydantic models:
```python
class NutrientAmount(BaseModel):
    name: str
    amount: float
    unit: str

class SafetyAlert(BaseModel):
    nutrient: str
    amount: float
    limit: float
    unit: str
    source: str
    url: str
```

### 5.2 `GET /mindful/today` endpoint (`backend/api/mindful.py`)

Auth-required. Returns:
```json
{
  "tracking_mode": "mindful",
  "date": "2026-06-16",
  "nutrients": [
    { "name": "Energy", "amount": 1840.0, "unit": "kcal" },
    { "name": "Protein", "amount": 72.3, "unit": "g" },
    ...
  ],
  "alerts": [
    {
      "nutrient": "Total Sugars",
      "amount": 58.2,
      "limit": 50.0,
      "unit": "g",
      "source": "WHO — Sugars intake for adults and children (2015)",
      "url": "https://www.who.int/..."
    }
  ]
}
```

Goal-mode users may call this endpoint too (it returns their intake and any safety
breaches); the frontend only routes mindful users to the mindful dashboard view.

### 5.3 Goals API changes (`backend/api/goals.py`)

- `GoalCreate`: `tracking_mode: Literal['goals', 'mindful'] = 'goals'`; `kcal_goal`, `protein_goal`, `fiber_goal` become `Optional[float]`; validation raises 422 if `tracking_mode='goals'` and any target is missing.
- `GoalUpdate`: same optional pattern.
- `GET /goals` response includes `tracking_mode`.

---

## 6. Agent Context

`GoalSummary` in `context.py` gains `tracking_mode: str`. In `build_system_prompt()`:

```python
if ctx.goals and ctx.goals.tracking_mode == 'goals':
    lines.append(f"Goals: {ctx.goals.kcal_goal} kcal ...")
elif ctx.goals and ctx.goals.tracking_mode == 'mindful':
    # Pass safety alerts to coaching context instead
    if ctx.goals.active_alerts:
        lines.append(f"Safety alerts: {_fmt_alerts(ctx.goals.active_alerts)}")
```

`build_context()` fetches active safety alerts for mindful users by calling
`evaluate_safety(await get_daily_intake(user_id, today))` and attaches them to
`GoalSummary.active_alerts: list[SafetyAlert]`.

The coaching prompt (`coaching_response_system` in `tunables.yaml`) already has a
refusals clause; mindful-mode safety alerts are informational, not clinical — the
agent can mention them using the provided source text (e.g. "Your sugar intake today
(58g) exceeds the WHO recommended limit of 50g/day for free sugars — see [source].").

---

## 7. Frontend

### 7.1 Onboarding (`OnboardingPage.tsx`)

New **Step 0** before the existing steps: a two-card choice screen.

- **"Set goals"** card: brief copy ("I want daily targets for calories, protein & fiber"). → proceeds to Step 1 (TDEE flow).
- **"Mindful eating"** card: brief copy ("I want to track what I eat with no targets"). → skips to dietary-prefs step, then submits `{ tracking_mode: 'mindful' }` with null goals.

Styling: same card style as the existing step cards; no new design primitives needed.

### 7.2 Settings page (`SettingsPage.tsx`)

New "Tracking mode" section with a toggle:
- Current mode label.
- "Switch to Mindful Eating" / "Switch to Goal Tracking" button.
- Switching TO goal tracking opens a goal-setting modal (same form as onboarding Step 1).
- Switching TO mindful: PATCH `/goals` with `{ tracking_mode: 'mindful' }`, clear local targets.

### 7.3 Dashboard (`Dashboard.tsx` / `MacroRings.tsx`)

When `tracking_mode === 'mindful'`:
- Replace `MacroRings` with a **`MindfulPanel`** component.
- `MindfulPanel` calls `GET /mindful/today`, renders a plain list of nutrients + amounts (no rings, no %, no targets).
- If `alerts` is non-empty, render **`SafetyAlertCard`** components below the list: amber/red banner, nutrient name, intake vs limit, clickable source link.

When `tracking_mode === 'goals'`: existing `MacroRings` unchanged.

New components: `MindfulPanel`, `SafetyAlertCard`. Both live in
`frontend/src/components/dashboard/`.

New hook: `useMindfulToday(userId)` — TanStack Query against `GET /mindful/today`,
`staleTime: 30_000` (same as `useTodayTotals`).

---

## 8. Testing

| Layer | Tests |
|---|---|
| `mindful.py` unit | `get_daily_intake` aggregates macros + micros correctly; `evaluate_safety` returns alert for intake ≥ UL, empty list for intake < UL, alert includes correct citation URL |
| API | `GET /mindful/today` 200 for authed user, 401 without auth |
| Goals API | mindful create succeeds with null targets; goal create fails (422) if mode=goals and target missing |
| Migration | `tracking_mode` defaults to `'goals'`; existing rows unaffected |
| Frontend | TS type-check + lint; `MindfulPanel` renders nutrients; `SafetyAlertCard` renders alert with link |

---

## 9. Out of Scope (V1)

- Deficiency alerts (lower-bound thresholds) — only overconsumption (UL) in V1.
- Age/sex-stratified UL values — single adult default.
- Push notifications for alerts — surfaced only on dashboard and via agent context.
- Chronic trend alerts (e.g. "Sugar exceeded UL 5 days this week") — single-day check only.

---

## 10. File Map

| File | Change |
|---|---|
| `src/backend/db/migrations/006_mindful_eating.sql` | New migration |
| `src/backend/config/tunables.yaml` | Add `upper_limits:` block |
| `src/backend/config/tunables.py` | `UpperLimitEntry`, `UpperLimitsConfig` models |
| `src/backend/agent/tools/mindful.py` | New: `get_daily_intake`, `evaluate_safety` |
| `src/backend/api/mindful.py` | New: `GET /mindful/today` router |
| `src/backend/api/goals.py` | `tracking_mode` field, optional targets |
| `src/backend/agent/context.py` | `GoalSummary.tracking_mode`, mindful system-prompt block |
| `src/backend/main.py` | Register mindful router |
| `frontend/src/api/mindful.ts` | `getMindfulToday()`, `useMindfulToday()` hook |
| `frontend/src/types/mindful.ts` | `NutrientAmount`, `SafetyAlert`, `MindfulDay` types |
| `frontend/src/components/dashboard/MindfulPanel.tsx` | New component |
| `frontend/src/components/dashboard/SafetyAlertCard.tsx` | New component |
| `frontend/src/pages/Dashboard.tsx` | Conditional `MindfulPanel` vs `MacroRings` |
| `frontend/src/pages/OnboardingPage.tsx` | Step 0: mode-choice screen |
| `frontend/src/pages/SettingsPage.tsx` | Tracking-mode toggle |
| `tests/test_mindful.py` | Unit tests for intake aggregation + safety eval |
| `tests/test_mindful_api.py` | API tests |
| `tests/test_goals_api.py` | Mindful-mode create/update tests |
