# Android Backend Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the Mealsy API for a native Android launch: sized DB pool, idempotent logging, pending-card recovery, FCM push, and a version gate.

**Architecture:** Five additive changes to the existing FastAPI backend; no breaking changes to any response shape. Two Alembic migrations (012, 013). New external dependency: `firebase-admin`.

**Tech Stack:** Python 3.12/3.13 · FastAPI · SQLAlchemy async · Alembic · Celery · psycopg_pool · firebase-admin · pytest (`asyncio_mode=auto`).

**Spec:** `docs/specs/2026-09-05-android-launch.md` (§3)

## Global Constraints

- All new code follows `.claude/CLAUDE.md`: `from __future__ import annotations`, full type annotations, Google docstrings, Pydantic models with `extra="forbid"` for request/response bodies, Black 88-char, no bare except.
- Run tests with `uv run pytest tests/<file> -v` (conftest supplies dummy env; DB tests marked `integration` need local docker-compose Postgres on port 5411).
- Response shapes of existing endpoints may gain fields but never lose or rename any (spec §A6).
- Commit after every green task; never push. Prod deploy/migration is manual and out of scope.
- After Tasks 2–3 (they touch the agent write path), run `uv run --env-file .env python eval/gate.py --runs 5 --baseline eval/baseline_scores.json` — scores must not move.

---

### Task 1: Checkpointer pool sizing + timeout

**Files:**
- Modify: `src/backend/db/checkpointer.py` (the `AsyncConnectionPool(...)` construction inside `pooled_checkpointer`)
- Test: `tests/test_checkpointer_pool.py` (create)

**Interfaces:**
- Consumes: existing `pooled_checkpointer()` context manager.
- Produces: pool honors env `CHECKPOINTER_POOL_SIZE` (int, default 8) and has `timeout=5.0`. No signature changes.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for checkpointer pool sizing (no live DB needed)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from backend.db import checkpointer as cp


@pytest.fixture
def pool_kwargs():
    """Capture kwargs passed to AsyncConnectionPool without opening one."""
    captured = {}

    class FakePool:
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)

        async def open(self):  # pragma: no cover - shape only
            pass

        async def close(self):
            pass

    with patch.object(cp, "AsyncConnectionPool", FakePool), patch.object(
        cp, "AsyncPostgresSaver", AsyncMock()
    ):
        yield captured


async def test_pool_size_defaults_to_eight(pool_kwargs, monkeypatch):
    monkeypatch.delenv("CHECKPOINTER_POOL_SIZE", raising=False)
    async with cp.pooled_checkpointer():
        pass
    assert pool_kwargs["max_size"] == 8
    assert pool_kwargs["timeout"] == 5.0


async def test_pool_size_from_env(pool_kwargs, monkeypatch):
    monkeypatch.setenv("CHECKPOINTER_POOL_SIZE", "3")
    async with cp.pooled_checkpointer():
        pass
    assert pool_kwargs["max_size"] == 3
```

Adjust the fixture to whatever `pooled_checkpointer` actually does after reading it (e.g. if it calls `pool.open()` positionally or uses `saver.setup()` — mock those the same way). The assertion targets are only `max_size` and `timeout`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_checkpointer_pool.py -v`
Expected: FAIL — `max_size` is 4 and `timeout` absent.

- [ ] **Step 3: Implement**

In `src/backend/db/checkpointer.py`, change the pool construction:

```python
import os  # add to imports if missing

pool = AsyncConnectionPool(
    conninfo=conninfo,
    min_size=1,
    max_size=int(os.environ.get("CHECKPOINTER_POOL_SIZE", "8")),
    timeout=5.0,  # raise PoolTimeout loudly instead of stalling requests
    max_idle=240,
    check=_check_connection,
    open=False,
)
```

Keep every existing kwarg that is already there; only add `max_size` env lookup and `timeout`.

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_checkpointer_pool.py tests/test_orchestrator.py -v`
Expected: PASS (orchestrator tests guard against accidental breakage).

- [ ] **Step 5: Document + commit**

Add `CHECKPOINTER_POOL_SIZE=8` (web) with a comment `# worker=3 bot=2; sum of all pools must stay under Supabase pooler cap` to `.env.example`.

```bash
git add src/backend/db/checkpointer.py tests/test_checkpointer_pool.py .env.example
git commit -m "feat(db): env-sized checkpointer pool with loud 5s timeout"
```

---

### Task 2: Idempotent `POST /meals/log-items` (migration 012)

**Files:**
- Create: `src/backend/db/migrations/versions/20260905_012_meal_log_client_request_id.py`
- Modify: `src/backend/db/models.py` (MealLog), `src/backend/api/meals.py` (`LogItemsRequest`, `log_items` handler)
- Test: `tests/test_log_items.py` (extend)

**Interfaces:**
- Consumes: existing `log_items` handler and `persist_meal` (`backend.agent.tools.meals.log_meal`).
- Produces: `LogItemsRequest.client_request_id: str | None` (UUID string); response gains `"deduplicated": bool`. Column `meal_log.client_request_id: str | None`. Task 5's docs reference these names verbatim.

- [ ] **Step 1: Migration**

```python
"""meal_log.client_request_id for idempotent mobile replays.

Revision ID: 012_client_request_id
Revises: 011_food_source_trgm
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "012_client_request_id"
down_revision = "011_food_source_trgm"


def upgrade() -> None:
    op.add_column(
        "meal_log",
        sa.Column("client_request_id", sa.String(64), nullable=True),
    )
    op.create_index(
        "uq_meal_log_user_client_request",
        "meal_log",
        ["user_id", "client_request_id"],
        unique=True,
        postgresql_where=sa.text("client_request_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_meal_log_user_client_request", table_name="meal_log")
    op.drop_column("meal_log", "client_request_id")
```

Check the real revision ids first (`ls src/backend/db/migrations/versions/`, open 011 for its `revision` string) and use those exact values for `down_revision`.

- [ ] **Step 2: Model column**

In `MealLog` (models.py), after `label`:

```python
    client_request_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
```

- [ ] **Step 3: Write the failing test** (append to `tests/test_log_items.py`, reusing its existing client/fixture pattern — read the file first and mirror how the current tests build requests and stub `persist_meal`)

```python
async def test_log_items_dedupes_on_client_request_id(client, db_session):
    body = {
        "meal_type": "lunch",
        "portion": 1.0,
        "client_request_id": "11111111-1111-1111-1111-111111111111",
        "items": [
            {"food_name": "banana, raw", "qty_g": 118, "target_qty_g": 118,
             "kcal": 105, "protein_g": 1.3, "carbs_g": 27, "fat_g": 0.4,
             "fiber_g": 3.1, "fdc_id": 1105314}
        ],
    }
    first = await client.post("/meals/log-items", json=body)
    assert first.status_code == 200
    assert first.json()["deduplicated"] is False

    second = await client.post("/meals/log-items", json=body)
    assert second.status_code == 200
    assert second.json()["deduplicated"] is True
    assert second.json()["meal_id"] == first.json()["meal_id"]
```

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run pytest tests/test_log_items.py -v -k dedupe`
Expected: FAIL — 422 (unknown field) or missing `deduplicated`.

- [ ] **Step 5: Implement handler**

In `api/meals.py`:
1. `LogItemsRequest` gains `client_request_id: str | None = Field(default=None, max_length=64)`.
2. In `log_items`, before persisting: if `req.client_request_id`, `SELECT` an existing `MealLog` by `(user_id, client_request_id)`; if found, rebuild the success response from that row and return it with `"deduplicated": True`.
3. Pass `client_request_id` through to the insert (thread it into `persist_meal` as a new optional keyword `client_request_id: str | None = None`, stored on the row) and add `"deduplicated": False` to the normal response.
4. Wrap the insert so a concurrent-duplicate `IntegrityError` on `uq_meal_log_user_client_request` is caught and answered by re-selecting the winner row (same dedup response) — this is the race-safe path; the pre-select is just the fast path.

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/test_log_items.py tests/test_meal_tools.py -v`
Expected: PASS.

- [ ] **Step 7: Eval gate + commit**

Run: `uv run --env-file .env python eval/gate.py --runs 5 --baseline eval/baseline_scores.json` — no category may regress past tolerance.

```bash
git add src/backend/db/migrations/versions/20260905_012_meal_log_client_request_id.py src/backend/db/models.py src/backend/api/meals.py src/backend/agent/tools/meals.py tests/test_log_items.py
git commit -m "feat(meals): idempotent log-items via client_request_id"
```

---

### Task 3: `GET /meals/pending` recovery endpoint

**Files:**
- Modify: `src/backend/api/meals.py`, `src/backend/agent/orchestrator.py`
- Test: `tests/test_pending_endpoint.py` (create)

**Interfaces:**
- Consumes: `graph.aget_state(config)` pattern from `orchestrator.handle_message` (orchestrator.py:143), `_graph_for(checkpointer)`.
- Produces: `async def get_pending_card(user_id: str, thread_id: str, checkpointer: Any) -> dict[str, Any]` in `orchestrator.py`, returning `{"paused": False}` or `{"status": "pending", "paused": True, "message": <last AI message text>, "items": <serialized usda_results>}`. Route `GET /meals/pending?conversation_id=`.

- [ ] **Step 1: Read the serialization precedent**

Open `orchestrator.py` `_handle_meal_logging` and find how `items` are built from `usda_results` for the normal paused response (there is an existing helper or inline dict-building — reuse it verbatim; if it's inline, extract it to `_serialize_items(usda_results) -> list[dict]` first so both paths share it).

- [ ] **Step 2: Write the failing test**

```python
"""GET /meals/pending returns the paused card or paused=false."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from backend.agent import orchestrator


async def test_not_paused_returns_false():
    graph = AsyncMock()
    graph.aget_state.return_value = SimpleNamespace(next=(), values={})
    with patch.object(orchestrator, "_graph_for", return_value=graph):
        out = await orchestrator.get_pending_card("u1", "t1", checkpointer=object())
    assert out == {"paused": False}


async def test_paused_returns_card():
    fake_result = SimpleNamespace(
        fdc_id=123, food_name="banana, raw", qty_g=118.0, kcal=105.0,
        protein_g=1.3, carbs_g=27.0, fat_g=0.4, fiber_g=3.1,
        match_confidence=0.95, estimated=False,
    )

    class Msg:
        type = "ai"
        content = "Here's your card"

    graph = AsyncMock()
    graph.aget_state.return_value = SimpleNamespace(
        next=("intent_router",),
        values={"usda_results": [fake_result], "messages": [Msg()]},
    )
    with patch.object(orchestrator, "_graph_for", return_value=graph):
        out = await orchestrator.get_pending_card("u1", "t1", checkpointer=object())
    assert out["paused"] is True
    assert out["items"][0]["food_name"] == "banana, raw"
    assert out["message"] == "Here's your card"
```

Align `fake_result`'s shape with whatever `_serialize_items` actually reads (attributes vs dict) after Step 1.

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_pending_endpoint.py -v`
Expected: FAIL — `get_pending_card` not defined.

- [ ] **Step 4: Implement**

In `orchestrator.py`:

```python
async def get_pending_card(
    user_id: str,
    thread_id: str,
    checkpointer: Any,
) -> dict[str, Any]:
    """Return the unanswered confirmation card for a thread, if any.

    Read-only recovery path for clients that lost the POST /meals/log
    response (mobile process death, dropped connection). Never runs the
    graph, never consumes quota.
    """
    graph = _graph_for(checkpointer)
    config = {"configurable": {"thread_id": thread_id, "user_id": user_id}}
    state = await graph.aget_state(config)
    if not state.next:
        return {"paused": False}
    messages = state.values.get("messages", [])
    ai_texts = [m.content for m in messages if getattr(m, "type", "") == "ai"]
    return {
        "status": "pending",
        "paused": True,
        "message": ai_texts[-1] if ai_texts else "",
        "items": _serialize_items(state.values.get("usda_results", [])),
    }
```

In `api/meals.py`:

```python
@router.get("/pending")
async def pending_card(
    request: Request,
    conversation_id: str = Query(min_length=1),
    user_id: str = Depends(get_current_user_id),
) -> dict:
    return await get_pending_card(
        user_id=user_id,
        thread_id=conversation_id,
        checkpointer=request.app.state.checkpointer,
    )
```

(import `get_pending_card` alongside `handle_message`). No rate-limit dependency — it's a cheap read; the global IP limiter still covers it.

- [ ] **Step 5: Run tests + commit**

Run: `uv run pytest tests/test_pending_endpoint.py tests/test_orchestrator.py -v` → PASS.

```bash
git add src/backend/agent/orchestrator.py src/backend/api/meals.py tests/test_pending_endpoint.py
git commit -m "feat(meals): GET /meals/pending recovers a paused confirmation card"
```

---

### Task 4: FCM device registration + sender (migration 013)

**Files:**
- Create: `src/backend/db/migrations/versions/20260905_013_device_token.py`, `src/backend/api/devices.py`, `src/backend/push/fcm.py`
- Modify: `src/backend/db/models.py`, `src/backend/main.py` (include router), `src/backend/workers/tasks.py` (task + beat), `pyproject.toml` (`firebase-admin>=6`)
- Test: `tests/test_devices_api.py`, `tests/test_fcm.py` (create)

**Interfaces:**
- Consumes: `get_current_user_id`, `get_session`, Celery `app` in `workers/tasks.py`, beat-schedule dict.
- Produces: model `DeviceToken` (`device_token` table: id, user_id, platform, token, created_at, last_seen_at); routes `POST /devices/register` (201, body `{token, platform}`) and `DELETE /devices/{token}` (204); function `backend.push.fcm.send_to_user(user_id: str, title: str, body: str, data: dict[str, str] | None = None) -> int` (returns tokens successfully sent); Celery tasks `send_push_fcm(user_id, title, body, data)` and `send_daily_summary_push` (beat 07:00).

- [ ] **Step 1: Migration + model**

Migration `20260905_013_device_token.py` (set `down_revision = "012_client_request_id"`):

```python
def upgrade() -> None:
    op.create_table(
        "device_token",
        sa.Column("id", postgresql.UUID(), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(),
                  sa.ForeignKey("user_goal.user_id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("platform", sa.String(16), nullable=False,
                  server_default="fcm"),
        sa.Column("token", sa.Text(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_device_token_user", "device_token", ["user_id"])
```

Model in `models.py` mirrors it (`class DeviceToken(Base)`, `__tablename__ = "device_token"`), following the `PushSubscription` class style at models.py:67.

- [ ] **Step 2: Failing API test** (`tests/test_devices_api.py`, mirroring the fixture style of `tests/test_goals_api.py` — read it first and copy its app/client/session setup)

```python
async def test_register_upserts_on_token(client):
    body = {"token": "fcm-abc", "platform": "fcm"}
    r1 = await client.post("/devices/register", json=body)
    assert r1.status_code == 201
    r2 = await client.post("/devices/register", json=body)  # same token again
    assert r2.status_code == 201  # upsert, not conflict


async def test_delete_token(client):
    await client.post("/devices/register", json={"token": "fcm-x", "platform": "fcm"})
    r = await client.delete("/devices/fcm-x")
    assert r.status_code == 204


async def test_register_rejects_unknown_platform(client):
    r = await client.post("/devices/register", json={"token": "t", "platform": "apns"})
    assert r.status_code == 422
```

- [ ] **Step 3: Run to verify failure** — `uv run pytest tests/test_devices_api.py -v` → FAIL (404, no router).

- [ ] **Step 4: Implement `api/devices.py`**

```python
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from backend.auth.supabase import get_current_user_id
from backend.db.models import DeviceToken
from backend.db.session import get_session

router = APIRouter(prefix="/devices", tags=["devices"])


class RegisterDeviceRequest(BaseModel):
    token: str = Field(min_length=1)
    platform: Literal["fcm"]

    model_config = ConfigDict(extra="forbid")


@router.post("/register", status_code=201)
async def register_device(
    req: RegisterDeviceRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Upsert an FCM token; re-registration rebinds it to the current user."""
    stmt = pg_insert(DeviceToken).values(
        user_id=user_id, platform=req.platform, token=req.token
    ).on_conflict_do_update(
        index_elements=[DeviceToken.token],
        set_={"user_id": user_id, "last_seen_at": func.now()},
    )
    await db.execute(stmt)
    await db.commit()
    return {"status": "registered"}


@router.delete("/{token}", status_code=204)
async def delete_device(
    token: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_session),
) -> Response:
    await db.execute(
        delete(DeviceToken).where(
            DeviceToken.token == token, DeviceToken.user_id == user_id
        )
    )
    await db.commit()
    return Response(status_code=204)
```

Register in `main.py` next to the other routers: `from backend.api import devices` … `app.include_router(devices.router)`.

- [ ] **Step 5: Failing sender test** (`tests/test_fcm.py`)

```python
"""FCM sender: sends per token, prunes dead tokens, no-ops unconfigured."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.push import fcm


async def test_send_to_user_no_tokens_returns_zero(db_session):
    sent = await fcm.send_to_user("00000000-0000-0000-0000-0000000000bb",
                                  "hi", "body")
    assert sent == 0


async def test_send_prunes_unregistered_token(db_session, seeded_device_token):
    err = fcm.messaging.UnregisteredError("gone")  # type: ignore[attr-defined]
    with patch.object(fcm, "_send_one", side_effect=err):
        sent = await fcm.send_to_user(seeded_device_token.user_id, "hi", "b")
    assert sent == 0
    # token row deleted — assert via a fresh select in the fixture's session
```

Write the `seeded_device_token` fixture in this file (insert a `DeviceToken` row for the conftest test user).

- [ ] **Step 6: Implement `push/fcm.py`**

```python
"""Send FCM notifications to a user's registered Android devices.

Lazy-initializes firebase-admin from FIREBASE_CREDENTIALS_JSON (service
account JSON as a string). When the env var is absent (dev, CI), sending
is a logged no-op so the rest of the app never needs Firebase locally.
"""
from __future__ import annotations

import asyncio
import json
import os

import firebase_admin
import logfire
from firebase_admin import credentials, messaging
from sqlalchemy import delete, select

from backend.db.models import DeviceToken
from backend.db.session import async_session

_app: firebase_admin.App | None = None


def _get_app() -> firebase_admin.App | None:
    global _app
    if _app is not None:
        return _app
    raw = os.environ.get("FIREBASE_CREDENTIALS_JSON", "").strip()
    if not raw:
        return None
    _app = firebase_admin.initialize_app(credentials.Certificate(json.loads(raw)))
    return _app


def _send_one(token: str, title: str, body: str, data: dict[str, str]) -> None:
    """Blocking single-message send; called via asyncio.to_thread."""
    messaging.send(
        messaging.Message(
            token=token,
            notification=messaging.Notification(title=title, body=body),
            data=data,
        )
    )


async def send_to_user(
    user_id: str,
    title: str,
    body: str,
    data: dict[str, str] | None = None,
) -> int:
    """Send a push to every device of user_id; prune dead tokens.

    Returns:
        Number of tokens successfully delivered to.
    """
    if _get_app() is None:
        logfire.info("fcm_disabled", user_id=user_id)
        return 0
    async with async_session() as db:
        rows = (
            await db.execute(
                select(DeviceToken.token).where(DeviceToken.user_id == user_id)
            )
        ).scalars().all()
        sent = 0
        for token in rows:
            try:
                await asyncio.to_thread(_send_one, token, title, body, data or {})
                sent += 1
            except (messaging.UnregisteredError, ValueError):
                await db.execute(
                    delete(DeviceToken).where(DeviceToken.token == token)
                )
        await db.commit()
    return sent
```

Check the real session-factory name in `backend/db/session.py` first (`async_session` vs `get_session_factory` etc.) and use that. Add `firebase-admin>=6.5` to `pyproject.toml` deps and run `uv sync`. Create `src/backend/push/__init__.py` (empty).

- [ ] **Step 7: Celery tasks** (in `workers/tasks.py`, following the `_run()` wrapper pattern used by the existing tasks)

```python
@app.task(name="backend.workers.tasks.send_push_fcm")
def send_push_fcm(user_id: str, title: str, body: str,
                  data: dict[str, str] | None = None) -> int:
    from backend.push.fcm import send_to_user
    return _run(send_to_user(user_id, title, body, data))


@app.task(name="backend.workers.tasks.send_daily_summary_push")
def send_daily_summary_push() -> int:
    """Beat 07:00: enqueue one send_push_fcm per user with device tokens."""
    async def _fan_out() -> int:
        async with async_session() as db:
            user_ids = (
                await db.execute(select(DeviceToken.user_id).distinct())
            ).scalars().all()
        for uid in user_ids:
            send_push_fcm.delay(
                uid, "Your Mealsy daily summary",
                "Yesterday's recap is ready — open Mealsy to see it.",
                {"deeplink": "mealsy://chat"},
            )
        return len(user_ids)
    return _run(_fan_out())
```

Beat entry beside the Telegram one:

```python
"send-daily-summary-push": {
    "task": "backend.workers.tasks.send_daily_summary_push",
    "schedule": crontab(hour=7, minute=0),
},
```

Mirror the exact `_run`/import style already in the file.

- [ ] **Step 8: Run everything + commit**

Run: `uv run pytest tests/test_devices_api.py tests/test_fcm.py tests/test_workers.py tests/test_tasks.py -v` → PASS.

Add to `.env.example`: `FIREBASE_CREDENTIALS_JSON=  # service-account JSON string; empty = push disabled`.

```bash
git add src/backend/api/devices.py src/backend/push/ src/backend/db/models.py src/backend/db/migrations/versions/20260905_013_device_token.py src/backend/workers/tasks.py src/backend/main.py pyproject.toml uv.lock .env.example tests/test_devices_api.py tests/test_fcm.py
git commit -m "feat(push): FCM device registration, sender, and 07:00 daily summary"
```

---

### Task 5: `/meta/app` version gate + mobile API doc

**Files:**
- Create: `src/backend/api/meta.py`, `docs/reference/mobile-api.md`
- Modify: `src/backend/main.py`
- Test: `tests/test_meta_api.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: unauthed `GET /meta/app` → `{"min_supported_version_code": int, "latest_version_code": int}` from env `ANDROID_MIN_VERSION_CODE` / `ANDROID_LATEST_VERSION_CODE` (both default 1). Workstream B's version-gate task reads exactly these field names.

- [ ] **Step 1: Failing test**

```python
from __future__ import annotations


async def test_meta_app_defaults(client):
    r = await client.get("/meta/app")
    assert r.status_code == 200
    assert r.json() == {"min_supported_version_code": 1,
                        "latest_version_code": 1}


async def test_meta_app_from_env(client, monkeypatch):
    monkeypatch.setenv("ANDROID_MIN_VERSION_CODE", "4")
    monkeypatch.setenv("ANDROID_LATEST_VERSION_CODE", "7")
    r = await client.get("/meta/app")
    assert r.json() == {"min_supported_version_code": 4,
                        "latest_version_code": 7}
```

(unauthed client fixture — no `X-Debug-User-Id` header needed; confirm the route is reachable without auth.)

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_meta_api.py -v` → 404.

- [ ] **Step 3: Implement `api/meta.py`**

```python
from __future__ import annotations

import os

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

router = APIRouter(prefix="/meta", tags=["meta"])


class AppVersionResponse(BaseModel):
    min_supported_version_code: int
    latest_version_code: int

    model_config = ConfigDict(extra="forbid")


@router.get("/app", response_model=AppVersionResponse)
async def app_version() -> AppVersionResponse:
    """Version gate for the Android client (unauthed).

    A client below min_supported_version_code must block and prompt an
    upgrade; between min and latest it may show a soft nudge.
    """
    return AppVersionResponse(
        min_supported_version_code=int(
            os.environ.get("ANDROID_MIN_VERSION_CODE", "1")
        ),
        latest_version_code=int(
            os.environ.get("ANDROID_LATEST_VERSION_CODE", "1")
        ),
    )
```

Include in `main.py`. Add both env vars to `.env.example`.

- [ ] **Step 4: Write `docs/reference/mobile-api.md`**

Hand-written contract doc listing the ten endpoints from spec §4 with request/response examples (copy real shapes from the code, including `deduplicated` and `paused`), plus the three invariants: fields are never removed or renamed; enums never shrink; clients must ignore unknown fields. Note that `/meals/log` may take 2–6 s and clients must not retry it on timeout (use `/meals/pending` instead) — `/meals/log-items` with `client_request_id` is the only safe-to-retry write.

- [ ] **Step 5: Run + commit**

Run: `uv run pytest tests/test_meta_api.py -v` → PASS. Full suite once: `uv run pytest -m "not integration" -q`.

```bash
git add src/backend/api/meta.py src/backend/main.py tests/test_meta_api.py docs/reference/mobile-api.md .env.example
git commit -m "feat(meta): app version gate + frozen mobile API contract doc"
```
