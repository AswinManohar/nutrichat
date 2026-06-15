# Daily Nutrient Summary vs RDA Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing 7-day Nutrient Check-up with a generic-adult RDA baseline
comparison and a deterministic plain-English summary, surfaced on the dashboard card, via
a daily Telegram message, and as a one-time chat nudge.

**Architecture:** All new computation piggybacks on the existing nightly
`build_nutrient_checkup` Celery task (01:30 Europe/Oslo): `get_nutrient_checkup_aggregates`
gains a per-nutrient `rda_pct`, and a new pure helper `summarize_nutrient_checkup` turns
the notable nutrients into a template string. Both are persisted on `nutrient_checkup`
via two new columns plus two delivery-tracking timestamps. A second Celery task
(07:00) pushes `summary_text` to linked Telegram chats. `GET /nutrient-checkup` exposes
the new fields to the dashboard; two new endpoints serve/ack a one-time chat nudge.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, Celery beat, aiogram (Telegram),
Pydantic, React 19 + TypeScript + TanStack Query, pytest + pytest-asyncio.

---

## Task 1: RDA baseline tunables config

**Files:**
- Modify: `src/backend/config/tunables.yaml:186-219` (nutrient_checkup section)
- Modify: `src/backend/config/__init__.py:99-105` (`NutrientCheckupConfig`)
- Test: `tests/test_config.py` (new file if it doesn't exist — check first)

- [ ] **Step 1: Check for an existing config test file**

Run: `ls tests/test_config.py 2>/dev/null || echo "no existing file"`

If it exists, add the test below into it (matching its existing import style). If not,
create `tests/test_config.py` with:

```python
from __future__ import annotations

from backend.config import get_tunables


def test_nutrient_checkup_rda_loaded() -> None:
    rda = get_tunables().nutrient_checkup.rda
    assert rda["Protein"] == 50
    assert rda["Fiber"] == 28
    assert rda["Sugar"] == 50
    assert rda["Vitamin C"] == 90
    assert rda["Vitamin D"] == 20
    assert rda["Iron"] == 18
    assert rda["Calcium"] == 1300
    assert rda["Vitamin B-12"] == 2.4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `pydantic_core._pydantic_core.ValidationError` (extra field `rda` not
permitted is not the failure yet; first it fails because `get_tunables()` raises a
validation error once we add `rda:` to the YAML in step 3 before updating the model —
so actually run this *after* step 3's YAML edit but *before* step 4's model edit, to see:
`Extra inputs are not permitted` for `nutrient_checkup.rda`). To keep ordering simple,
do step 3 (YAML) first, then run this test now — it should FAIL with the extra-field
error described above.

- [ ] **Step 3: Add the `rda` section to tunables.yaml**

In `src/backend/config/tunables.yaml`, immediately after the `flat_threshold_pct: 0.05`
line (end of the `nutrient_checkup:` section, before `routing:`), add:

```yaml

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

- [ ] **Step 4: Run the test again to confirm the extra-field failure**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `pydantic_core._pydantic_core.ValidationError` mentioning
`nutrient_checkup.rda` and "Extra inputs are not permitted".

- [ ] **Step 5: Add `rda` to `NutrientCheckupConfig`**

In `src/backend/config/__init__.py`, change:

```python
class NutrientCheckupConfig(BaseModel):
    """USDA nutrient map + trend threshold for the Daily Nutrient Check-up."""

    micronutrients: dict[str, MicronutrientConfig]
    flat_threshold_pct: float = Field(ge=0.0, le=1.0)

    model_config = ConfigDict(extra="forbid")
```

to:

```python
class NutrientCheckupConfig(BaseModel):
    """USDA nutrient map + trend threshold + RDA baseline for the Check-up."""

    micronutrients: dict[str, MicronutrientConfig]
    flat_threshold_pct: float = Field(ge=0.0, le=1.0)
    rda: dict[str, float]

    model_config = ConfigDict(extra="forbid")
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/backend/config/tunables.yaml src/backend/config/__init__.py tests/test_config.py
git commit -m "feat: add RDA baseline tunables for nutrient check-up"
```

---

## Task 2: `rda_pct` + `summarize_nutrient_checkup` in `agent/tools/history.py`

**Files:**
- Modify: `src/backend/agent/tools/history.py` (module constants + `get_nutrient_checkup_aggregates` + new `summarize_nutrient_checkup`)
- Test: `tests/test_history.py`

- [ ] **Step 1: Write failing tests for `rda_pct`**

In `tests/test_history.py`, extend `test_nutrient_checkup_computes_averages_and_trend` by
adding these assertions at the end of the test:

```python
    # rda_pct = avg / RDA * 100. Protein avg=100, RDA=50 -> 200%.
    assert result["Protein"]["rda_pct"] == pytest.approx(200.0)
    # Fiber avg=20, RDA=28 -> ~71.4%.
    assert result["Fiber"]["rda_pct"] == pytest.approx(100.0 * 20.0 / 28.0)
    # Sugar avg=100, RDA=50 -> 200%.
    assert result["Sugar"]["rda_pct"] == pytest.approx(200.0)
```

Also extend `test_nutrient_checkup_handles_missing_data` by adding:

```python
    # Zero avg -> rda_pct is 0, not None (RDA itself is never 0).
    assert result["Protein"]["rda_pct"] == pytest.approx(0.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_history.py -v -k nutrient_checkup`
Expected: FAIL — `KeyError: 'rda_pct'`

- [ ] **Step 3: Add `_CHECKUP_RDA` constant and `rda_pct` to both loops**

In `src/backend/agent/tools/history.py`, near the top where `_CHECKUP_MICRONUTRIENTS` and
`_CHECKUP_FLAT_THRESHOLD` are defined, add:

```python
_CHECKUP_RDA = _TUNABLES.nutrient_checkup.rda
```

Then update `get_nutrient_checkup_aggregates`'s two loops to add `rda_pct`. The macro loop
becomes:

```python
    for display_name, (field, unit) in _CHECKUP_MACROS.items():
        cur_avg = cur_macros[field] / 7
        prev_avg = prev_macros[field] / 7
        trend_pct, direction = _trend(cur_avg, prev_avg)
        rda = _CHECKUP_RDA[display_name]
        rda_pct = (cur_avg / rda) * 100 if rda else None
        result[display_name] = {
            "avg": cur_avg,
            "prev_avg": prev_avg,
            "unit": unit,
            "trend_pct": trend_pct,
            "direction": direction,
            "rda_pct": rda_pct,
        }
```

And the micronutrient loop becomes:

```python
    for display_name, micro_cfg in _CHECKUP_MICRONUTRIENTS.items():
        cur_entry = cur_micro.get(micro_cfg.usda_name)
        prev_entry = prev_micro.get(micro_cfg.usda_name)
        cur_avg = float(cur_entry["amount"]) / 7 if cur_entry else 0.0
        prev_avg = float(prev_entry["amount"]) / 7 if prev_entry else 0.0
        entry_with_unit = cur_entry or prev_entry
        unit = str(entry_with_unit["unit"]) if entry_with_unit else micro_cfg.unit
        trend_pct, direction = _trend(cur_avg, prev_avg)
        rda = _CHECKUP_RDA[display_name]
        rda_pct = (cur_avg / rda) * 100 if rda else None
        result[display_name] = {
            "avg": cur_avg,
            "prev_avg": prev_avg,
            "unit": unit,
            "trend_pct": trend_pct,
            "direction": direction,
            "rda_pct": rda_pct,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_history.py -v -k nutrient_checkup`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/backend/agent/tools/history.py tests/test_history.py
git commit -m "feat: add rda_pct to nutrient check-up aggregates"
```

- [ ] **Step 6: Write failing tests for `summarize_nutrient_checkup`**

Add this new section at the end of `tests/test_history.py`:

```python
# ---------------------------------------------------------------------------
# summarize_nutrient_checkup
# ---------------------------------------------------------------------------


def _item(rda_pct: float) -> dict[str, float | str | None]:
    return {
        "avg": 0.0,
        "prev_avg": 0.0,
        "unit": "g",
        "trend_pct": None,
        "direction": "flat",
        "rda_pct": rda_pct,
    }


def test_summarize_nutrient_checkup_returns_none_when_nothing_notable():
    nutrients = {"Protein": _item(100.0), "Fiber": _item(120.0)}

    notable, summary_text = summarize_nutrient_checkup(nutrients)

    assert notable == []
    assert summary_text is None


def test_summarize_nutrient_checkup_single_under_target():
    nutrients = {"Protein": _item(100.0), "Fiber": _item(50.0)}

    notable, summary_text = summarize_nutrient_checkup(nutrients)

    assert notable == [{"name": "Fiber", "rda_pct": 50.0, "status": "under"}]
    assert summary_text == (
        "This week, your Fiber intake is at 50% of the daily target — "
        "consider eating more whole grains, legumes, or vegetables."
    )


def test_summarize_nutrient_checkup_single_over_target():
    nutrients = {"Protein": _item(100.0), "Sugar": _item(220.0)}

    notable, summary_text = summarize_nutrient_checkup(nutrients)

    assert notable == [{"name": "Sugar", "rda_pct": 220.0, "status": "over"}]
    assert summary_text == (
        "This week, your Sugar intake is at 220% of the daily target — "
        "you're well above the daily target."
    )


def test_summarize_nutrient_checkup_top_two_by_distance_from_100():
    # Distances from 100: Fiber=50, Iron=10, Sugar=70. Top 2 -> Sugar, Fiber.
    nutrients = {
        "Fiber": _item(50.0),
        "Iron": _item(110.0),
        "Sugar": _item(170.0),
    }

    notable, summary_text = summarize_nutrient_checkup(nutrients)

    assert [item["name"] for item in notable] == ["Sugar", "Fiber"]
    assert summary_text == (
        "This week: Sugar is at 170% and Fiber is at 50% of their daily "
        "targets — let's bring these closer to your daily targets."
    )


def test_summarize_nutrient_checkup_two_under_target_combines_hints():
    nutrients = {"Fiber": _item(50.0), "Protein": _item(40.0)}

    notable, summary_text = summarize_nutrient_checkup(nutrients)

    assert [item["name"] for item in notable] == ["Protein", "Fiber"]
    assert summary_text == (
        "This week: Protein is at 40% and Fiber is at 50% of their daily "
        "targets — consider eating more lean meat, eggs, beans, or dairy "
        "and whole grains, legumes, or vegetables."
    )


def test_summarize_nutrient_checkup_ignores_none_rda_pct():
    nutrients = {"Protein": _item(None), "Fiber": _item(50.0)}

    notable, summary_text = summarize_nutrient_checkup(nutrients)

    assert [item["name"] for item in notable] == ["Fiber"]
    assert summary_text is not None
```

Add `summarize_nutrient_checkup` to the import at the top of `tests/test_history.py`:

```python
from backend.agent.tools.history import (
    get_food_breakdown_for_range,
    get_history,
    get_macros_for_range,
    get_micronutrients_for_range,
    get_nutrient_checkup_aggregates,
    summarize_nutrient_checkup,
)
```

- [ ] **Step 7: Run tests to verify they fail**

Run: `pytest tests/test_history.py -v -k summarize`
Expected: FAIL — `ImportError: cannot import name 'summarize_nutrient_checkup'`

- [ ] **Step 8: Implement `summarize_nutrient_checkup`**

Add this near the bottom of `src/backend/agent/tools/history.py`, after
`get_nutrient_checkup_aggregates`:

```python
_NOTABLE_UNDER_THRESHOLD = 70.0
_NOTABLE_OVER_THRESHOLD = 150.0

_NUTRIENT_FOOD_HINTS: dict[str, str] = {
    "Protein": "lean meat, eggs, beans, or dairy",
    "Fiber": "whole grains, legumes, or vegetables",
    "Vitamin C": "citrus fruits, berries, or peppers",
    "Vitamin D": "fatty fish, eggs, or fortified foods",
    "Iron": "red meat, spinach, or legumes",
    "Calcium": "dairy, leafy greens, or fortified plant milk",
    "Vitamin B-12": "meat, fish, eggs, or dairy",
}


def _phrase_for(item: dict[str, float | str]) -> str:
    """Return the "why" clause for a single notable nutrient."""
    if item["status"] == "over":
        return "you're well above the daily target"
    hint = _NUTRIENT_FOOD_HINTS.get(str(item["name"]))
    if hint:
        return f"consider eating more {hint}"
    return "consider eating more of this nutrient"


def _combined_phrase(items: list[dict[str, float | str]]) -> str:
    """Return the "why" clause for two notable nutrients."""
    statuses = {item["status"] for item in items}
    if statuses == {"under"}:
        hints = [
            _NUTRIENT_FOOD_HINTS[str(item["name"])]
            for item in items
            if str(item["name"]) in _NUTRIENT_FOOD_HINTS
        ]
        if hints:
            return "consider eating more " + " and ".join(hints)
        return "consider eating more of these nutrients"
    if statuses == {"over"}:
        return "you're well above the daily targets for these"
    return "let's bring these closer to your daily targets"


def summarize_nutrient_checkup(
    nutrients: dict[str, dict[str, float | str | None]],
) -> tuple[list[dict[str, float | str]], str | None]:
    """Build a one-line summary of nutrients notably off their RDA targets.

    A nutrient is "notable" if its `rda_pct` is below
    `_NOTABLE_UNDER_THRESHOLD` (under-target) or above
    `_NOTABLE_OVER_THRESHOLD` (over-target). The top 2 notable nutrients,
    ranked by distance from 100%, drive a deterministic template summary.

    Args:
        nutrients: Output of `get_nutrient_checkup_aggregates`, keyed by
            display name, each with an `rda_pct` (float or None).

    Returns:
        A tuple of (notable nutrients, summary text). `notable` is a list of
        dicts with `name`, `rda_pct`, and `status` ("under" or "over").
        `summary_text` is None when nothing is notable.
    """
    notable: list[dict[str, float | str]] = []
    for name, values in nutrients.items():
        rda_pct = values["rda_pct"]
        if rda_pct is None:
            continue
        rda_pct = float(rda_pct)
        if rda_pct < _NOTABLE_UNDER_THRESHOLD:
            notable.append({"name": name, "rda_pct": rda_pct, "status": "under"})
        elif rda_pct > _NOTABLE_OVER_THRESHOLD:
            notable.append({"name": name, "rda_pct": rda_pct, "status": "over"})

    if not notable:
        return [], None

    notable.sort(key=lambda item: abs(float(item["rda_pct"]) - 100.0), reverse=True)
    top = notable[:2]

    if len(top) == 1:
        item = top[0]
        summary_text = (
            f"This week, your {item['name']} intake is at "
            f"{item['rda_pct']:.0f}% of the daily target — {_phrase_for(item)}."
        )
    else:
        first, second = top
        phrase = _combined_phrase(top)
        summary_text = (
            f"This week: {first['name']} is at {first['rda_pct']:.0f}% and "
            f"{second['name']} is at {second['rda_pct']:.0f}% of their daily "
            f"targets — {phrase}."
        )

    return top, summary_text
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `pytest tests/test_history.py -v -k "summarize or nutrient_checkup"`
Expected: PASS (all)

- [ ] **Step 10: Commit**

```bash
git add src/backend/agent/tools/history.py tests/test_history.py
git commit -m "feat: add summarize_nutrient_checkup helper for RDA-based summaries"
```

---

## Task 3: Schema migration + `NutrientCheckup` model columns

**Files:**
- Create: `src/backend/db/migrations/versions/20260615_005_nutrient_summary.py`
- Modify: `src/backend/db/models.py:250-280` (`NutrientCheckup`)

- [ ] **Step 1: Create the migration file**

Run: `cd src/backend && uv run alembic revision -m "nutrient_summary" --rev-id 005` —
**actually skip this** (it generates a timestamp-prefixed name that doesn't match this
repo's `YYYYMMDD_NNN_name.py` convention). Instead, create the file directly at
`src/backend/db/migrations/versions/20260615_005_nutrient_summary.py`:

```python
"""Daily Nutrient Summary vs RDA Baseline.

Adds notable_nutrients/summary_text (generated nightly alongside the existing
nutrient_checkup aggregates) and telegram_sent_at/chat_nudge_seen_at
(delivery-tracking for the Telegram push and chat nudge) to nutrient_checkup.

Revision ID: 005
Revises: 004
Create Date: 2026-06-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "nutrient_checkup",
        sa.Column(
            "notable_nutrients", JSONB(), nullable=False, server_default="[]"
        ),
    )
    op.add_column(
        "nutrient_checkup",
        sa.Column("summary_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "nutrient_checkup",
        sa.Column("telegram_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "nutrient_checkup",
        sa.Column("chat_nudge_seen_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("nutrient_checkup", "chat_nudge_seen_at")
    op.drop_column("nutrient_checkup", "telegram_sent_at")
    op.drop_column("nutrient_checkup", "summary_text")
    op.drop_column("nutrient_checkup", "notable_nutrients")
```

- [ ] **Step 2: Add the new columns to the `NutrientCheckup` model**

In `src/backend/db/models.py`, change the `NutrientCheckup` class from:

```python
class NutrientCheckup(Base):
    __tablename__ = "nutrient_checkup"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("user_goal.user_id", ondelete="CASCADE"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    nutrients: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_nutrient_checkup_user_date"),
        Index("ix_nutrient_checkup_user_date", "user_id", "date"),
    )
```

to:

```python
class NutrientCheckup(Base):
    __tablename__ = "nutrient_checkup"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("user_goal.user_id", ondelete="CASCADE"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    nutrients: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    notable_nutrients: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    telegram_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    chat_nudge_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_nutrient_checkup_user_date"),
        Index("ix_nutrient_checkup_user_date", "user_id", "date"),
    )
```

- [ ] **Step 3: Apply the migration to the database**

Run: `uv run --env-file .env alembic -c src/backend/db/migrations/alembic.ini upgrade head`
(adjust the `-c` path if the repo's alembic.ini lives elsewhere — check with
`find src/backend/db/migrations -name alembic.ini`)

Expected: migration `005` applies cleanly; `\d nutrient_checkup` (via psql or the Supabase
MCP `list_tables`) shows the 4 new columns.

- [ ] **Step 4: Commit**

```bash
git add src/backend/db/migrations/versions/20260615_005_nutrient_summary.py src/backend/db/models.py
git commit -m "feat: add nutrient_checkup summary + delivery-tracking columns"
```

---

## Task 4: Persist `notable_nutrients`/`summary_text` in `_build_nutrient_checkup`

**Files:**
- Modify: `src/backend/workers/tasks.py:377-405` (`_build_nutrient_checkup`)
- Test: `tests/test_tasks.py` (new file — check if it exists first)

- [ ] **Step 1: Check for an existing tasks test file**

Run: `ls tests/test_tasks.py 2>/dev/null || echo "no existing file"`

If it exists, read it first to match its mocking conventions before adding the test
below. If not, create `tests/test_tasks.py` with the test in the next step plus this
header:

```python
from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_session_factory(session: MagicMock) -> MagicMock:
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=session)
```

- [ ] **Step 2: Write the failing test**

Add to `tests/test_tasks.py`:

```python
@pytest.mark.asyncio
async def test_build_nutrient_checkup_persists_summary_fields():
    from backend.workers.tasks import _build_nutrient_checkup

    user_row = MagicMock(user_id="user-1")
    users_result = MagicMock()
    users_result.all.return_value = [user_row]

    session = MagicMock()
    session.execute = AsyncMock(return_value=users_result)
    session.commit = AsyncMock()
    factory = _mock_session_factory(session)

    nutrients = {
        "Protein": {
            "avg": 20.0,
            "prev_avg": 20.0,
            "unit": "g",
            "trend_pct": 0.0,
            "direction": "flat",
            "rda_pct": 40.0,
        },
    }
    notable = [{"name": "Protein", "rda_pct": 40.0, "status": "under"}]
    summary_text = (
        "This week, your Protein intake is at 40% of the daily target — "
        "consider eating more lean meat, eggs, beans, or dairy."
    )

    with (
        patch("backend.workers.tasks.get_session", return_value=factory),
        patch(
            "backend.workers.tasks.get_nutrient_checkup_aggregates",
            new_callable=AsyncMock,
            return_value=nutrients,
        ),
        patch(
            "backend.workers.tasks.summarize_nutrient_checkup",
            return_value=(notable, summary_text),
        ),
    ):
        await _build_nutrient_checkup(date(2026, 6, 14))

    # Second execute call is the upsert; inspect its compiled parameters.
    upsert_call = session.execute.call_args_list[1]
    stmt = upsert_call[0][0]
    compiled = stmt.compile()
    params = compiled.params
    assert params["notable_nutrients"] == notable
    assert params["summary_text"] == summary_text
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_tasks.py -v -k summary_fields`
Expected: FAIL — `KeyError: 'notable_nutrients'` (the upsert doesn't set these columns yet)

- [ ] **Step 4: Update `_build_nutrient_checkup`**

In `src/backend/workers/tasks.py`, change:

```python
        for user_id in user_ids:
            nutrients = await get_nutrient_checkup_aggregates(user_id, target_date)

            stmt = pg_insert(NutrientCheckup).values(
                user_id=user_id,
                date=target_date,
                nutrients=nutrients,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["user_id", "date"],
                set_={
                    "nutrients": stmt.excluded.nutrients,
                    "generated_at": func.now(),
                },
            )
            await session.execute(stmt)
```

to:

```python
        for user_id in user_ids:
            nutrients = await get_nutrient_checkup_aggregates(user_id, target_date)
            notable, summary_text = summarize_nutrient_checkup(nutrients)

            stmt = pg_insert(NutrientCheckup).values(
                user_id=user_id,
                date=target_date,
                nutrients=nutrients,
                notable_nutrients=notable,
                summary_text=summary_text,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["user_id", "date"],
                set_={
                    "nutrients": stmt.excluded.nutrients,
                    "notable_nutrients": stmt.excluded.notable_nutrients,
                    "summary_text": stmt.excluded.summary_text,
                    "generated_at": func.now(),
                },
            )
            await session.execute(stmt)
```

Then add `summarize_nutrient_checkup` to the existing import of
`get_nutrient_checkup_aggregates`:

```python
from backend.agent.tools.history import (
    get_nutrient_checkup_aggregates,
    summarize_nutrient_checkup,
)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_tasks.py -v -k summary_fields`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/backend/workers/tasks.py tests/test_tasks.py
git commit -m "feat: persist notable_nutrients/summary_text in nutrient checkup"
```

---

## Task 5: Telegram daily summary push

**Files:**
- Modify: `src/backend/workers/tasks.py` (imports, `beat_schedule`, new task)
- Test: `tests/test_tasks.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_tasks.py`:

```python
@pytest.mark.asyncio
async def test_send_daily_summary_telegram_sends_and_marks_sent():
    from backend.workers.tasks import _send_daily_summary_telegram

    row = MagicMock(chat_id=123456, user_id="user-1", summary_text="Eat more fiber!")
    select_result = MagicMock()
    select_result.all.return_value = [row]

    session = MagicMock()
    session.execute = AsyncMock(return_value=select_result)
    session.commit = AsyncMock()
    factory = _mock_session_factory(session)

    bot = MagicMock()
    bot.send_message = AsyncMock()
    bot.__aenter__ = AsyncMock(return_value=bot)
    bot.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("backend.workers.tasks.get_session", return_value=factory),
        patch("backend.workers.tasks.build_bot", return_value=bot),
    ):
        await _send_daily_summary_telegram(date(2026, 6, 14))

    bot.send_message.assert_awaited_once_with(123456, "Eat more fiber!")
    # Second execute call is the UPDATE marking telegram_sent_at.
    update_call = session.execute.call_args_list[1]
    stmt = str(update_call[0][0])
    assert "telegram_sent_at" in stmt
    session.commit.assert_awaited()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tasks.py -v -k send_daily_summary`
Expected: FAIL — `ImportError: cannot import name '_send_daily_summary_telegram'`

- [ ] **Step 3: Implement the task**

In `src/backend/workers/tasks.py`, add to imports:

```python
from backend.telegram.bot import build_bot
```

Add to `beat_schedule` (after `build-nutrient-checkup`):

```python
    "send-daily-summary-telegram": {
        "task": "backend.workers.tasks.send_daily_summary_telegram",
        "schedule": crontab(hour=7, minute=0),
    },
```

Add a new section at the end of the file, before `__all__`:

```python
# ---------------------------------------------------------------------------
# send_daily_summary_telegram
# ---------------------------------------------------------------------------


async def _send_daily_summary_telegram(target_date: date) -> None:
    session_factory = get_session()
    async with session_factory() as session:
        result = await session.execute(
            sa_text(
                "SELECT tl.chat_id, nc.user_id, nc.summary_text "
                "FROM nutrient_checkup nc "
                "JOIN telegram_link tl ON tl.user_id = nc.user_id "
                "WHERE nc.date = :target_date "
                "AND nc.summary_text IS NOT NULL "
                "AND nc.telegram_sent_at IS NULL"
            ),
            {"target_date": target_date},
        )
        rows = result.all()

        async with build_bot() as bot:
            for row in rows:
                await bot.send_message(row.chat_id, row.summary_text)
                await session.execute(
                    sa_text(
                        "UPDATE nutrient_checkup SET telegram_sent_at = now() "
                        "WHERE user_id = :user_id AND date = :target_date"
                    ),
                    {"user_id": row.user_id, "target_date": target_date},
                )
        await session.commit()


@celery_app.task(name="backend.workers.tasks.send_daily_summary_telegram")
def send_daily_summary_telegram(target_date: str | None = None) -> None:
    """Send the daily nutrient summary to linked Telegram chats.

    Runs at 07:00 (after the 01:30 build_nutrient_checkup), for any user
    whose `nutrient_checkup` row for `target_date` has a non-null
    `summary_text` and hasn't been sent yet.

    Args:
        target_date: ISO date string for the check-up date to send.
            Defaults to yesterday (the date build_nutrient_checkup just
            computed).
    """
    resolved = (
        date.fromisoformat(target_date)
        if target_date
        else date.today() - timedelta(days=1)
    )
    _run(_send_daily_summary_telegram(resolved))
```

Add `"send_daily_summary_telegram"` to `__all__`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tasks.py -v -k send_daily_summary`
Expected: PASS

- [ ] **Step 5: Run the full backend test suite**

Run: `pytest tests/ -v`
Expected: PASS (no regressions)

- [ ] **Step 6: Commit**

```bash
git add src/backend/workers/tasks.py tests/test_tasks.py
git commit -m "feat: send daily nutrient summary via Telegram"
```

---

## Task 6: Dashboard API — extend `/nutrient-checkup` response

**Files:**
- Modify: `src/backend/api/nutrient_checkup.py`
- Test: `tests/test_nutrient_checkup_api.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_nutrient_checkup_api.py`, update `test_get_nutrient_checkup_returns_latest_row`
by adding `rda_pct` to each nutrient in `row.nutrients` and the two new top-level fields to
the `NutrientCheckup(...)` construction:

```python
def test_get_nutrient_checkup_returns_latest_row(client: TestClient) -> None:
    row = NutrientCheckup(
        id="ck-1",
        user_id="user-1",
        date=date(2026, 6, 14),
        nutrients={
            "Protein": {
                "avg": 100.0,
                "prev_avg": 90.0,
                "unit": "g",
                "trend_pct": 0.111,
                "direction": "up",
                "rda_pct": 200.0,
            },
            "Vitamin C": {
                "avg": 0.0,
                "prev_avg": 0.0,
                "unit": "mg",
                "trend_pct": None,
                "direction": "flat",
                "rda_pct": 0.0,
            },
        },
        notable_nutrients=[
            {"name": "Protein", "rda_pct": 200.0, "status": "over"},
        ],
        summary_text=(
            "This week, your Protein intake is at 200% of the daily target — "
            "you're well above the daily target."
        ),
        generated_at=datetime(2026, 6, 15, 1, 30, tzinfo=timezone.utc),
    )

    session = MagicMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = row
    session.execute = AsyncMock(return_value=exec_result)
    factory = _mock_session_factory(session)

    with patch("backend.api.nutrient_checkup.get_session", return_value=factory):
        resp = client.get("/nutrient-checkup", headers=_auth_headers("user-1"))

    assert resp.status_code == 200
    body = resp.json()
    assert body["date"] == "2026-06-14"
    by_name = {item["name"]: item for item in body["nutrients"]}
    assert by_name["Protein"]["avg"] == 100.0
    assert by_name["Protein"]["direction"] == "up"
    assert by_name["Protein"]["rda_pct"] == 200.0
    assert by_name["Vitamin C"]["trend_pct"] is None
    assert body["notable"] == ["Protein"]
    assert body["summary_text"] == row.summary_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_nutrient_checkup_api.py -v -k returns_latest_row`
Expected: FAIL — `pydantic_core._pydantic_core.ValidationError` (extra field `rda_pct` not
permitted on `NutrientCheckupItem`, since `model_config = extra="forbid"`)

- [ ] **Step 3: Extend the response models and endpoint**

In `src/backend/api/nutrient_checkup.py`, change:

```python
class NutrientCheckupItem(BaseModel):
    """One nutrient's rolling 7-day average and trend vs the prior week."""

    name: str
    avg: float
    prev_avg: float
    unit: str
    trend_pct: float | None
    direction: str

    model_config = ConfigDict(extra="forbid")


class NutrientCheckupResponse(BaseModel):
    date: date
    nutrients: list[NutrientCheckupItem]
    generated_at: datetime

    model_config = ConfigDict(extra="forbid")
```

to:

```python
class NutrientCheckupItem(BaseModel):
    """One nutrient's rolling 7-day average, trend, and RDA comparison."""

    name: str
    avg: float
    prev_avg: float
    unit: str
    trend_pct: float | None
    direction: str
    rda_pct: float | None

    model_config = ConfigDict(extra="forbid")


class NutrientCheckupResponse(BaseModel):
    date: date
    nutrients: list[NutrientCheckupItem]
    generated_at: datetime
    notable: list[str]
    summary_text: str | None

    model_config = ConfigDict(extra="forbid")
```

Then change the `get_nutrient_checkup` return statement from:

```python
    return NutrientCheckupResponse(
        date=row.date,
        generated_at=row.generated_at,
        nutrients=[
            NutrientCheckupItem(name=name, **values)
            for name, values in row.nutrients.items()
        ],
    )
```

to:

```python
    return NutrientCheckupResponse(
        date=row.date,
        generated_at=row.generated_at,
        nutrients=[
            NutrientCheckupItem(name=name, **values)
            for name, values in row.nutrients.items()
        ],
        notable=[item["name"] for item in row.notable_nutrients],
        summary_text=row.summary_text,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_nutrient_checkup_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/backend/api/nutrient_checkup.py tests/test_nutrient_checkup_api.py
git commit -m "feat: expose rda_pct, notable nutrients, and summary in nutrient-checkup API"
```

---

## Task 7: Chat nudge endpoints

**Files:**
- Modify: `src/backend/api/nutrient_checkup.py`
- Test: `tests/test_nutrient_checkup_api.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_nutrient_checkup_api.py`:

```python
def test_pending_nudge_returns_summary_when_unseen(client: TestClient) -> None:
    row = NutrientCheckup(
        id="ck-1",
        user_id="user-1",
        date=date(2026, 6, 14),
        nutrients={},
        notable_nutrients=[{"name": "Fiber", "rda_pct": 50.0, "status": "under"}],
        summary_text="This week, your Fiber intake is at 50% of the daily target.",
        chat_nudge_seen_at=None,
        generated_at=datetime(2026, 6, 15, 1, 30, tzinfo=timezone.utc),
    )

    session = MagicMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = row
    session.execute = AsyncMock(return_value=exec_result)
    factory = _mock_session_factory(session)

    with patch("backend.api.nutrient_checkup.get_session", return_value=factory):
        resp = client.get(
            "/nutrient-checkup/pending-nudge", headers=_auth_headers("user-1")
        )

    assert resp.status_code == 200
    assert resp.json() == {"summary_text": row.summary_text}


def test_pending_nudge_returns_none_when_already_seen(client: TestClient) -> None:
    row = NutrientCheckup(
        id="ck-1",
        user_id="user-1",
        date=date(2026, 6, 14),
        nutrients={},
        notable_nutrients=[],
        summary_text="This week, your Fiber intake is at 50% of the daily target.",
        chat_nudge_seen_at=datetime(2026, 6, 15, 8, 0, tzinfo=timezone.utc),
        generated_at=datetime(2026, 6, 15, 1, 30, tzinfo=timezone.utc),
    )

    session = MagicMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = row
    session.execute = AsyncMock(return_value=exec_result)
    factory = _mock_session_factory(session)

    with patch("backend.api.nutrient_checkup.get_session", return_value=factory):
        resp = client.get(
            "/nutrient-checkup/pending-nudge", headers=_auth_headers("user-1")
        )

    assert resp.status_code == 200
    assert resp.json() == {"summary_text": None}


def test_pending_nudge_returns_none_when_no_row(client: TestClient) -> None:
    session = MagicMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=exec_result)
    factory = _mock_session_factory(session)

    with patch("backend.api.nutrient_checkup.get_session", return_value=factory):
        resp = client.get(
            "/nutrient-checkup/pending-nudge", headers=_auth_headers("user-1")
        )

    assert resp.status_code == 200
    assert resp.json() == {"summary_text": None}


def test_pending_nudge_ack_marks_seen(client: TestClient) -> None:
    session = MagicMock()
    exec_result = MagicMock()
    session.execute = AsyncMock(return_value=exec_result)
    session.commit = AsyncMock()
    factory = _mock_session_factory(session)

    with patch("backend.api.nutrient_checkup.get_session", return_value=factory):
        resp = client.post(
            "/nutrient-checkup/pending-nudge/ack", headers=_auth_headers("user-1")
        )

    assert resp.status_code == 204
    stmt = str(session.execute.call_args[0][0])
    assert "chat_nudge_seen_at" in stmt
    session.commit.assert_awaited()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_nutrient_checkup_api.py -v -k pending_nudge`
Expected: FAIL — `404 Not Found` (routes don't exist yet)

- [ ] **Step 3: Implement the endpoints**

In `src/backend/api/nutrient_checkup.py`, add after the existing `NutrientCheckupResponse`
class:

```python
class PendingNudgeResponse(BaseModel):
    summary_text: str | None

    model_config = ConfigDict(extra="forbid")
```

Add `Response` and `status` to the FastAPI import:

```python
from fastapi import APIRouter, Depends, HTTPException, Response, status
```

Add `sa_text` import (matches `tasks.py`'s convention):

```python
from sqlalchemy import text as sa_text
```

Add two new routes at the end of the file:

```python
@router.get("/pending-nudge")
async def get_pending_nudge(
    user_id: str = Depends(get_current_user_id),
) -> PendingNudgeResponse:
    """Return the most recent unseen daily summary, if any.

    Returns `{summary_text: null}` if there's no nutrient-checkup row yet,
    the most recent row has already been acknowledged
    (`chat_nudge_seen_at` is set), or it has no `summary_text`.
    """
    session_factory = get_session()
    async with session_factory() as session:
        result = await session.execute(
            select(NutrientCheckup)
            .where(NutrientCheckup.user_id == user_id)
            .order_by(NutrientCheckup.date.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()

    if row is None or row.chat_nudge_seen_at is not None:
        return PendingNudgeResponse(summary_text=None)

    return PendingNudgeResponse(summary_text=row.summary_text)


@router.post("/pending-nudge/ack", status_code=status.HTTP_204_NO_CONTENT)
async def ack_pending_nudge(
    user_id: str = Depends(get_current_user_id),
) -> Response:
    """Mark the most recent nutrient-checkup row's nudge as seen."""
    session_factory = get_session()
    async with session_factory() as session:
        await session.execute(
            sa_text(
                "UPDATE nutrient_checkup SET chat_nudge_seen_at = now() "
                "WHERE user_id = :user_id "
                "AND date = (SELECT MAX(date) FROM nutrient_checkup WHERE user_id = :user_id)"
            ),
            {"user_id": user_id},
        )
        await session.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_nutrient_checkup_api.py -v`
Expected: PASS (all)

- [ ] **Step 5: Run the full backend test suite**

Run: `pytest tests/ -v`
Expected: PASS (no regressions)

- [ ] **Step 6: Commit**

```bash
git add src/backend/api/nutrient_checkup.py tests/test_nutrient_checkup_api.py
git commit -m "feat: add pending-nudge endpoints for the daily nutrient summary"
```

---

## Task 8: Frontend types + hooks

**Files:**
- Modify: `frontend/src/api/types.ts:66-79`
- Modify: `frontend/src/api/hooks.ts`

- [ ] **Step 1: Extend the types**

In `frontend/src/api/types.ts`, change:

```typescript
export interface NutrientCheckupItem {
  name: string;
  avg: number;
  prev_avg: number;
  unit: string;
  trend_pct: number | null;
  direction: 'up' | 'down' | 'flat';
}

export interface NutrientCheckupResponse {
  date: string; // ISO date
  nutrients: NutrientCheckupItem[];
  generated_at: string;
}
```

to:

```typescript
export interface NutrientCheckupItem {
  name: string;
  avg: number;
  prev_avg: number;
  unit: string;
  trend_pct: number | null;
  direction: 'up' | 'down' | 'flat';
  rda_pct: number | null;
}

export interface NutrientCheckupResponse {
  date: string; // ISO date
  nutrients: NutrientCheckupItem[];
  generated_at: string;
  notable: string[];
  summary_text: string | null;
}

export interface PendingNudgeResponse {
  summary_text: string | null;
}
```

- [ ] **Step 2: Add hooks**

In `frontend/src/api/hooks.ts`, add `PendingNudgeResponse` to the type import:

```typescript
import type {
  DayTrend,
  LogMealRequest,
  LogMealResponse,
  TodayTotals,
  GoalData,
  NutrientCheckupResponse,
  PendingNudgeResponse,
  TelegramLinkCode,
  TelegramLinkStatus,
} from './types'
```

Add two new hooks after `useNutrientCheckup`:

```typescript
export const usePendingNudge = () => {
  return useQuery<PendingNudgeResponse, ApiError>({
    queryKey: ['nutrient-checkup', 'pending-nudge'],
    queryFn: () => apiClient.get<PendingNudgeResponse>('/nutrient-checkup/pending-nudge'),
    staleTime: Infinity,
    retry: (failureCount, error) => {
      if (error.status === 404) return false
      return failureCount < 3
    },
  })
}

export const useAckPendingNudge = () => {
  return useMutation<void, Error, void>({
    mutationFn: () => apiClient.post<void>('/nutrient-checkup/pending-nudge/ack'),
  })
}
```

- [ ] **Step 3: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/hooks.ts
git commit -m "feat: add types and hooks for nutrient summary + pending nudge"
```

---

## Task 9: `NutrientCheckupCard` — summary intro + RDA tick

**Files:**
- Modify: `frontend/src/components/dashboard/NutrientCheckupCard.tsx`

- [ ] **Step 1: Add the RDA tick to `NutrientBar`**

In `frontend/src/components/dashboard/NutrientCheckupCard.tsx`, change the `NutrientBar`
function from:

```typescript
/** Horizontal bar for this week's average, with a tick marking last week's average. */
function NutrientBar({ item, color }: { item: NutrientCheckupItem; color: string }) {
  const max = Math.max(item.avg, item.prev_avg, 1e-6)
  const avgPct = Math.min(100, (item.avg / max) * 100)
  const prevPct = Math.min(100, (item.prev_avg / max) * 100)

  return (
    <div className="relative h-1.5 rounded-full bg-[var(--color-sand-border)] overflow-hidden">
      <div
        className="absolute inset-y-0 left-0 rounded-full transition-[width] duration-300"
        style={{ width: `${avgPct}%`, background: color }}
      />
      {item.prev_avg > 0 && (
        <div
          className="absolute inset-y-0 w-px bg-ink-soft/50"
          style={{ left: `${prevPct}%` }}
          title="Last week's average"
        />
      )}
    </div>
  )
}
```

to:

```typescript
/**
 * Horizontal bar for this week's average, with ticks marking last week's
 * average and the daily RDA target.
 */
function NutrientBar({ item, color }: { item: NutrientCheckupItem; color: string }) {
  const rdaAmount =
    item.rda_pct !== null && item.rda_pct > 0 && item.avg > 0
      ? item.avg / (item.rda_pct / 100)
      : null
  const max = Math.max(item.avg, item.prev_avg, rdaAmount ?? 1e-6)
  const avgPct = Math.min(100, (item.avg / max) * 100)
  const prevPct = Math.min(100, (item.prev_avg / max) * 100)
  const rdaPct = rdaAmount !== null ? Math.min(100, (rdaAmount / max) * 100) : null

  return (
    <div className="relative h-1.5 rounded-full bg-[var(--color-sand-border)] overflow-hidden">
      <div
        className="absolute inset-y-0 left-0 rounded-full transition-[width] duration-300"
        style={{ width: `${avgPct}%`, background: color }}
      />
      {item.prev_avg > 0 && (
        <div
          className="absolute inset-y-0 w-px bg-ink-soft/50"
          style={{ left: `${prevPct}%` }}
          title="Last week's average"
        />
      )}
      {rdaPct !== null && (
        <div
          className="absolute inset-y-0 w-px bg-sage-deep/50"
          style={{ left: `${rdaPct}%` }}
          title="Daily recommended target"
        />
      )}
    </div>
  )
}
```

- [ ] **Step 2: Render `summary_text` as an intro paragraph**

Change the `NutrientCheckupCard` function from:

```typescript
export function NutrientCheckupCard() {
  const { data, isLoading, error } = useNutrientCheckup()

  if (isLoading) return null

  return (
    <section className="space-y-3">
      <h3 className="label-caps">Weekly Nutrient Check-up</h3>
      <div className="card-sand p-4">
        {error || !data || data.nutrients.length === 0 ? (
          <p className="text-sm text-muted">
            Log meals for a few days and your weekly nutrient averages will show up here.
          </p>
        ) : (
          <div className="divide-y divide-sand-border">
            {data.nutrients.map((item) => (
              <NutrientRow key={item.name} item={item} />
            ))}
          </div>
        )}
      </div>
    </section>
  )
}
```

to:

```typescript
export function NutrientCheckupCard() {
  const { data, isLoading, error } = useNutrientCheckup()

  if (isLoading) return null

  return (
    <section className="space-y-3">
      <h3 className="label-caps">Weekly Nutrient Check-up</h3>
      <div className="card-sand p-4">
        {error || !data || data.nutrients.length === 0 ? (
          <p className="text-sm text-muted">
            Log meals for a few days and your weekly nutrient averages will show up here.
          </p>
        ) : (
          <>
            {data.summary_text && (
              <p className="text-sm text-sage-deep mb-3">{data.summary_text}</p>
            )}
            <div className="divide-y divide-sand-border">
              {data.nutrients.map((item) => (
                <NutrientRow key={item.name} item={item} />
              ))}
            </div>
          </>
        )}
      </div>
    </section>
  )
}
```

- [ ] **Step 3: Type-check and lint**

Run: `cd frontend && npx tsc --noEmit && npx eslint src/`
Expected: no errors

- [ ] **Step 4: Visual check**

Start the dev server (`bash scripts/run-local.sh` or `cd frontend && npm run dev`) and use
Playwright to navigate to the dashboard. Confirm:
- A sage-deep intro sentence appears above the nutrient rows when `summary_text` is
  non-null (requires a user whose `nutrient_checkup` row has `summary_text` set — if none
  exists locally, this can be verified after Task 4's migration runs against a row with a
  notable nutrient, or by temporarily mocking the API response).
- Each `NutrientBar` shows up to two tick marks (last week in `ink-soft`, RDA target in
  `sage-deep`) without visually overlapping or breaking the rounded-bar layout.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/dashboard/NutrientCheckupCard.tsx
git commit -m "feat: show RDA target tick and weekly summary on nutrient check-up card"
```

---

## Task 10: Chat nudge on `ChatPage`

**Files:**
- Modify: `frontend/src/pages/ChatPage.tsx`

- [ ] **Step 1: Wire up the pending-nudge effect**

In `frontend/src/pages/ChatPage.tsx`, add imports:

```typescript
import { useEffect } from 'react'
import { useDashboard, useLogMeal, usePendingNudge, useAckPendingNudge } from '../api/hooks'
```

(Merge with the existing `import { useState } from 'react'` line — combine into
`import { useEffect, useState } from 'react'` — and the existing
`import { useDashboard, useLogMeal } from '../api/hooks'` line.)

Inside the `ChatPage` component, after the existing hook calls (`logMealMutation`,
`mobileTotalsOpen`, `dashboardWidth`/`onResizerPointerDown`), add:

```typescript
  const { data: pendingNudge } = usePendingNudge()
  const ackNudgeMutation = useAckPendingNudge()

  useEffect(() => {
    if (!pendingNudge?.summary_text || conversationId !== null) return
    addMessage({ sender: 'agent', text: pendingNudge.summary_text })
    ackNudgeMutation.mutate()
    // Only fire once per pending summary; ack makes subsequent fetches return null.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingNudge?.summary_text])
```

- [ ] **Step 2: Type-check and lint**

Run: `cd frontend && npx tsc --noEmit && npx eslint src/`
Expected: no errors

- [ ] **Step 3: Visual check**

With Playwright: for a user whose latest `nutrient_checkup` row has a non-null
`summary_text` and `chat_nudge_seen_at IS NULL`, load `/`. Confirm:
- The summary text appears as the first agent message in the chat thread.
- Reloading the page does not show it again (since `ack` set `chat_nudge_seen_at`).
- For a user with `conversationId` already set (an active paused thread), the nudge does
  NOT get prepended.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/ChatPage.tsx
git commit -m "feat: show one-time daily nutrient summary nudge in chat"
```

---

## Self-Review Notes

- **Spec §2** (RDA tunables) → Task 1.
- **Spec §3.1** (`rda_pct`) and **§3.2** (`summarize_nutrient_checkup`) → Task 2.
- **Spec §3.3** (`_build_nutrient_checkup` persistence) → Task 4.
- **Spec §3.4** (schema migration) → Task 3. Per spec, no special-casing for resetting
  `telegram_sent_at`/`chat_nudge_seen_at` on re-runs — left as-is (NULL on insert).
- **Spec §4** (dashboard) → Tasks 6, 8, 9.
- **Spec §5** (Telegram push) → Task 5.
- **Spec §6** (chat nudge) → Tasks 7, 8, 10.
- **Spec §7** (testing) → covered inline in each task's Steps.
- **Spec §8** (out of scope) → no tasks added for personalized RDA, LLM narrative,
  opt-outs, or no-telegram-link users — confirmed absent from this plan.

---

Plan complete and saved to `docs/superpowers/plans/2026-06-15-daily-nutrient-summary.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
