# My Meals Safety UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add persistent duplicate-log detection and an inline delete confirmation to the My Meals page.

**Architecture:** The backend `GET /my-meals` endpoint gains a single extra query that checks today's `meal_log.label` values; the result is surfaced as `logged_today: bool` on each `MyMealSummary`. The frontend reads this flag to conditionally show an inline popover before re-logging, and separately adds a two-step inline confirmation before deleting a saved meal.

**Tech Stack:** Python 3.12 · FastAPI · SQLAlchemy async · pytest · React 19 · TypeScript · Tailwind CSS

## Global Constraints

- Python max line length: 88 chars (Black default)
- All Python functions must have type annotations and `from __future__ import annotations`
- No wildcard imports
- TypeScript max line length: 100 chars
- Never use `any` in TypeScript — use `unknown` and narrow
- No new API endpoints; no new DB columns or migrations
- No modal components — all confirmations are inline within the row
- Follow existing `card-sand`, `rise-in`, `press` Tailwind class patterns for new UI elements
- Backend tests use `unittest.mock` with `AsyncMock`/`MagicMock` + FastAPI `TestClient`; no live DB

---

## File Map

| File | Role |
|---|---|
| `src/backend/api/my_meals.py` | Add `logged_today: bool` to `MyMealSummary`; compute via `MealLog` label query in `list_meals` |
| `tests/test_my_meals_api.py` | Extend with `logged_today` tests |
| `frontend/src/api/types.ts` | Add `logged_today: boolean` to `MyMealSummary` interface |
| `frontend/src/pages/MyMealsPage.tsx` | Add duplicate-log popover + delete confirmation to `MealRow` |

---

### Task 1: Backend — `logged_today` on `MyMealSummary`

**Files:**
- Modify: `src/backend/api/my_meals.py`
- Test: `tests/test_my_meals_api.py`

**Interfaces:**
- Produces: `MyMealSummary.logged_today: bool` on every item returned by `GET /my-meals`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_my_meals_api.py`:

```python
def _exec_returning_all(rows: list):
    """A mock execute() result whose .scalars().all() returns `rows`."""
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = rows
    result.scalars.return_value = scalars
    return result


def _exec_returning_rows(rows: list):
    """A mock execute() result whose .all() returns `rows` (non-scalar)."""
    result = MagicMock()
    result.all.return_value = rows
    return result


def test_list_meals_logged_today_true() -> None:
    """A saved meal whose name matches a today label gets logged_today=True."""
    app = _make_app()
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"
    client = TestClient(app)

    meal = MagicMock()
    meal.id = "meal-1"
    meal.name = "Chicken Biryani"
    meal.name_normalized = "chicken biryani"
    meal.kcal = 500.0
    meal.protein_g = 30.0
    meal.carbs_g = 60.0
    meal.fat_g = 10.0
    meal.fiber_g = 3.0
    meal.ingredients = ["ing1", "ing2"]
    meal.deleted_at = None

    session = MagicMock()
    # First call: list saved meals
    # Second call: today's logged labels
    label_row = MagicMock()
    label_row.label = "Chicken Biryani"
    session.execute = AsyncMock(
        side_effect=[
            _exec_returning_all([meal]),
            _exec_returning_rows([label_row]),
        ]
    )
    factory = _mock_session_factory(session)

    with patch("backend.api.my_meals.get_session", return_value=factory):
        resp = client.get("/my-meals")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["logged_today"] is True


def test_list_meals_logged_today_false() -> None:
    """A saved meal with no matching today label gets logged_today=False."""
    app = _make_app()
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"
    client = TestClient(app)

    meal = MagicMock()
    meal.id = "meal-2"
    meal.name = "Oat Porridge"
    meal.name_normalized = "oat porridge"
    meal.kcal = 300.0
    meal.protein_g = 10.0
    meal.carbs_g = 50.0
    meal.fat_g = 5.0
    meal.fiber_g = 6.0
    meal.ingredients = ["oats"]
    meal.deleted_at = None

    session = MagicMock()
    # Today's labels contain a different meal
    label_row = MagicMock()
    label_row.label = "Chicken Biryani"
    session.execute = AsyncMock(
        side_effect=[
            _exec_returning_all([meal]),
            _exec_returning_rows([label_row]),
        ]
    )
    factory = _mock_session_factory(session)

    with patch("backend.api.my_meals.get_session", return_value=factory):
        resp = client.get("/my-meals")

    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["logged_today"] is False


def test_list_meals_no_logs_today() -> None:
    """When no meals are logged today, all saved meals get logged_today=False."""
    app = _make_app()
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"
    client = TestClient(app)

    meal = MagicMock()
    meal.id = "meal-3"
    meal.name = "Salad"
    meal.name_normalized = "salad"
    meal.kcal = 150.0
    meal.protein_g = 5.0
    meal.carbs_g = 10.0
    meal.fat_g = 8.0
    meal.fiber_g = 4.0
    meal.ingredients = ["lettuce"]
    meal.deleted_at = None

    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=[
            _exec_returning_all([meal]),
            _exec_returning_rows([]),  # no labels today
        ]
    )
    factory = _mock_session_factory(session)

    with patch("backend.api.my_meals.get_session", return_value=factory):
        resp = client.get("/my-meals")

    assert resp.status_code == 200
    assert resp.json()[0]["logged_today"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/aswinmanohar/nutrichat
python -m pytest tests/test_my_meals_api.py::test_list_meals_logged_today_true tests/test_my_meals_api.py::test_list_meals_logged_today_false tests/test_my_meals_api.py::test_list_meals_no_logs_today -v
```

Expected: FAIL — `MyMealSummary` has no `logged_today` field, and `list_meals` doesn't query labels.

- [ ] **Step 3: Implement `logged_today` in the backend**

In `src/backend/api/my_meals.py`:

**3a.** Add `MealLog` to imports (it's in `backend.db.models`, already imported for `UserMeal`):

```python
from backend.db.models import MealLog, UserMeal
```

**3b.** Add `current_day_bounds` import from `backend.db.redis_client`:

```python
from backend.db.redis_client import current_day_bounds
```

**3c.** Add `logged_today` field to `MyMealSummary`:

```python
class MyMealSummary(BaseModel):
    id: str
    name: str
    kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float
    n_ingredients: int
    logged_today: bool = False

    model_config = ConfigDict(extra="forbid")
```

**3d.** Update `_summary` to accept and forward `logged_today`:

```python
def _summary(meal: UserMeal, logged_today: bool = False) -> MyMealSummary:
    return MyMealSummary(
        id=meal.id,
        name=meal.name,
        kcal=meal.kcal,
        protein_g=meal.protein_g,
        carbs_g=meal.carbs_g,
        fat_g=meal.fat_g,
        fiber_g=meal.fiber_g,
        n_ingredients=len(meal.ingredients),
        logged_today=logged_today,
    )
```

**3e.** Update `list_meals` to query today's labels and pass the flag:

```python
@router.get("")
async def list_meals(
    user_id: str = Depends(get_current_user_id),
) -> list[MyMealSummary]:
    async with get_session()() as session:
        stmt = (
            select(UserMeal)
            .where(UserMeal.user_id == user_id, UserMeal.deleted_at.is_(None))
            .order_by(UserMeal.created_at.desc())
        )
        rows = (await session.execute(stmt)).scalars().all()

        today_start, today_end = current_day_bounds()
        label_result = await session.execute(
            select(MealLog.label).where(
                MealLog.user_id == user_id,
                MealLog.logged_at >= today_start,
                MealLog.logged_at < today_end,
                MealLog.deleted_at.is_(None),
                MealLog.label.isnot(None),
            )
        )
        logged_labels: set[str] = {row.label for row in label_result.all()}

        return [_summary(m, logged_today=m.name in logged_labels) for m in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/aswinmanohar/nutrichat
python -m pytest tests/test_my_meals_api.py -v
```

Expected: All tests PASS, including the three new ones and all pre-existing tests.

- [ ] **Step 5: Commit**

```bash
git add src/backend/api/my_meals.py tests/test_my_meals_api.py
git commit -m "feat(my-meals): add logged_today flag to MyMealSummary list endpoint"
```

---

### Task 2: Frontend — `logged_today` type + delete confirmation

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/pages/MyMealsPage.tsx`

**Interfaces:**
- Consumes: `MyMealSummary.logged_today: bool` from Task 1
- Produces: `MyMealSummary.logged_today: boolean` in TypeScript; inline delete confirmation UI in `MealRow`

- [ ] **Step 1: Add `logged_today` to the TypeScript type**

In `frontend/src/api/types.ts`, update `MyMealSummary`:

```typescript
export interface MyMealSummary {
  id: string;
  name: string;
  kcal: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  fiber_g: number;
  n_ingredients: number;
  logged_today: boolean;
}
```

- [ ] **Step 2: Add delete confirmation to `MealRow`**

In `frontend/src/pages/MyMealsPage.tsx`, add `confirmDelete` state and replace the trash button section:

Add state near the top of `MealRow` (alongside `logMenuOpen`, `customizing`, `justLogged`):

```typescript
const [confirmDelete, setConfirmDelete] = useState(false)
```

Replace the existing trash button:

```typescript
{/* Delete button — two-step inline confirmation */}
{confirmDelete ? (
  <div className="flex items-center gap-1.5 shrink-0">
    <span className="text-[12px] text-danger font-medium">Delete?</span>
    <button
      type="button"
      onClick={() => deleteMeal.mutate(meal.id)}
      disabled={deleteMeal.isPending}
      className="press cursor-pointer px-2.5 py-1.5 rounded-full text-[12px] font-medium text-white bg-danger hover:bg-danger/90 disabled:opacity-50"
    >
      Yes
    </button>
    <button
      type="button"
      onClick={() => setConfirmDelete(false)}
      className="press cursor-pointer px-2.5 py-1.5 rounded-full text-[12px] font-medium text-ink border border-sand-border hover:bg-sand"
    >
      No
    </button>
  </div>
) : (
  <button
    type="button"
    onClick={() => setConfirmDelete(true)}
    disabled={deleteMeal.isPending}
    aria-label={`Delete ${meal.name}`}
    className="press cursor-pointer w-9 h-9 rounded-full flex items-center justify-center text-muted hover:text-danger hover:bg-container disabled:opacity-50"
  >
    <Trash2 className="w-4 h-4" strokeWidth={1.75} />
  </button>
)}
```

- [ ] **Step 3: Run TypeScript check**

```bash
cd /home/aswinmanohar/nutrichat/frontend
npx tsc --noEmit
```

Expected: No type errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/pages/MyMealsPage.tsx
git commit -m "feat(my-meals): inline delete confirmation on saved meal rows"
```

---

### Task 3: Frontend — Duplicate-log warning popover

**Files:**
- Modify: `frontend/src/pages/MyMealsPage.tsx`

**Interfaces:**
- Consumes: `meal.logged_today: boolean` from `MyMealSummary` (Task 1 + 2)
- Produces: Inline popover on `MealRow` when re-logging an already-logged meal

- [ ] **Step 1: Add duplicate-warning state and logic to `MealRow`**

Add two more state variables inside `MealRow` (alongside `confirmDelete` from Task 2):

```typescript
const [showDuplicateWarning, setShowDuplicateWarning] = useState(false)
const [warningSuppressed, setWarningSuppressed] = useState(false)
```

Update the Log button's `onClick` to intercept when `meal.logged_today` is true and the warning hasn't been suppressed yet:

```typescript
onClick={() => {
  setJustLogged(false)
  if (meal.logged_today && !warningSuppressed) {
    setShowDuplicateWarning(true)
  } else {
    setLogMenuOpen((o) => !o)
  }
}}
```

- [ ] **Step 2: Add the duplicate-warning popover**

Place the popover **inside** the `<div className="relative">` that wraps the Log button (immediately after the `{logMenuOpen && ...}` dropdown block):

```typescript
{showDuplicateWarning && (
  <div
    role="alertdialog"
    aria-label="Already logged today"
    className="absolute right-0 top-full mt-1.5 w-56 bg-paper border border-sand-border rounded-xl shadow-lg z-30 p-3 rise-in"
  >
    <p className="text-[12px] text-ink-soft mb-2.5">
      Already logged today — log again?
    </p>
    <div className="flex gap-2 justify-end">
      <button
        type="button"
        onClick={() => setShowDuplicateWarning(false)}
        className="press cursor-pointer px-2.5 py-1.5 rounded-full text-[12px] font-medium text-ink border border-sand-border hover:bg-sand"
      >
        Cancel
      </button>
      <button
        type="button"
        onClick={() => {
          setWarningSuppressed(true)
          setShowDuplicateWarning(false)
          setLogMenuOpen(true)
        }}
        className="press cursor-pointer px-2.5 py-1.5 rounded-full text-[12px] font-medium text-white bg-sage hover:bg-sage-deep"
      >
        Log again
      </button>
    </div>
  </div>
)}
```

- [ ] **Step 3: Run TypeScript check**

```bash
cd /home/aswinmanohar/nutrichat/frontend
npx tsc --noEmit
```

Expected: No type errors.

- [ ] **Step 4: Manual smoke test**

Start the dev server:

```bash
cd /home/aswinmanohar/nutrichat/frontend && npm run dev
```

Check in browser:
1. Navigate to My Meals page.
2. A meal that was already logged today should have no visible difference — Log button looks normal.
3. Click Log on an already-logged meal → popover appears with "Already logged today — log again?".
4. Click **Cancel** → popover dismisses, nothing logged.
5. Click Log again → popover reappears (not suppressed yet).
6. Click **Log again** → meal-type dropdown opens; pick a type → meal logs successfully.
7. Click Log once more on the same meal → dropdown opens immediately (warning suppressed for session).
8. A meal that was NOT logged today → Log button opens dropdown directly, no popover.
9. Trash icon → shows "Delete? Yes / No" inline. Yes deletes. No reverts to trash icon.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/MyMealsPage.tsx
git commit -m "feat(my-meals): show duplicate-log warning when meal already logged today"
```
