# LLM Rate Limiting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce a lifetime per-user LLM inference quota (free: 50, paid: 150) with graceful degrade when exhausted, using a Postgres atomic upsert as the single source of truth.

**Architecture:** A new `quota.py` module exposes `consume_llm_credit(user_id)` which atomically increments a counter in `user_goal` and returns `False` when the user is over quota. Three call sites in `orchestrator.py` call this guard before each LLM inference; over-quota requests degrade to keyword-only routing or a static upgrade message. A `GET /quota` endpoint surfaces the counter state for the frontend.

**Tech Stack:** FastAPI · SQLAlchemy (async) · Alembic · PostgreSQL · Logfire · pytest

## Global Constraints

- All new Python files must start with `from __future__ import annotations`
- All functions must have full type annotations
- Max line length 88 characters (Black default)
- `FREE_QUOTA = 50` and `PAID_QUOTA = 150` are the only definition of quota values — never hard-code 50 or 150 anywhere else
- All async I/O must use `async/await`; never call blocking functions from async code
- Use `Depends(get_current_user_id)` from `backend.auth.supabase` for all protected endpoints
- Follow existing migration naming: `YYYYMMDD_NNN_description.py`, revision IDs as `"009"`, `down_revision = "008"`
- Commit after every task; use `git add <specific files>` never `git add .`

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `src/backend/db/models.py` | Modify | Add `llm_requests_used`, `llm_quota` columns to `UserGoal` |
| `src/backend/db/migrations/versions/20260621_009_llm_quota.py` | Create | Alembic migration for the two new columns |
| `src/backend/quota.py` | Create | `FREE_QUOTA`, `PAID_QUOTA`, `consume_llm_credit()` |
| `src/backend/agent/orchestrator.py` | Modify | Hook quota guard at intent classifier, coaching, and meal-logging sites |
| `src/backend/api/quota.py` | Create | `GET /quota` endpoint |
| `src/backend/main.py` | Modify | Register quota router |
| `src/backend/api/billing.py` | Modify | `POST /billing/upgrade` sets `llm_quota = PAID_QUOTA` |
| `tests/test_quota.py` | Create | Unit tests for `consume_llm_credit()` |
| `tests/test_quota_api.py` | Create | API tests for `GET /quota` |
| `tests/test_orchestrator_quota.py` | Create | Orchestrator quota degrade tests |

---

## Task 1: Data Model + Alembic Migration

**Files:**
- Modify: `src/backend/db/models.py`
- Create: `src/backend/db/migrations/versions/20260621_009_llm_quota.py`

**Interfaces:**
- Produces: `UserGoal.llm_requests_used: int`, `UserGoal.llm_quota: int` — used by Task 2 and Task 4

---

- [ ] **Step 1: Add columns to `UserGoal` in `models.py`**

Open `src/backend/db/models.py`. In the `UserGoal` class, add these two mapped columns after `streak_days`:

```python
llm_requests_used: Mapped[int] = mapped_column(
    Integer, nullable=False, default=0, server_default="0"
)
llm_quota: Mapped[int] = mapped_column(
    Integer, nullable=False, default=50, server_default="50"
)
```

The full `UserGoal` class definition should now end with:

```python
    streak_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    llm_requests_used: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    llm_quota: Mapped[int] = mapped_column(
        Integer, nullable=False, default=50, server_default="50"
    )
    created_at: Mapped[datetime] = mapped_column(...)
    updated_at: Mapped[datetime] = mapped_column(...)
```

- [ ] **Step 2: Write the Alembic migration**

Create `src/backend/db/migrations/versions/20260621_009_llm_quota.py`:

```python
"""user_goal — llm_requests_used and llm_quota columns for per-user LLM quota.

Free tier default 50, paid tier set to 150 by billing on upgrade.
Existing rows receive 0 / 50 via server defaults — no backfill required.

Revision ID: 009
Revises: 008
Create Date: 2026-06-21
"""

from __future__ import annotations

from alembic import op

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE user_goal "
        "ADD COLUMN IF NOT EXISTS llm_requests_used INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE user_goal "
        "ADD COLUMN IF NOT EXISTS llm_quota INTEGER NOT NULL DEFAULT 50"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE user_goal DROP COLUMN IF EXISTS llm_quota")
    op.execute("ALTER TABLE user_goal DROP COLUMN IF EXISTS llm_requests_used")
```

- [ ] **Step 3: Run the migration**

```bash
cd /home/aswinmanohar/nutrichat
alembic upgrade head
```

Expected output ends with:
```
INFO  [alembic.runtime.migration] Running upgrade 008 -> 009, user_goal — llm_requests_used and llm_quota columns
```

- [ ] **Step 4: Verify columns exist**

```bash
python -c "
import asyncio, os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

async def check():
    engine = create_async_engine(os.environ['DATABASE_URL'])
    async with engine.connect() as conn:
        r = await conn.execute(text(
            \"SELECT column_name FROM information_schema.columns \"
            \"WHERE table_name = 'user_goal' AND column_name IN \"
            \"('llm_requests_used', 'llm_quota') ORDER BY column_name\"
        ))
        print([row[0] for row in r.fetchall()])

asyncio.run(check())
"
```

Expected: `['llm_quota', 'llm_requests_used']`

- [ ] **Step 5: Commit**

```bash
git add src/backend/db/models.py \
        src/backend/db/migrations/versions/20260621_009_llm_quota.py
git commit -m "feat(quota): add llm_requests_used + llm_quota columns to user_goal"
```

---

## Task 2: Quota Guard Module

**Files:**
- Create: `src/backend/quota.py`
- Create: `tests/test_quota.py`

**Interfaces:**
- Consumes: `UserGoal.llm_requests_used`, `UserGoal.llm_quota` (from Task 1), `get_session()` from `backend.db.session`
- Produces:
  - `FREE_QUOTA: int = 50`
  - `PAID_QUOTA: int = 150`
  - `async def consume_llm_credit(user_id: str) -> bool`

---

- [ ] **Step 1: Write the failing tests**

Create `tests/test_quota.py`:

```python
"""Unit tests for quota.consume_llm_credit()."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.quota import FREE_QUOTA, PAID_QUOTA, consume_llm_credit


def _make_session(row=None):
    """Return a mock async session whose execute() returns `row` or nothing."""
    result = MagicMock()
    result.fetchone.return_value = row
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=session)


@pytest.mark.asyncio
async def test_consume_credit_granted_when_under_quota():
    """Returns True and calls commit when a row is returned (credit granted)."""
    factory = _make_session(row=(1,))  # row = (llm_requests_used,)
    with patch("backend.quota.get_session", return_value=factory):
        result = await consume_llm_credit("user-abc")
    assert result is True


@pytest.mark.asyncio
async def test_consume_credit_denied_when_over_quota():
    """Returns False when no row returned (WHERE clause failed — at quota)."""
    factory = _make_session(row=None)
    with patch("backend.quota.get_session", return_value=factory):
        result = await consume_llm_credit("user-abc")
    assert result is False


@pytest.mark.asyncio
async def test_consume_credit_new_user_upsert_grants_credit():
    """Missing user_goal row is created by upsert and credit is granted."""
    # row=(1,) simulates a successful INSERT (new row, first credit consumed)
    factory = _make_session(row=(1,))
    with patch("backend.quota.get_session", return_value=factory):
        result = await consume_llm_credit("brand-new-user")
    assert result is True


def test_quota_constants():
    assert FREE_QUOTA == 50
    assert PAID_QUOTA == 150
```

- [ ] **Step 2: Run to confirm tests fail**

```bash
cd /home/aswinmanohar/nutrichat
python -m pytest tests/test_quota.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'backend.quota'`

- [ ] **Step 3: Implement `src/backend/quota.py`**

```python
from __future__ import annotations

import logfire
from sqlalchemy import text

from backend.db.session import get_session

FREE_QUOTA: int = 50
PAID_QUOTA: int = 150

_UPSERT_SQL = text("""
    INSERT INTO user_goal (user_id, llm_requests_used, llm_quota)
    VALUES (:user_id, 1, :free_quota)
    ON CONFLICT (user_id) DO UPDATE
      SET llm_requests_used = user_goal.llm_requests_used + 1
      WHERE user_goal.llm_requests_used < user_goal.llm_quota
    RETURNING llm_requests_used
""")


async def consume_llm_credit(user_id: str) -> bool:
    """Atomically increment the LLM request counter if under quota.

    Uses an upsert so new users without a user_goal row are initialised
    with FREE_QUOTA. Returns True if a credit was consumed (caller may
    proceed with the LLM call). Returns False if the user is at or over
    quota (caller must degrade gracefully).

    Args:
        user_id: Supabase Auth UUID.

    Returns:
        True if a credit was consumed, False if the user is over quota.
    """
    session_factory = get_session()
    async with session_factory() as session:
        result = await session.execute(_UPSERT_SQL, {"user_id": user_id, "free_quota": FREE_QUOTA})
        await session.commit()
        row = result.fetchone()

    granted = row is not None
    if granted:
        logfire.info("quota_credit_consumed", user_id=user_id, used=row[0])
    else:
        logfire.info("quota_exhausted", user_id=user_id)
    return granted
```

- [ ] **Step 4: Run tests and confirm they pass**

```bash
python -m pytest tests/test_quota.py -v
```

Expected:
```
tests/test_quota.py::test_consume_credit_granted_when_under_quota PASSED
tests/test_quota.py::test_consume_credit_denied_when_over_quota PASSED
tests/test_quota.py::test_consume_credit_new_user_upsert_grants_credit PASSED
tests/test_quota.py::test_quota_constants PASSED
4 passed
```

- [ ] **Step 5: Commit**

```bash
git add src/backend/quota.py tests/test_quota.py
git commit -m "feat(quota): add consume_llm_credit() with atomic upsert"
```

---

## Task 3: Orchestrator Hooks

**Files:**
- Modify: `src/backend/agent/orchestrator.py`
- Create: `tests/test_orchestrator_quota.py`

**Interfaces:**
- Consumes: `consume_llm_credit(user_id: str) -> bool` from `backend.quota` (Task 2)
- Consumes: `_classify_intent(message: str, user_id: str) -> str` — signature change (adds `user_id`)
- Produces: over-quota `handle_message()` returns `{"status": "success", "message": "<upgrade text>", "paused": False, "items": []}`

**Upgrade message strings (used verbatim in code and tests):**
- Web/default: `"You've used all your free AI requests. Visit nutrichat.app/upgrade to continue."`

---

- [ ] **Step 1: Write failing tests**

Create `tests/test_orchestrator_quota.py`:

```python
"""Tests for quota degrade paths in orchestrator.handle_message()."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_UPGRADE_MSG = "You've used all your free AI requests. Visit nutrichat.app/upgrade to continue."


@pytest.mark.asyncio
async def test_coaching_over_quota_returns_upgrade_message():
    """When over quota, coaching turn returns upgrade message without calling LLM."""
    from backend.agent.orchestrator import _handle_coaching

    with patch("backend.agent.orchestrator.consume_llm_credit", new=AsyncMock(return_value=False)):
        result = await _handle_coaching("user-1", "how much protein today?")

    assert result["status"] == "success"
    assert result["message"] == _UPGRADE_MSG
    assert result["paused"] is False
    assert result["items"] == []


@pytest.mark.asyncio
async def test_coaching_under_quota_calls_agent():
    """When under quota, coaching turn delegates to the coaching agent."""
    from backend.agent.orchestrator import _handle_coaching

    mock_agent = AsyncMock(return_value="You had 120g protein today.")
    with (
        patch("backend.agent.orchestrator.consume_llm_credit", new=AsyncMock(return_value=True)),
        patch("backend.agent.orchestrator._coaching_agent") as mock_coaching,
    ):
        mock_coaching.handle = mock_agent
        result = await _handle_coaching("user-1", "how much protein today?")

    assert result["message"] == "You had 120g protein today."


@pytest.mark.asyncio
async def test_classify_intent_over_quota_defaults_to_log_meal():
    """When over quota and no keyword match, intent defaults to log_meal."""
    from backend.agent.orchestrator import _classify_intent

    with patch("backend.agent.orchestrator.consume_llm_credit", new=AsyncMock(return_value=False)):
        # "blah" has no keyword match, so LLM would normally be called
        intent = await _classify_intent("blah blah", "user-1")

    assert intent == "log_meal"


@pytest.mark.asyncio
async def test_classify_intent_keyword_match_skips_quota():
    """Keyword-matched intent never touches the quota guard."""
    from backend.agent.orchestrator import _classify_intent

    mock_credit = AsyncMock(return_value=False)
    with patch("backend.agent.orchestrator.consume_llm_credit", new=mock_credit):
        intent = await _classify_intent("I ate rice", "user-1")  # "ate" is a log signal

    mock_credit.assert_not_called()
    assert intent == "log_meal"


@pytest.mark.asyncio
async def test_meal_logging_over_quota_returns_upgrade_message():
    """Fresh meal-logging turn over quota returns upgrade message without invoking graph."""
    from backend.agent.orchestrator import _handle_meal_logging

    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock()

    with patch("backend.agent.orchestrator.consume_llm_credit", new=AsyncMock(return_value=False)):
        result = await _handle_meal_logging(
            graph=mock_graph,
            config={"configurable": {"thread_id": "t1", "user_id": "user-1"}},
            user_input="I had rice",
            user_id="user-1",
            image_b64=None,
            is_paused=False,
        )

    mock_graph.ainvoke.assert_not_called()
    assert result["status"] == "success"
    assert result["message"] == _UPGRADE_MSG
    assert result["paused"] is False


@pytest.mark.asyncio
async def test_meal_logging_paused_resume_skips_quota():
    """Paused graph resume (correct/decompose path) never calls consume_llm_credit."""
    from backend.agent.orchestrator import _handle_meal_logging

    mock_state = MagicMock()
    mock_state.next = []  # not still paused after resume
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value={"messages": [], "usda_results": []})
    mock_graph.aget_state = AsyncMock(return_value=mock_state)
    mock_graph.aupdate_state = AsyncMock()

    mock_credit = AsyncMock(return_value=False)
    with patch("backend.agent.orchestrator.consume_llm_credit", new=mock_credit):
        await _handle_meal_logging(
            graph=mock_graph,
            config={"configurable": {"thread_id": "t1", "user_id": "user-1"}},
            user_input="yes confirm",
            user_id="user-1",
            image_b64=None,
            is_paused=True,
        )

    mock_credit.assert_not_called()
```

- [ ] **Step 2: Run to confirm tests fail**

```bash
python -m pytest tests/test_orchestrator_quota.py -v 2>&1 | head -30
```

Expected: `ImportError` or attribute errors — `consume_llm_credit` not yet imported in orchestrator.

- [ ] **Step 3: Modify `orchestrator.py`**

Add the import at the top of the existing import block in `orchestrator.py`:

```python
from backend.quota import consume_llm_credit
```

Replace `_classify_intent` with the version that adds `user_id` and the quota check:

```python
async def _classify_intent(message: str, user_id: str) -> str:
    """Classify a fresh user message as log_meal or coaching.

    Two-stage: keyword pre-filter (zero LLM cost and zero quota), LLM
    fallback when ambiguous. When over quota, skips the LLM and defaults
    to log_meal.

    Args:
        message: Raw user message.
        user_id: Supabase Auth UUID — used for quota check.

    Returns:
        "log_meal" or "coaching".
    """
    lowered = message.lower()
    has_log = any(sig in lowered for sig in _LOG_SIGNALS)
    has_query = any(sig in lowered for sig in _QUERY_SIGNALS)

    if has_query:
        return "coaching"
    if has_log:
        return "log_meal"

    granted = await consume_llm_credit(user_id)
    if not granted:
        return "log_meal"

    with logfire.span("classify_intent_llm"):
        result = await _intent_llm.ainvoke(
            [
                SystemMessage(content=_INTENT_SYSTEM),
                HumanMessage(content=message),
            ]
        )
    return result.type
```

Update the call site in `handle_message()` — change:
```python
and await _classify_intent(user_input) == "coaching"
```
to:
```python
and await _classify_intent(user_input, user_id) == "coaching"
```

Replace `_handle_coaching` with the quota-gated version:

```python
async def _handle_coaching(user_id: str, user_input: str) -> dict[str, Any]:
    """Answer a nutrition question via the coaching agent.

    Consumes one quota credit per coaching turn (not per internal LLM call).
    Returns an upgrade prompt when over quota.

    Args:
        user_id: Supabase Auth UUID.
        user_input: User's nutrition question.

    Returns:
        Dict with status, message, paused=False, and items=[].
    """
    granted = await consume_llm_credit(user_id)
    if not granted:
        return {
            "status": "success",
            "message": (
                "You've used all your free AI requests. "
                "Visit nutrichat.app/upgrade to continue."
            ),
            "paused": False,
            "items": [],
        }
    with logfire.span("coaching"):
        message = await _coaching_agent.handle(user_id, user_input)
    return {"status": "success", "message": message, "paused": False, "items": []}
```

In `_handle_meal_logging`, add the quota check for fresh (non-paused) turns. Insert right before the `else:` branch that calls `graph.ainvoke`:

```python
async def _handle_meal_logging(
    graph: Any,
    config: dict[str, Any],
    user_input: str,
    user_id: str,
    image_b64: str | None,
    is_paused: bool,
    meal_type: str | None = None,
    action: str | None = None,
) -> dict[str, Any]:
    """Run (or resume) the meal-logging graph and shape its response.

    For fresh (non-paused) turns, consumes one quota credit before invoking
    the extraction LLM. Paused-graph resumes (correct/decompose/confirm) are
    exempt — those paths only call apply_correction or decompose_to_ingredients,
    which are explicitly excluded from the quota.

    Args:
        graph: Compiled LangGraph StateGraph.
        config: LangGraph config with thread_id and user_id.
        user_input: Raw text from the user.
        user_id: Supabase Auth UUID.
        image_b64: Optional base64-encoded image string.
        is_paused: Whether the graph was paused at the confirmation interrupt.
        meal_type: User-picked meal category, injected into state on resume.
        action: Card action ("decompose", "combine", or None).

    Returns:
        Dict with status, message, paused, and items.
    """
    _UPGRADE_MSG = (
        "You've used all your free AI requests. "
        "Visit nutrichat.app/upgrade to continue."
    )
    with logfire.span("meal_logging"):
        if is_paused:
            update: dict[str, Any] = {
                "messages": [HumanMessage(content=user_input)],
                "action": action,
            }
            if meal_type is not None:
                update["meal_type"] = meal_type
            await graph.aupdate_state(config, update)
            result = await graph.ainvoke(None, config=config)
        else:
            granted = await consume_llm_credit(user_id)
            if not granted:
                return {
                    "status": "success",
                    "message": _UPGRADE_MSG,
                    "paused": False,
                    "items": [],
                }
            result = await graph.ainvoke(
                {
                    "messages": [HumanMessage(content=user_input)],
                    "user_id": user_id,
                    "image_b64": image_b64 or "",
                    "entities": [],
                    "usda_results": [],
                    "meal_type": None,
                    "action": None,
                    "from_saved": False,
                    "meal_id": None,
                },
                config=config,
            )

        new_state = await graph.aget_state(config)
        still_paused = bool(new_state.next)

        last_ai = next(
            (m for m in reversed(result["messages"]) if isinstance(m, AIMessage)),
            None,
        )

        items = []
        if still_paused:
            for r in result.get("usda_results", []):
                items.append(
                    {
                        "food_name": r["food_name"],
                        "qty_g": r["qty_g"],
                        "confidence": r["match_confidence"],
                        "kcal": r["kcal"],
                        "protein_g": r["protein_g"],
                        "carbs_g": r["carbs_g"],
                        "fat_g": r["fat_g"],
                        "fiber_g": r["fiber_g"],
                        "fdc_id": r["fdc_id"],
                        "candidates": r.get("candidates", []),
                        "source": r.get("source", "USDA"),
                        "estimated": r.get("estimated", False),
                        "source_dish": r.get("source_dish"),
                        "sugar_g": r.get("sugar_g", 0.0),
                        "sat_fat_g": r.get("sat_fat_g", 0.0),
                        "nutrients": r.get("nutrients", {}),
                    }
                )

        response: dict[str, Any] = {
            "status": "success",
            "message": last_ai.content if last_ai else "",
            "paused": still_paused,
            "items": items,
        }
        if not still_paused:
            response["meal_id"] = result.get("meal_id")
        return response
```

- [ ] **Step 4: Run tests and confirm they pass**

```bash
python -m pytest tests/test_orchestrator_quota.py -v
```

Expected:
```
tests/test_orchestrator_quota.py::test_coaching_over_quota_returns_upgrade_message PASSED
tests/test_orchestrator_quota.py::test_coaching_under_quota_calls_agent PASSED
tests/test_orchestrator_quota.py::test_classify_intent_over_quota_defaults_to_log_meal PASSED
tests/test_orchestrator_quota.py::test_classify_intent_keyword_match_skips_quota PASSED
tests/test_orchestrator_quota.py::test_meal_logging_over_quota_returns_upgrade_message PASSED
tests/test_orchestrator_quota.py::test_meal_logging_paused_resume_skips_quota PASSED
6 passed
```

- [ ] **Step 5: Run the full test suite to check for regressions**

```bash
python -m pytest tests/ -v --ignore=tests/test_e2e_meals.py -x 2>&1 | tail -20
```

Expected: all tests pass. If `test_coaching.py` fails due to `_classify_intent` signature change, those tests mock `_classify_intent` directly and won't be affected.

- [ ] **Step 6: Commit**

```bash
git add src/backend/agent/orchestrator.py tests/test_orchestrator_quota.py
git commit -m "feat(quota): gate LLM calls in orchestrator with consume_llm_credit()"
```

---

## Task 4: `GET /quota` Endpoint

**Files:**
- Create: `src/backend/api/quota.py`
- Modify: `src/backend/main.py`
- Create: `tests/test_quota_api.py`

**Interfaces:**
- Consumes: `FREE_QUOTA`, `PAID_QUOTA` from `backend.quota` (Task 2)
- Consumes: `UserGoal` from `backend.db.models` (Task 1)
- Consumes: `get_current_user_id` from `backend.auth.supabase`
- Produces: `GET /quota` → `{"used": int, "limit": int, "remaining": int, "exhausted": bool, "tier": str}`

---

- [ ] **Step 1: Write failing tests**

Create `tests/test_quota_api.py`:

```python
"""Tests for GET /quota endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import quota as quota_router_module
from backend.auth.supabase import get_current_user_id
from backend.db.models import UserGoal


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(quota_router_module.router)
    return app


def _mock_goal(used: int, limit: int) -> UserGoal:
    goal = MagicMock(spec=UserGoal)
    goal.llm_requests_used = used
    goal.llm_quota = limit
    return goal


def _mock_session(goal):
    session = MagicMock()
    session.get = AsyncMock(return_value=goal)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=session)


def test_quota_requires_auth():
    client = TestClient(_make_app())
    assert client.get("/quota").status_code == 401


def test_quota_free_user_under_limit(monkeypatch):
    app = _make_app()
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"

    goal = _mock_goal(used=34, limit=50)
    monkeypatch.setattr(quota_router_module, "get_session", _mock_session(goal))

    client = TestClient(app)
    resp = client.get("/quota")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"used": 34, "limit": 50, "remaining": 16, "exhausted": False, "tier": "free"}


def test_quota_paid_user(monkeypatch):
    app = _make_app()
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"

    goal = _mock_goal(used=80, limit=150)
    monkeypatch.setattr(quota_router_module, "get_session", _mock_session(goal))

    client = TestClient(app)
    resp = client.get("/quota")
    assert resp.status_code == 200
    body = resp.json()
    assert body["tier"] == "paid"
    assert body["remaining"] == 70
    assert body["exhausted"] is False


def test_quota_exhausted_user(monkeypatch):
    app = _make_app()
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"

    goal = _mock_goal(used=50, limit=50)
    monkeypatch.setattr(quota_router_module, "get_session", _mock_session(goal))

    client = TestClient(app)
    resp = client.get("/quota")
    assert resp.status_code == 200
    body = resp.json()
    assert body["exhausted"] is True
    assert body["remaining"] == 0


def test_quota_no_goal_row_returns_free_defaults(monkeypatch):
    """New user with no user_goal row gets free-tier defaults."""
    app = _make_app()
    app.dependency_overrides[get_current_user_id] = lambda: "new-user"

    monkeypatch.setattr(quota_router_module, "get_session", _mock_session(goal=None))

    client = TestClient(app)
    resp = client.get("/quota")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"used": 0, "limit": 50, "remaining": 50, "exhausted": False, "tier": "free"}
```

- [ ] **Step 2: Run to confirm tests fail**

```bash
python -m pytest tests/test_quota_api.py -v 2>&1 | head -20
```

Expected: `ImportError: cannot import name 'router' from 'backend.api.quota'`

- [ ] **Step 3: Implement `src/backend/api/quota.py`**

```python
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from backend.auth.supabase import get_current_user_id
from backend.db.models import UserGoal
from backend.db.session import get_session
from backend.quota import FREE_QUOTA, PAID_QUOTA

router = APIRouter(prefix="/quota", tags=["quota"])


class QuotaResponse(BaseModel):
    used: int
    limit: int
    remaining: int
    exhausted: bool
    tier: str

    model_config = ConfigDict(extra="forbid")


@router.get("", response_model=QuotaResponse)
async def get_quota(user_id: str = Depends(get_current_user_id)) -> QuotaResponse:
    """Return the authenticated user's LLM credit usage.

    Args:
        user_id: Supabase Auth UUID resolved from the bearer token.

    Returns:
        QuotaResponse with used, limit, remaining, exhausted, and tier.
    """
    session_factory = get_session()
    async with session_factory() as session:
        goal = await session.get(UserGoal, user_id)

    if goal is None:
        return QuotaResponse(
            used=0,
            limit=FREE_QUOTA,
            remaining=FREE_QUOTA,
            exhausted=False,
            tier="free",
        )

    used = goal.llm_requests_used
    limit = goal.llm_quota
    remaining = max(0, limit - used)
    return QuotaResponse(
        used=used,
        limit=limit,
        remaining=remaining,
        exhausted=used >= limit,
        tier="paid" if limit >= PAID_QUOTA else "free",
    )
```

- [ ] **Step 4: Register the quota router in `main.py`**

Add `quota` to the existing imports block (keep alphabetical order):

```python
from backend.api import (
    goals,
    integrations,
    meals,
    mindful,
    my_meals,
    nutrient_checkup,
    quota,
    telegram_link,
)
```

Add after the other `app.include_router` calls:

```python
app.include_router(quota.router)
```

- [ ] **Step 5: Run tests and confirm they pass**

```bash
python -m pytest tests/test_quota_api.py -v
```

Expected:
```
tests/test_quota_api.py::test_quota_requires_auth PASSED
tests/test_quota_api.py::test_quota_free_user_under_limit PASSED
tests/test_quota_api.py::test_quota_paid_user PASSED
tests/test_quota_api.py::test_quota_exhausted_user PASSED
tests/test_quota_api.py::test_quota_no_goal_row_returns_free_defaults PASSED
5 passed
```

- [ ] **Step 6: Commit**

```bash
git add src/backend/api/quota.py src/backend/main.py tests/test_quota_api.py
git commit -m "feat(quota): add GET /quota endpoint returning used/limit/remaining/exhausted/tier"
```

---

## Task 5: Billing Upgrade Path

**Files:**
- Modify: `src/backend/api/billing.py`

**Interfaces:**
- Consumes: `PAID_QUOTA` from `backend.quota` (Task 2)
- Consumes: `UserGoal` from `backend.db.models` (Task 1)
- Produces: `POST /billing/upgrade` — sets `llm_quota = PAID_QUOTA` on the caller's `user_goal` row

---

- [ ] **Step 1: Write the failing test**

Add `tests/test_billing_quota.py`:

```python
"""Tests for POST /billing/upgrade quota promotion."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import billing
from backend.auth.supabase import get_current_user_id
from backend.db.models import UserGoal
from backend.quota import PAID_QUOTA


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(billing.router)
    return app


def _mock_session(goal):
    session = MagicMock()
    session.get = AsyncMock(return_value=goal)
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=session)


def test_upgrade_sets_paid_quota(monkeypatch):
    app = _make_app()
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"

    goal = MagicMock(spec=UserGoal)
    goal.llm_quota = 50
    goal.llm_requests_used = 30
    monkeypatch.setattr(billing, "get_session", _mock_session(goal))

    client = TestClient(app)
    resp = client.post("/billing/upgrade")
    assert resp.status_code == 200
    assert goal.llm_quota == PAID_QUOTA


def test_upgrade_does_not_reset_counter(monkeypatch):
    """Upgrading leaves llm_requests_used untouched."""
    app = _make_app()
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"

    goal = MagicMock(spec=UserGoal)
    goal.llm_quota = 50
    goal.llm_requests_used = 30
    monkeypatch.setattr(billing, "get_session", _mock_session(goal))

    client = TestClient(app)
    client.post("/billing/upgrade")
    assert goal.llm_requests_used == 30


def test_upgrade_requires_auth():
    client = TestClient(_make_app())
    assert client.post("/billing/upgrade").status_code == 401
```

- [ ] **Step 2: Run to confirm tests fail**

```bash
python -m pytest tests/test_billing_quota.py -v 2>&1 | head -20
```

Expected: `ImportError` or 404 — `billing.router` exists but has no route.

- [ ] **Step 3: Implement `src/backend/api/billing.py`**

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from backend.auth.supabase import get_current_user_id
from backend.db.models import UserGoal
from backend.db.session import get_session
from backend.quota import PAID_QUOTA

router = APIRouter(prefix="/billing", tags=["billing"])


class UpgradeResponse(BaseModel):
    tier: str
    quota: int

    model_config = ConfigDict(extra="forbid")


@router.post("/upgrade", response_model=UpgradeResponse)
async def upgrade_to_paid(user_id: str = Depends(get_current_user_id)) -> UpgradeResponse:
    """Promote the authenticated user to the paid tier.

    Sets llm_quota to PAID_QUOTA without resetting llm_requests_used, so
    credits consumed on the free tier carry forward. In production this
    endpoint is called by a Stripe webhook after a successful payment.

    Args:
        user_id: Supabase Auth UUID resolved from the bearer token.

    Returns:
        UpgradeResponse with the new tier and quota.

    Raises:
        HTTPException 404: If the user has no user_goal row yet.
    """
    session_factory = get_session()
    async with session_factory() as session:
        goal = await session.get(UserGoal, user_id)
        if goal is None:
            raise HTTPException(status_code=404, detail="User profile not found")
        goal.llm_quota = PAID_QUOTA
        await session.commit()

    return UpgradeResponse(tier="paid", quota=PAID_QUOTA)
```

- [ ] **Step 4: Register billing router in `main.py`**

Add `billing` to the imports block (already has `quota` from Task 4):

```python
from backend.api import (
    billing,
    goals,
    integrations,
    meals,
    mindful,
    my_meals,
    nutrient_checkup,
    quota,
    telegram_link,
)
```

Add after `app.include_router(quota.router)`:

```python
app.include_router(billing.router)
```

- [ ] **Step 5: Run tests and confirm they pass**

```bash
python -m pytest tests/test_billing_quota.py -v
```

Expected:
```
tests/test_billing_quota.py::test_upgrade_sets_paid_quota PASSED
tests/test_billing_quota.py::test_upgrade_does_not_reset_counter PASSED
tests/test_billing_quota.py::test_upgrade_requires_auth PASSED
3 passed
```

- [ ] **Step 6: Run full test suite**

```bash
python -m pytest tests/ -v --ignore=tests/test_e2e_meals.py -x 2>&1 | tail -10
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/backend/api/billing.py src/backend/main.py tests/test_billing_quota.py
git commit -m "feat(quota): billing upgrade sets llm_quota to PAID_QUOTA"
```
