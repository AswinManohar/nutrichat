---
name: my-meals-safety-ux
description: Duplicate-log detection (backend logged_today flag) and inline delete confirmation for the My Meals page
metadata:
  type: project
---

# My Meals Safety UX

**Date:** 2026-06-30  
**Branch:** feat/coaching-telegram-estimation-deploy  
**Scope:** Two independent UX safety improvements to `MyMealsPage` — duplicate-log warning and delete confirmation.

---

## Problem

1. **Duplicate logging:** A user can tap Log on a saved meal they already logged earlier today with no warning. The backend accepts it silently, inflating their daily totals.
2. **Accidental delete:** The trash icon on a saved meal fires immediately with no confirmation step, making it easy to lose a saved meal by misclick.

---

## Feature 1 — Duplicate-log detection

### Approach

Backend Option A: add `logged_today: bool` to `MyMealSummary`. The `GET /my-meals` list endpoint computes this by checking whether the meal's name appears in today's `meal_log.label` values.

This is reliable because `log_my_meal` always sets `label = meal.name` (the saved meal's display name) when logging from My Meals. The match is case-sensitive equality on the stored string.

### Backend changes

**`src/backend/api/my_meals.py`**

- `MyMealSummary` Pydantic model gains `logged_today: bool = False`
- `list_meals` endpoint fetches today's logged labels in a single extra query before building the response:

```python
today_start, today_end = current_day_bounds()
result = await session.execute(
    select(MealLog.label)
    .where(
        MealLog.user_id == user_id,
        MealLog.logged_at >= today_start,
        MealLog.logged_at < today_end,
        MealLog.deleted_at.is_(None),
        MealLog.label.isnot(None),
    )
)
logged_labels: set[str] = {row.label for row in result.all()}
```

Then `_summary` gains a `logged_today` parameter:

```python
def _summary(meal: UserMeal, logged_today: bool = False) -> MyMealSummary:
    return MyMealSummary(..., logged_today=logged_today)
```

And `list_meals` passes it:

```python
return [_summary(m, logged_today=m.name in logged_labels) for m in rows]
```

The single `MealLog` query covers all meals in one round-trip; no N+1 issue.

### Frontend changes

**`frontend/src/api/types.ts`**

`MyMealSummary` gains:
```typescript
logged_today: boolean;
```

**`frontend/src/pages/MyMealsPage.tsx` — `MealRow`**

New local state:
- `showDuplicateWarning: boolean` — controls the inline popover
- `warningSuppressed: boolean` — set after first confirmed re-log; skips warning for the rest of the session

Logic on Log button click:
1. If `meal.logged_today && !warningSuppressed` → set `showDuplicateWarning = true` instead of opening the meal-type dropdown
2. Otherwise → open the meal-type dropdown as normal

**Inline popover** appears to the right of the Log button (absolutely positioned, `z-30`):

```
╔══════════════════════════════════════════╗
║ Already logged today — log again?        ║
║               [Log again]  [Cancel]      ║
╚══════════════════════════════════════════╝
```

- **Log again** → sets `warningSuppressed = true`, closes popover, opens meal-type dropdown
- **Cancel** → closes popover

The popover is a small `div` with the same `card-sand` styling and `rise-in` animation already used throughout the app.

---

## Feature 2 — Delete confirmation

### Approach

Inline two-step confirmation within the same trash button space. No modal. Clicking the trash transitions the button into a small inline prompt; user confirms or cancels within the row.

### Frontend changes

**`frontend/src/pages/MyMealsPage.tsx` — `MealRow`**

New local state:
- `confirmDelete: boolean`

When `confirmDelete` is false, render the trash icon button as today.

When `confirmDelete` is true, replace the trash button area with:

```
[Delete?]  [Yes]  [No]
```

- Label "Delete?" in `text-danger text-[12px]`
- **Yes** → calls `deleteMeal.mutate(meal.id)`, disabled while pending
- **No** → sets `confirmDelete = false`

No auto-dismiss timer; the user must explicitly confirm or cancel.

---

## What is NOT changing

- No new API endpoints
- No changes to the log flow, `LogMyMealRequest`, or confirmation card
- No changes to how `meal_log.label` is set (already correct)
- `GET /my-meals/{meal_id}` (detail endpoint) does not need `logged_today` — it is only used by the Customize editor
- No modal components added

---

## File touch list

| File | Change |
|---|---|
| `src/backend/api/my_meals.py` | Add `logged_today` to `MyMealSummary`; compute in `list_meals` |
| `src/backend/db/models.py` | Import `MealLog` if not already available in my_meals scope |
| `frontend/src/api/types.ts` | Add `logged_today: boolean` to `MyMealSummary` |
| `frontend/src/pages/MyMealsPage.tsx` | Duplicate warning popover + delete confirmation |

---

## Acceptance criteria

1. A saved meal logged earlier today shows the duplicate-log warning when the user taps Log.
2. Tapping "Log again" proceeds to the meal-type picker and logs successfully.
3. Tapping "Cancel" dismisses the warning with no side effects.
4. After confirming once, subsequent Log taps in the same session skip the warning.
5. A saved meal not logged today shows no warning — Log button opens the picker directly.
6. After an undo (meal log deleted), the `logged_today` flag resets on next page load/refetch.
7. Tapping the trash icon shows "Delete? Yes / No" inline; Yes deletes, No reverts to the trash icon.
8. Delete confirmation does not affect the Log button or any other part of the row.
