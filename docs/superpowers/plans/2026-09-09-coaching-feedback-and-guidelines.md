# Coaching Feedback Loop and Guideline Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist every coaching reply with its inputs, let web users rate replies up/down, and ground advice-type answers in retrieved, cited passages from curated public dietary guidelines filtered by the user's declared conditions.

**Architecture:** Two new Postgres tables (`guideline_chunk` with a pgvector column, `coaching_response`) plus a `user_goal.conditions` array. A new `backend.guidelines` package holds pure markdown chunking, an idempotent ingest CLI, a pgvector `retrieve()` and an export CLI. `coaching.py` gains a `needs_guidance` parse flag, a passage block in the response instructions, citation extraction, and returns a `CoachingResult`; the orchestrator persists it and returns `response_id`. A `/coaching/{id}/feedback` route and a `FeedbackButtons` component close the loop.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2 async, Alembic, pgvector, Pydantic AI (Gemini), Logfire/OpenTelemetry, pytest (`asyncio_mode = "auto"`), React 19, TanStack Query, Zustand, Vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-09-09-coaching-feedback-and-guidelines-design.md`

## Global Constraints

- Python: `from __future__ import annotations` in every file, Google-style docstrings, all functions type-annotated, 88-column lines, `black` + `ruff` defaults, never bare `except`.
- Pydantic models that cross a boundary use `model_config = ConfigDict(extra="forbid")`.
- All I/O is async; no blocking calls inside async code.
- TypeScript: no `any`; new files kebab-case (`feedback-buttons.tsx`, `use-coaching-feedback.ts`); 100-column lines.
- Migration revision id is exactly `"012"`, `down_revision = "011"`.
- `guideline_chunk.embedding` and query embeddings are 768-dim (`EMBEDDING_DIM`), IVFFlat cosine index, matching `user_memory`.
- Allowed `user_goal.conditions` values: `diabetes`, `prediabetes`, `hypertension`, `ckd`. Only `diabetes` and `prediabetes` map to retrieval tag `diabetes`; retrieval always includes tag `general`.
- Feedback rate limit: 60 requests per user per minute, via `backend.ratelimit.user_rate_limiter`.
- `rating_comment` max 500 chars. Feedback on unknown or another user's id returns 404 (same code for both).
- Retrieval failure and `coaching_response` write failure must never fail a coaching turn.
- Guideline source files live in `docs/guidelines/<source_id>.md`, 300-600 words each; the ADA file paraphrases (copyrighted source) and keeps section references.
- The `coaching` Logfire span carries attributes `needs_guidance`, `retrieved_count`, `citation_count`, `response_id`.
- Prompts are NOT in `tunables.yaml`: `PromptsConfig` loads `src/backend/config/prompts/<key>.md`. Edit `query_parse_system.md` and `coaching_response_system.md` there.
- Tests run with `uv run pytest ...` from the repo root (the `backend` package is installed from `src/`). Alembic runs with `PYTHONPATH=src uv run alembic ...`.
- Frontend tests run with `cd frontend && npx vitest run <path>`; component tests carry `// @vitest-environment jsdom` on line 1.
- Every commit message ends with these two trailer lines:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01E8q5bjtSR2xhaZbUKGTiM4
  ```
- Never commit or push to `production`; work stays on `feat/coaching-telegram-estimation-deploy`.

---

## File map

| Path | Responsibility |
|---|---|
| `src/backend/db/migrations/versions/20260909_012_coaching_feedback_guidelines.py` | Creates `guideline_chunk`, `coaching_response`, adds `user_goal.conditions` |
| `src/backend/db/models.py` | `GuidelineChunk`, `CoachingResponse` ORM classes; `UserGoal.conditions` |
| `src/backend/guidelines/__init__.py` | Package marker |
| `src/backend/guidelines/chunking.py` | `parse_markdown(path) -> list[Chunk]`, pure |
| `src/backend/guidelines/ingest.py` | `sync_source()` upsert + `python -m backend.guidelines.ingest` CLI |
| `src/backend/guidelines/retrieval.py` | `retrieve(query, conditions, k)`, `condition_tags()`, `RetrievedChunk` |
| `src/backend/guidelines/export_feedback.py` | JSONL export CLI |
| `docs/guidelines/dga-2020.md`, `who-healthy-diet.md`, `ada-soc-nutrition.md` | Seed guideline sources |
| `src/backend/config/prompts/query_parse_system.md` | Gains `needs_guidance` rule |
| `src/backend/config/prompts/coaching_response_system.md` | Gains citation rules |
| `src/backend/agent/coaching.py` | `needs_guidance`, `Citation`, `CoachingResult`, `format_passages`, `extract_citations`, retrieval wiring |
| `src/backend/agent/coaching_store.py` | `save_coaching_response()` |
| `src/backend/agent/orchestrator.py` | `_handle_coaching` persists, sets span attrs, returns `response_id` |
| `src/backend/api/coaching_feedback.py` | `POST /coaching/{response_id}/feedback` |
| `src/backend/api/goals.py` | `conditions` on GET/POST/PUT |
| `src/backend/main.py` | `include_router(coaching_feedback.router)` |
| `frontend/src/api/types.ts` | `LogMealResponse.response_id`, `GoalData.conditions` |
| `frontend/src/stores/mealStore.ts` | `ChatMessage.responseId`, passthrough in `logToApi` |
| `frontend/src/hooks/use-coaching-feedback.ts` | TanStack mutation hook |
| `frontend/src/components/chat/feedback-buttons.tsx` | Up/down buttons + comment input |
| `frontend/src/components/chat/ChatThread.tsx` | Renders `FeedbackButtons` under agent bubbles |
| `frontend/src/pages/SettingsPage.tsx` | "Health conditions" chips |

---

### Task 1: Migration 012 and ORM models

**Files:**
- Create: `src/backend/db/migrations/versions/20260909_012_coaching_feedback_guidelines.py`
- Modify: `src/backend/db/models.py` (after `UserGoal.dietary_prefs` at line 45; append two classes at end of file)
- Test: `tests/test_models_coaching_feedback.py`

**Interfaces:**
- Consumes: `Base`, `Vector`, `ARRAY`, `JSONB`, `UUID` already imported in `models.py`; revision `"011"` in `20260708_011_food_source_trgm.py`.
- Produces:
  - `UserGoal.conditions: Mapped[list[str]]` (`ARRAY(Text)`, not null, default `[]`).
  - `class GuidelineChunk(Base)` — `__tablename__ = "guideline_chunk"`, columns `id`, `source_id`, `source_title`, `source_url`, `section`, `condition`, `ordinal`, `text`, `content_hash`, `embedding: Vector(768)`, `created_at`.
  - `class CoachingResponse(Base)` — `__tablename__ = "coaching_response"`, columns `id`, `user_id`, `conversation_id`, `query`, `parsed_query`, `retrieved_chunk_ids`, `citations`, `response_text`, `model`, `trace_id`, `rating`, `rating_comment`, `rated_at`, `created_at`.

- [ ] **Step 1: Write the failing model test**

```python
# tests/test_models_coaching_feedback.py
from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import ARRAY

from backend.db.models import CoachingResponse, GuidelineChunk, UserGoal


def test_user_goal_has_conditions_array() -> None:
    col = UserGoal.__table__.c.conditions
    assert isinstance(col.type, ARRAY)
    assert col.nullable is False
    assert str(col.server_default.arg) == "'{}'"


def test_guideline_chunk_columns() -> None:
    cols = GuidelineChunk.__table__.c
    assert isinstance(cols.embedding.type, Vector)
    assert cols.embedding.type.dim == 768
    assert cols.content_hash.unique is True
    assert {"source_id", "section", "condition", "ordinal", "text"} <= set(cols.keys())


def test_coaching_response_columns() -> None:
    cols = CoachingResponse.__table__.c
    assert isinstance(cols.retrieved_chunk_ids.type, ARRAY)
    assert cols.rating.nullable is True
    assert cols.trace_id.nullable is True
    assert cols.user_id.nullable is False
    assert {"query", "parsed_query", "citations", "response_text", "model"} <= set(
        cols.keys()
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models_coaching_feedback.py -v`
Expected: FAIL with `ImportError: cannot import name 'CoachingResponse' from 'backend.db.models'`

- [ ] **Step 3: Add `conditions` to `UserGoal` and the two new models**

In `src/backend/db/models.py`, directly after the `dietary_prefs` line inside `UserGoal`:

```python
    # Declared health conditions (API-validated: diabetes, prediabetes,
    # hypertension, ckd). Drives which guideline passages the coach may cite.
    conditions: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'")
    )
```

Append at the end of `models.py`:

```python
class GuidelineChunk(Base):
    """One embedded passage from a curated public dietary guideline.

    Written by ``python -m backend.guidelines.ingest``. Read by
    backend.guidelines.retrieval.retrieve() via pgvector ANN when a coaching
    question needs a recommendation rather than a data readback.
    """

    __tablename__ = "guideline_chunk"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_title: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    section: Mapped[str] = mapped_column(Text, nullable=False)
    condition: Mapped[str] = mapped_column(Text, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    embedding: Mapped[list | None] = mapped_column(Vector(768), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_guideline_chunk_condition", "condition"),)


class CoachingResponse(Base):
    """One persisted coaching reply with the inputs that produced it.

    Written by the orchestrator after every coaching turn. Rated via
    POST /coaching/{id}/feedback. Exported to JSONL by
    backend.guidelines.export_feedback as the seed for a coaching eval set.
    """

    __tablename__ = "coaching_response"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("user_goal.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    conversation_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    parsed_query: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    retrieved_chunk_ids: Mapped[list[str]] = mapped_column(
        ARRAY(UUID(as_uuid=False)),
        nullable=False,
        default=list,
        server_default=text("'{}'"),
    )
    citations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    response_text: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    rating: Mapped[str | None] = mapped_column(Text, nullable=True)
    rating_comment: Mapped[str | None] = mapped_column(String(500), nullable=True)
    rated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_coaching_response_user_id", "user_id"),
        Index("ix_coaching_response_created_at", "created_at"),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_models_coaching_feedback.py -v`
Expected: 3 passed

- [ ] **Step 5: Write the migration**

Create `src/backend/db/migrations/versions/20260909_012_coaching_feedback_guidelines.py`:

```python
"""Coaching feedback loop + guideline retrieval tables.

Adds `guideline_chunk` (embedded passages from curated public dietary
guidelines, pgvector IVFFlat cosine index), `coaching_response` (every
coaching reply with its inputs, ratable by the user), and
`user_goal.conditions` (declared health conditions used to filter which
guideline passages the coach may cite).

Revision ID: 012
Revises: 011
Create Date: 2026-09-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # user_goal.conditions
    op.add_column(
        "user_goal",
        sa.Column(
            "conditions",
            ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )

    # guideline_chunk
    op.create_table(
        "guideline_chunk",
        sa.Column(
            "id",
            UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("source_title", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("section", sa.Text(), nullable=False),
        sa.Column("condition", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False, unique=True),
        # Placeholder type, altered to vector(768) below (same idiom as 001).
        sa.Column("embedding", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.execute(
        "ALTER TABLE guideline_chunk "
        "ALTER COLUMN embedding TYPE vector(768) USING NULL"
    )
    op.create_index("ix_guideline_chunk_condition", "guideline_chunk", ["condition"])
    op.execute("""
        CREATE INDEX ix_guideline_chunk_embedding
        ON guideline_chunk
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
        """)

    # coaching_response
    op.create_table(
        "coaching_response",
        sa.Column("id", UUID(), primary_key=True),
        sa.Column(
            "user_id",
            UUID(),
            sa.ForeignKey("user_goal.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("conversation_id", sa.Text(), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("parsed_query", JSONB(), nullable=False),
        sa.Column(
            "retrieved_chunk_ids",
            ARRAY(UUID()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("citations", JSONB(), nullable=False),
        sa.Column("response_text", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column("rating", sa.Text(), nullable=True),
        sa.Column("rating_comment", sa.String(500), nullable=True),
        sa.Column("rated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_coaching_response_user_id", "coaching_response", ["user_id"])
    op.create_index(
        "ix_coaching_response_created_at", "coaching_response", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_coaching_response_created_at", table_name="coaching_response")
    op.drop_index("ix_coaching_response_user_id", table_name="coaching_response")
    op.drop_table("coaching_response")
    op.execute("DROP INDEX IF EXISTS ix_guideline_chunk_embedding")
    op.drop_index("ix_guideline_chunk_condition", table_name="guideline_chunk")
    op.drop_table("guideline_chunk")
    op.drop_column("user_goal", "conditions")
```

- [ ] **Step 6: Apply, roll back, re-apply against the dev database**

Run: `PYTHONPATH=src uv run alembic upgrade head && PYTHONPATH=src uv run alembic downgrade 011 && PYTHONPATH=src uv run alembic upgrade head`
Expected: three `INFO  [alembic.runtime.migration] Running ...` blocks, last line `Running upgrade 011 -> 012, Coaching feedback loop + guideline retrieval tables.`, exit 0.

- [ ] **Step 7: Run the existing suites that construct `UserGoal`**

Run: `uv run pytest tests/test_goals_api.py tests/test_context.py tests/test_coaching.py -q`
Expected: all passed (the new column has defaults, so untouched tests still pass)

- [ ] **Step 8: Commit**

```bash
git add src/backend/db/models.py src/backend/db/migrations/versions/20260909_012_coaching_feedback_guidelines.py tests/test_models_coaching_feedback.py
git commit -F - <<'EOF'
feat(db): guideline_chunk, coaching_response tables and user_goal.conditions

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01E8q5bjtSR2xhaZbUKGTiM4
EOF
```

---

### Task 2: Chunking module, ingest CLI, seed guideline files

**Files:**
- Create: `src/backend/guidelines/__init__.py`, `src/backend/guidelines/chunking.py`, `src/backend/guidelines/ingest.py`
- Create: `docs/guidelines/dga-2020.md`, `docs/guidelines/who-healthy-diet.md`, `docs/guidelines/ada-soc-nutrition.md`
- Test: `tests/test_guideline_chunking.py`, `tests/test_guideline_ingest.py`

**Interfaces:**
- Consumes: `GuidelineChunk` (Task 1), `backend.agent.llm.embed_text(text: str) -> list[float]`, `backend.db.session.get_session`, `dispose_engine`.
- Produces:
  - `chunking.Frontmatter(BaseModel)`: `source_id, title, url, condition, license: str`.
  - `chunking.Chunk(BaseModel)`: `source_id, source_title, source_url, condition, section, text, content_hash: str; ordinal: int`.
  - `chunking.FrontmatterError(ValueError)`.
  - `chunking.parse_markdown(path: Path) -> list[Chunk]`; `chunking.content_hash(source_id, section, text) -> str`; `chunking.MAX_CHUNK_WORDS = 300`.
  - `ingest.IngestStats(BaseModel)`: `source_id: str; unchanged: int; added: int; removed: int`.
  - `ingest.sync_source(session, source_id, chunks, embed, *, dry_run=False) -> IngestStats`.
  - `ingest.main(argv: list[str] | None = None) -> int`.

- [ ] **Step 1: Write the failing chunking tests**

```python
# tests/test_guideline_chunking.py
from __future__ import annotations

from pathlib import Path

import pytest

from backend.guidelines.chunking import (
    MAX_CHUNK_WORDS,
    Chunk,
    FrontmatterError,
    _split_long,
    content_hash,
    parse_markdown,
)

_FRONTMATTER = """---
source_id: demo
title: Demo Guideline
url: https://example.org/demo
condition: general
license: public domain
---
"""


def _write(tmp_path: Path, body: str, name: str = "demo.md") -> Path:
    path = tmp_path / name
    path.write_text(_FRONTMATTER + body, encoding="utf-8")
    return path


def test_each_heading_starts_a_chunk_with_section_path(tmp_path: Path) -> None:
    body = (
        "## Chapter 1\n\nIntro paragraph.\n\n"
        "### Core elements\n\nVegetables and fruit.\n\n"
        "## Chapter 2\n\nLimits.\n"
    )
    chunks = parse_markdown(_write(tmp_path, body))

    assert [c.section for c in chunks] == [
        "Chapter 1",
        "Chapter 1 > Core elements",
        "Chapter 2",
    ]
    assert [c.ordinal for c in chunks] == [0, 1, 2]
    assert chunks[1].text == "Vegetables and fruit."
    assert all(isinstance(c, Chunk) for c in chunks)
    assert chunks[0].source_title == "Demo Guideline"
    assert chunks[0].condition == "general"


def test_hash_is_stable_and_depends_on_section_and_text() -> None:
    a = content_hash("demo", "Chapter 1", "text")
    assert a == content_hash("demo", "Chapter 1", "text")
    assert a != content_hash("demo", "Chapter 2", "text")
    assert a != content_hash("demo", "Chapter 1", "other")
    assert len(a) == 64


def test_long_section_splits_at_paragraphs_with_one_paragraph_overlap() -> None:
    paras = [f"p{i} " + ("word " * 99).strip() for i in range(1, 6)]  # 100 words each
    pieces = _split_long("\n\n".join(paras), max_words=250)

    assert len(pieces) == 4
    assert pieces[0].startswith("p1 ") and pieces[0].endswith(paras[1])
    assert pieces[1].startswith("p2 ")  # overlap: last paragraph of piece 0
    assert pieces[3].startswith("p4 ") and pieces[3].endswith(paras[4])


def test_short_section_is_not_split() -> None:
    text = "one paragraph\n\ntwo paragraph"
    assert _split_long(text, max_words=MAX_CHUNK_WORDS) == [text]


def test_missing_frontmatter_key_raises_naming_the_file(tmp_path: Path) -> None:
    path = tmp_path / "demo.md"
    path.write_text(
        "---\nsource_id: demo\ntitle: T\nurl: u\ncondition: general\n---\n## A\n\nx\n",
        encoding="utf-8",
    )
    with pytest.raises(FrontmatterError, match="demo.md"):
        parse_markdown(path)


def test_source_id_must_match_filename(tmp_path: Path) -> None:
    path = _write(tmp_path, "## A\n\nx\n", name="other.md")
    with pytest.raises(FrontmatterError, match="source_id"):
        parse_markdown(path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_guideline_chunking.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.guidelines'`

- [ ] **Step 3: Implement the chunking module**

Create `src/backend/guidelines/__init__.py`:

```python
"""Curated dietary-guideline ingestion, retrieval and feedback export."""
```

Create `src/backend/guidelines/chunking.py`:

```python
"""Parse a guideline markdown file into embeddable chunks. Pure, no I/O."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

# Roughly 400 tokens of English prose. No tokenizer dependency: the
# ingest path only needs a stable, approximate cap.
MAX_CHUNK_WORDS = 300

_HEADING_RE = re.compile(r"^(#{2,3})\s+(.*\S)\s*$")


class FrontmatterError(ValueError):
    """Raised when a guideline file has missing or inconsistent frontmatter."""


class Frontmatter(BaseModel):
    """Required YAML header of every ``docs/guidelines/<source_id>.md`` file."""

    source_id: str
    title: str
    url: str
    condition: str
    license: str

    model_config = ConfigDict(extra="forbid")


class Chunk(BaseModel):
    """One passage ready for embedding and insertion into guideline_chunk."""

    source_id: str
    source_title: str
    source_url: str
    condition: str
    section: str
    ordinal: int
    text: str
    content_hash: str

    model_config = ConfigDict(extra="forbid")


def content_hash(source_id: str, section: str, text: str) -> str:
    """Return the sha256 hex digest identifying a chunk across ingest runs."""
    payload = "\n".join((source_id, section, text)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _word_count(text: str) -> int:
    """Count whitespace-separated words."""
    return len(text.split())


def _split_frontmatter(raw: str, path: Path) -> tuple[Frontmatter, str]:
    """Split ``---`` delimited YAML frontmatter from the markdown body.

    Args:
        raw: Full file contents.
        path: File path, used only for error messages.

    Returns:
        Validated frontmatter and the remaining body text.

    Raises:
        FrontmatterError: If the header is missing, malformed, or lacks a key.
    """
    if not raw.startswith("---\n"):
        raise FrontmatterError(f"{path.name}: missing YAML frontmatter")
    end = raw.find("\n---", 4)
    if end == -1:
        raise FrontmatterError(f"{path.name}: unterminated YAML frontmatter")
    header = raw[4:end]
    body = raw[end + len("\n---") :].lstrip("\n")
    try:
        fields = yaml.safe_load(header) or {}
        frontmatter = Frontmatter(**fields)
    except (yaml.YAMLError, ValidationError, TypeError) as exc:
        raise FrontmatterError(f"{path.name}: invalid frontmatter: {exc}") from exc
    if frontmatter.source_id != path.stem:
        raise FrontmatterError(
            f"{path.name}: source_id '{frontmatter.source_id}' must equal "
            f"the filename stem '{path.stem}'"
        )
    return frontmatter, body


def _split_sections(body: str) -> list[tuple[str, str]]:
    """Split the body at every ``##`` / ``###`` heading.

    Returns:
        List of (section path joined with " > ", section text) pairs in
        document order. Text before the first heading is emitted under
        "Introduction" when non-empty.
    """
    sections: list[tuple[str, str]] = []
    h2: str | None = None
    h3: str | None = None
    buffer: list[str] = []
    current = "Introduction"

    def flush() -> None:
        text = "\n".join(buffer).strip()
        if text:
            sections.append((current, text))
        buffer.clear()

    for line in body.splitlines():
        match = _HEADING_RE.match(line)
        if match is None:
            buffer.append(line)
            continue
        flush()
        level, title = len(match.group(1)), match.group(2)
        if level == 2:
            h2, h3 = title, None
        else:
            h3 = title
        current = " > ".join(part for part in (h2, h3) if part)
    flush()
    return sections


def _split_long(text: str, max_words: int = MAX_CHUNK_WORDS) -> list[str]:
    """Split text longer than ``max_words`` at paragraph boundaries.

    Consecutive pieces share one paragraph so a recommendation that spans
    a boundary is still retrievable whole.

    Args:
        text: Section text with blank-line separated paragraphs.
        max_words: Soft cap per piece; a single oversized paragraph is
            kept intact.

    Returns:
        One or more pieces, each a "\\n\\n"-joined run of paragraphs.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    joined = "\n\n".join(paragraphs)
    if _word_count(joined) <= max_words:
        return [joined]

    pieces: list[str] = []
    current: list[str] = []
    for para in paragraphs:
        if current and _word_count("\n\n".join(current + [para])) > max_words:
            pieces.append("\n\n".join(current))
            current = [current[-1], para]
        else:
            current.append(para)
    if current:
        pieces.append("\n\n".join(current))
    return pieces


def parse_markdown(path: Path) -> list[Chunk]:
    """Parse one guideline file into ordered, hashed chunks.

    Args:
        path: ``docs/guidelines/<source_id>.md``.

    Returns:
        Chunks in document order with ``ordinal`` 0..n-1.

    Raises:
        FrontmatterError: See _split_frontmatter.
    """
    frontmatter, body = _split_frontmatter(path.read_text(encoding="utf-8"), path)
    chunks: list[Chunk] = []
    for section, section_text in _split_sections(body):
        for piece in _split_long(section_text):
            chunks.append(
                Chunk(
                    source_id=frontmatter.source_id,
                    source_title=frontmatter.title,
                    source_url=frontmatter.url,
                    condition=frontmatter.condition,
                    section=section,
                    ordinal=len(chunks),
                    text=piece,
                    content_hash=content_hash(frontmatter.source_id, section, piece),
                )
            )
    return chunks


__all__ = [
    "MAX_CHUNK_WORDS",
    "Chunk",
    "Frontmatter",
    "FrontmatterError",
    "content_hash",
    "parse_markdown",
]
```

- [ ] **Step 4: Run chunking tests**

Run: `uv run pytest tests/test_guideline_chunking.py -v`
Expected: 6 passed

- [ ] **Step 5: Write the failing ingest tests**

```python
# tests/test_guideline_ingest.py
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.sql.dml import Delete

from backend.guidelines.chunking import Chunk, content_hash
from backend.guidelines.ingest import IngestStats, sync_source


def _chunk(section: str, text: str) -> Chunk:
    return Chunk(
        source_id="demo",
        source_title="Demo",
        source_url="https://example.org",
        condition="general",
        section=section,
        ordinal=0,
        text=text,
        content_hash=content_hash("demo", section, text),
    )


def _session(existing_hashes: list[str]) -> MagicMock:
    session = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = existing_hashes
    session.execute = AsyncMock(return_value=result)
    session.add_all = MagicMock()
    session.commit = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_first_run_embeds_and_inserts_every_chunk() -> None:
    chunks = [_chunk("A", "alpha"), _chunk("B", "beta")]
    session = _session([])
    embed = AsyncMock(return_value=[0.1] * 768)

    stats = await sync_source(session, "demo", chunks, embed)

    assert stats == IngestStats(source_id="demo", unchanged=0, added=2, removed=0)
    assert embed.await_count == 2
    rows = session.add_all.call_args.args[0]
    assert [r.content_hash for r in rows] == [c.content_hash for c in chunks]
    assert rows[0].embedding == [0.1] * 768
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_second_run_with_no_changes_makes_no_writes_or_embed_calls() -> None:
    chunks = [_chunk("A", "alpha"), _chunk("B", "beta")]
    session = _session([c.content_hash for c in chunks])
    embed = AsyncMock()

    stats = await sync_source(session, "demo", chunks, embed)

    assert stats == IngestStats(source_id="demo", unchanged=2, added=0, removed=0)
    embed.assert_not_called()
    session.add_all.assert_not_called()
    # Only the SELECT of existing hashes ran; no DELETE.
    assert session.execute.await_count == 1
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_removed_chunk_is_deleted() -> None:
    kept = _chunk("A", "alpha")
    gone = _chunk("B", "beta")
    session = _session([kept.content_hash, gone.content_hash])
    embed = AsyncMock()

    stats = await sync_source(session, "demo", [kept], embed)

    assert stats == IngestStats(source_id="demo", unchanged=1, added=0, removed=1)
    delete_stmt = session.execute.await_args_list[1].args[0]
    assert isinstance(delete_stmt, Delete)
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_dry_run_reports_but_does_not_write() -> None:
    session = _session([])
    embed = AsyncMock()

    stats = await sync_source(session, "demo", [_chunk("A", "a")], embed, dry_run=True)

    assert stats.added == 1
    embed.assert_not_called()
    session.add_all.assert_not_called()
    session.commit.assert_not_awaited()
```

- [ ] **Step 6: Run ingest tests to verify they fail**

Run: `uv run pytest tests/test_guideline_ingest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.guidelines.ingest'`

- [ ] **Step 7: Implement the ingest module and CLI**

Create `src/backend/guidelines/ingest.py`:

```python
"""Idempotent guideline ingest: ``python -m backend.guidelines.ingest``.

Usage:
    PYTHONPATH=src uv run python -m backend.guidelines.ingest \\
        [--dir docs/guidelines] [--dry-run]

For each ``<source_id>.md`` the file is chunked and hashed; only chunks whose
hash is not yet stored are embedded and inserted, and stored chunks whose
hash is no longer present are deleted. A second run with unchanged files
performs no embedding calls and no writes.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agent.llm import embed_text
from backend.db.models import GuidelineChunk
from backend.db.session import dispose_engine, get_session
from backend.guidelines.chunking import Chunk, FrontmatterError, parse_markdown

Embedder = Callable[[str], Awaitable[list[float]]]

_DEFAULT_DIR = Path("docs/guidelines")
_EMBED_BATCH = 16


class IngestStats(BaseModel):
    """Per-source outcome of one sync."""

    source_id: str
    unchanged: int
    added: int
    removed: int

    model_config = ConfigDict(extra="forbid")


async def _embed_all(texts: Sequence[str], embed: Embedder) -> list[list[float]]:
    """Embed texts in parallel batches of ``_EMBED_BATCH``."""
    vectors: list[list[float]] = []
    for start in range(0, len(texts), _EMBED_BATCH):
        batch = texts[start : start + _EMBED_BATCH]
        vectors.extend(await asyncio.gather(*(embed(t) for t in batch)))
    return vectors


async def sync_source(
    session: AsyncSession,
    source_id: str,
    chunks: Sequence[Chunk],
    embed: Embedder,
    *,
    dry_run: bool = False,
) -> IngestStats:
    """Bring guideline_chunk rows for ``source_id`` in line with ``chunks``.

    Args:
        session: Open async session; committed here when anything changed.
        source_id: Source whose rows are reconciled.
        chunks: Freshly parsed chunks for that source.
        embed: Async text -> vector function (``embed_text`` in production).
        dry_run: Compute counts without embedding or writing.

    Returns:
        Counts of unchanged, added and removed chunks.
    """
    stmt = select(GuidelineChunk.content_hash).where(
        GuidelineChunk.source_id == source_id
    )
    existing = set((await session.execute(stmt)).scalars().all())
    wanted = {c.content_hash: c for c in chunks}

    new_chunks = [c for c in chunks if c.content_hash not in existing]
    stale = existing - wanted.keys()
    stats = IngestStats(
        source_id=source_id,
        unchanged=len(existing & wanted.keys()),
        added=len(new_chunks),
        removed=len(stale),
    )
    if dry_run or (not new_chunks and not stale):
        return stats

    if new_chunks:
        vectors = await _embed_all([c.text for c in new_chunks], embed)
        session.add_all(
            [
                GuidelineChunk(
                    source_id=c.source_id,
                    source_title=c.source_title,
                    source_url=c.source_url,
                    section=c.section,
                    condition=c.condition,
                    ordinal=c.ordinal,
                    text=c.text,
                    content_hash=c.content_hash,
                    embedding=vector,
                )
                for c, vector in zip(new_chunks, vectors, strict=True)
            ]
        )
    if stale:
        await session.execute(
            delete(GuidelineChunk).where(
                GuidelineChunk.source_id == source_id,
                GuidelineChunk.content_hash.in_(stale),
            )
        )
    await session.commit()
    return stats


async def _run(directory: Path, dry_run: bool) -> int:
    """Parse every file first (fail fast), then sync each source."""
    parsed: list[tuple[str, list[Chunk]]] = []
    for path in sorted(directory.glob("*.md")):
        try:
            parsed.append((path.stem, parse_markdown(path)))
        except FrontmatterError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    session_factory = get_session()
    try:
        async with session_factory() as session:
            for source_id, chunks in parsed:
                stats = await sync_source(
                    session, source_id, chunks, embed_text, dry_run=dry_run
                )
                print(
                    f"{stats.source_id}: unchanged={stats.unchanged} "
                    f"added={stats.added} removed={stats.removed}"
                )
    finally:
        await dispose_engine()
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    parser = argparse.ArgumentParser(description="Ingest guideline markdown files.")
    parser.add_argument("--dir", type=Path, default=_DEFAULT_DIR)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    return asyncio.run(_run(args.dir, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 8: Run ingest tests**

Run: `uv run pytest tests/test_guideline_ingest.py -v`
Expected: 4 passed

- [ ] **Step 9: Write the three seed guideline files**

Create `docs/guidelines/dga-2020.md`:

```markdown
---
source_id: dga-2020
title: Dietary Guidelines for Americans, 2020-2025
url: https://www.dietaryguidelines.gov/
condition: general
license: public domain (US government work)
---

## Four overarching guidelines

The Dietary Guidelines for Americans, 2020-2025 rest on four guidelines:
follow a healthy dietary pattern at every life stage; customize and enjoy
nutrient-dense food and beverage choices to reflect personal preferences,
cultural traditions, and budget; focus on meeting food group needs with
nutrient-dense foods and beverages while staying within calorie limits; and
limit foods and beverages higher in added sugars, saturated fat, and sodium,
and limit alcoholic beverages.

## Core elements of a healthy dietary pattern

A healthy dietary pattern includes vegetables of all types (dark green, red
and orange, beans, peas and lentils, starchy, and other), fruits (especially
whole fruit), grains (at least half whole grain), dairy (fat-free or low-fat
milk, yogurt, and cheese, or fortified soy alternatives), protein foods
(lean meats, poultry, and eggs; seafood; beans, peas, and lentils; nuts,
seeds, and soy products), and oils. At 2,000 calories the Healthy
U.S.-Style pattern provides about 2.5 cup-equivalents of vegetables, 2
cup-equivalents of fruit, 6 ounce-equivalents of grains (at least 3 whole),
3 cup-equivalents of dairy, 5.5 ounce-equivalents of protein foods, and 27
grams of oils per day.

## Nutrient-dense foods and beverages

Nutrient-dense foods provide vitamins, minerals, and other health-promoting
components with little added sugars, saturated fat, and sodium: vegetables,
fruits, whole grains, seafood, eggs, legumes, unsalted nuts and seeds,
low-fat dairy, and lean meats and poultry prepared without added sugars,
saturated fat, or salt.

## Limit added sugars

Limit added sugars to less than 10 percent of calories per day starting at
age 2, and avoid them entirely before age 2. The leading sources are
sugar-sweetened beverages, desserts and sweet snacks, sweetened coffee and
tea, and candy. Replacing these with water, unsweetened beverages, and whole
fruit is the most direct way to stay within the limit.

## Limit saturated fat

Limit saturated fat to less than 10 percent of calories per day starting at
age 2, and replace it with unsaturated fats, particularly polyunsaturated
fats, rather than with refined carbohydrates. Common sources include
burgers, tacos, and other sandwiches, rice and pasta mixed dishes,
higher-fat dairy, and processed meats.

## Limit sodium

Limit sodium to less than 2,300 milligrams per day for adults, and less for
children under 14. Most sodium comes from processed and prepared foods and
from food eaten away from home rather than the salt shaker, so choosing
fresh or minimally processed foods and reading the Nutrition Facts label are
the main strategies.

## Alcoholic beverages

Adults of legal drinking age can choose not to drink, or to drink in
moderation: 2 drinks or less in a day for men and 1 drink or less in a day
for women, on days when alcohol is consumed. People who are or might be pregnant, are under
the legal drinking age, take medications that interact with alcohol, or are
recovering from an alcohol use disorder should not drink at all.

## Adults and older adults

Most adults fall short on vegetables, fruits, whole grains, and dairy and
exceed the limits for added sugars, saturated fat, and sodium. Adults 19
through 59 should follow a healthy dietary pattern within their calorie
needs alongside regular physical activity. Older adults (60 and over) need
fewer calories but as many or more nutrients, so nutrient density matters
more; they should pay attention to protein to preserve muscle, to vitamin
B12 (absorbed less efficiently with age; fortified foods or a supplement may
be needed), and to fluids, since thirst declines with age.
```

Create `docs/guidelines/who-healthy-diet.md`:

```markdown
---
source_id: who-healthy-diet
title: WHO Healthy Diet fact sheet
url: https://www.who.int/news-room/fact-sheets/detail/healthy-diet
condition: general
license: CC BY-NC-SA 3.0 IGO (paraphrased)
---

## What a healthy diet does

A healthy diet helps protect against malnutrition in all its forms as well
as noncommunicable diseases such as diabetes, heart disease, stroke, and
cancer. The exact make-up of a healthy diet varies with a person's age, sex,
lifestyle, physical activity, cultural context, locally available foods, and
dietary customs, but the basic principles are the same everywhere. Energy
intake should be in balance with energy expenditure, and the diet should be
built around fruit, vegetables, legumes, nuts, and whole grains.

## Fruit, vegetables, legumes, and whole grains

Adults should eat at least 400 grams of fruit and vegetables per day, which
is roughly five portions. Potatoes, sweet potatoes, cassava, and other
starchy roots do not count toward this total. Practical ways to reach it
include always including vegetables in meals, eating fresh fruit and raw
vegetables as snacks, choosing seasonal produce, and eating a variety of
types. Legumes such as lentils and beans, nuts, and whole grains such as
unprocessed maize, millet, oats, wheat, and brown rice should also be eaten
regularly.

## Fats

Total fat should provide less than 30 percent of total energy intake, which
helps prevent unhealthy weight gain. Saturated fats should provide less than
10 percent of energy and trans fats less than 1 percent, with the aim of
shifting intake away from saturated and trans fats toward unsaturated fats.
Unsaturated fats are found in fish, avocado, nuts, and in sunflower, soybean,
canola, and olive oils. Saturated fats are found in fatty meat, butter, palm
and coconut oil, cream, cheese, ghee, and lard. Industrially produced trans
fats, found in some baked and fried foods and pre-packaged snacks, are not
part of a healthy diet and should be avoided. Fat intake can be reduced by
steaming or boiling instead of frying, replacing butter and lard with oils
rich in polyunsaturated fats, choosing reduced-fat dairy and lean meats, and
limiting baked and fried foods.

## Sugars and salt

Free sugars should provide less than 10 percent of total energy intake, and
reducing them to less than 5 percent brings additional health benefits. Free
sugars are all sugars added to foods or drinks by the manufacturer, cook, or
consumer, plus the sugars naturally present in honey, syrups, and fruit
juices. Limiting sugary snacks, sweets, and sugar-sweetened beverages and
choosing fresh fruit and raw vegetables instead reduces intake. Salt should
be kept to less than 5 grams per day, which is about 2 grams of sodium, and
the salt used should be iodized. Most salt comes from processed foods and
from salt added during cooking and at the table, so limiting salty
condiments, choosing lower-sodium products, and not adding salt at the table
are the main levers.
```

Create `docs/guidelines/ada-soc-nutrition.md`:

```markdown
---
source_id: ada-soc-nutrition
title: ADA Standards of Care in Diabetes, Section 5 (Nutrition Therapy)
url: https://diabetesjournals.org/care/issue/48/Supplement_1
condition: diabetes
license: copyrighted (American Diabetes Association); paraphrased, with section references so the original can be consulted
---

## Nutrition therapy overview

Section 5 of the Standards of Care ("Facilitating Positive Health Behaviors
and Well-being to Improve Health Outcomes"), Nutrition Therapy subsection.
The Standards recommend that nutrition therapy, ideally delivered by a
registered dietitian nutritionist, be offered to all people with type 1 or
type 2 diabetes (evidence grade A). Its goals are to support healthful
eating patterns built on nutrient-dense foods in appropriate portions, to
address individual needs based on personal and cultural preferences, health
literacy, food access, and readiness to change, to keep the pleasure of
eating by limiting choices only where evidence supports it, and to give
practical tools for day-to-day meal planning.

## Eating patterns and macronutrient distribution

Section 5, Nutrition Therapy: Eating Patterns and Macronutrient Distribution.
There is no single ideal percentage of calories from carbohydrate, protein,
and fat for people with diabetes; the split should be individualized around
calorie and metabolic goals. Mediterranean-style, low-carbohydrate and
very-low-carbohydrate, vegetarian or vegan, and DASH-style patterns are all
acceptable. Their shared features are an emphasis on non-starchy vegetables,
minimal added sugars and refined grains, and whole foods over highly
processed foods wherever possible.

## Carbohydrates

Section 5, Nutrition Therapy: Carbohydrates. Carbohydrate quality matters:
sources should be nutrient-dense, high in fiber, and minimally processed,
such as vegetables, fruits, legumes, whole grains, and dairy, aiming for at
least the general-population fiber target of about 14 grams per 1,000 kcal.
Reducing overall carbohydrate intake has the most evidence for improving
glycemia and fits within several eating patterns. People using mealtime
insulin should learn carbohydrate counting or, failing that, keep
carbohydrate intake consistent in timing and amount, and should consider
the fat and protein content of meals when dosing.

## Added sugars and sweetened beverages

Section 5, Nutrition Therapy: Carbohydrates. People with diabetes are
advised to replace sugar-sweetened beverages, including fruit juice, with
water or low- or no-calorie drinks as much as possible, to help glycemia and
weight and to lower cardiometabolic risk, and to minimize foods with added
sugar that displace more nutrient-dense choices. Nonnutritive sweeteners can
serve as a short-term substitute for sweetened products, but the aim is to
reduce sweetened drinks and foods overall rather than to substitute
indefinitely.

## Sodium and alcohol

Section 5, Nutrition Therapy: Sodium and Alcohol. As for the general
population, sodium should be limited to less than 2,300 mg per day. Adults
who choose to drink alcohol should do so in moderation, no more than one
drink per day for women and two for men. Alcohol raises the risk of
hypoglycemia, particularly delayed hypoglycemia, in people using insulin or
insulin secretagogues, so education on recognizing and managing it is
recommended.

## Weight management

Section 5, Nutrition Therapy: Weight Management (see also Section 8). For
people with type 2 diabetes who have overweight or obesity, a sustained
weight loss of 5 percent or more improves glycemia, blood pressure, and
lipids, with larger losses bringing larger benefits (evidence grade A).
This can be achieved with an individualized eating plan that creates an
energy deficit of roughly 500 to 750 kcal per day, combined with physical
activity and behavioral support, using whichever pattern fits the person's
preferences and health status.
```

- [ ] **Step 10: Verify the seed files parse and are 300-600 words**

Run: `uv run python -c "from pathlib import Path; from backend.guidelines.chunking import parse_markdown; [print(p.stem, len(parse_markdown(p)), 'chunks', len(p.read_text().split()), 'words') for p in sorted(Path('docs/guidelines').glob('*.md'))]"`
Expected: three lines like `ada-soc-nutrition 6 chunks 5xx words`, `dga-2020 8 chunks 5xx words`, `who-healthy-diet 4 chunks 4xx words`; every word count between 300 and 600.

- [ ] **Step 11: Dry-run then real ingest against the dev database**

Run: `PYTHONPATH=src uv run python -m backend.guidelines.ingest --dry-run`
Expected:
```
ada-soc-nutrition: unchanged=0 added=6 removed=0
dga-2020: unchanged=0 added=8 removed=0
who-healthy-diet: unchanged=0 added=4 removed=0
```
Run: `PYTHONPATH=src uv run python -m backend.guidelines.ingest` (needs `GOOGLE_API_KEY` and `DATABASE_URL`)
Expected: the same three lines.
Run it a second time.
Expected: `unchanged=6 added=0 removed=0`, `unchanged=8 ...`, `unchanged=4 ...` and no embedding calls.

- [ ] **Step 12: Commit**

```bash
git add src/backend/guidelines docs/guidelines tests/test_guideline_chunking.py tests/test_guideline_ingest.py
git commit -F - <<'EOF'
feat(guidelines): markdown chunking, idempotent ingest CLI, three seed sources

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01E8q5bjtSR2xhaZbUKGTiM4
EOF
```

---

### Task 3: Retrieval module

**Files:**
- Create: `src/backend/guidelines/retrieval.py`
- Test: `tests/test_guideline_retrieval.py`

**Interfaces:**
- Consumes: `GuidelineChunk` (Task 1), `backend.agent.llm.embed_text`, `backend.db.session.get_session`.
- Produces:
  - `RetrievedChunk(BaseModel)`: `id: str, source_id: str, source_title: str, section: str, text: str, score: float`.
  - `condition_tags(conditions: Sequence[str]) -> list[str]` — always `["general", ...]`, deduplicated, ordered.
  - `retrieve(query: str, conditions: Sequence[str], k: int = 5) -> list[RetrievedChunk]` — returns `[]` on any error.

- [ ] **Step 1: Write the failing unit tests**

```python
# tests/test_guideline_retrieval.py
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.db.models import GuidelineChunk
from backend.guidelines.retrieval import RetrievedChunk, condition_tags, retrieve


def test_condition_tags_always_includes_general() -> None:
    assert condition_tags([]) == ["general"]


def test_condition_tags_maps_diabetes_and_prediabetes_to_one_tag() -> None:
    assert condition_tags(["prediabetes"]) == ["general", "diabetes"]
    assert condition_tags(["diabetes", "prediabetes"]) == ["general", "diabetes"]


def test_condition_tags_ignores_conditions_without_a_guideline_yet() -> None:
    assert condition_tags(["hypertension", "ckd"]) == ["general"]


def _session_returning(rows: list[tuple[GuidelineChunk, float]]) -> MagicMock:
    session = MagicMock()
    result = MagicMock()
    result.all.return_value = rows
    session.execute = AsyncMock(return_value=result)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=session)


@pytest.mark.asyncio
async def test_retrieve_maps_rows_to_retrieved_chunks() -> None:
    chunk = GuidelineChunk(
        id="11111111-1111-1111-1111-111111111111",
        source_id="dga-2020",
        source_title="Dietary Guidelines for Americans, 2020-2025",
        source_url="https://www.dietaryguidelines.gov/",
        section="Limit added sugars",
        condition="general",
        ordinal=3,
        text="Limit added sugars to less than 10 percent of calories.",
        content_hash="abc",
    )
    with (
        patch(
            "backend.guidelines.retrieval.embed_text",
            new_callable=AsyncMock,
            return_value=[0.1] * 768,
        ),
        patch(
            "backend.guidelines.retrieval.get_session",
            return_value=_session_returning([(chunk, 0.25)]),
        ),
    ):
        chunks = await retrieve("how much sugar is ok?", ["prediabetes"], k=3)

    assert chunks == [
        RetrievedChunk(
            id="11111111-1111-1111-1111-111111111111",
            source_id="dga-2020",
            source_title="Dietary Guidelines for Americans, 2020-2025",
            section="Limit added sugars",
            text="Limit added sugars to less than 10 percent of calories.",
            score=0.75,
        )
    ]


@pytest.mark.asyncio
async def test_retrieve_returns_empty_and_warns_when_embedding_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with (
        patch(
            "backend.guidelines.retrieval.embed_text",
            new_callable=AsyncMock,
            side_effect=RuntimeError("quota"),
        ),
        caplog.at_level(logging.WARNING, logger="backend.guidelines.retrieval"),
    ):
        chunks = await retrieve("what should I eat?", [])

    assert chunks == []
    assert "guideline retrieval failed" in caplog.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_guideline_retrieval.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.guidelines.retrieval'`

- [ ] **Step 3: Implement retrieval**

Create `src/backend/guidelines/retrieval.py`:

```python
"""pgvector retrieval over guideline_chunk, filtered by user conditions."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from backend.agent.llm import embed_text
from backend.db.models import GuidelineChunk
from backend.db.session import get_session

logger = logging.getLogger(__name__)

# user_goal.conditions value -> guideline_chunk.condition tag. Conditions
# without a curated source yet (hypertension, ckd) are stored but unmapped.
_CONDITION_TO_TAG: dict[str, str] = {
    "diabetes": "diabetes",
    "prediabetes": "diabetes",
}


class RetrievedChunk(BaseModel):
    """One guideline passage with its cosine similarity to the query."""

    id: str
    source_id: str
    source_title: str
    section: str
    text: str
    score: float

    model_config = ConfigDict(extra="forbid")


def condition_tags(conditions: Sequence[str]) -> list[str]:
    """Map declared conditions to chunk tags, always including ``general``.

    Args:
        conditions: Values from ``user_goal.conditions``.

    Returns:
        Ordered, de-duplicated tags starting with "general".
    """
    tags = ["general"]
    for condition in conditions:
        tag = _CONDITION_TO_TAG.get(condition)
        if tag is not None and tag not in tags:
            tags.append(tag)
    return tags


async def retrieve(
    query: str, conditions: Sequence[str], k: int = 5
) -> list[RetrievedChunk]:
    """Return the ``k`` guideline passages nearest to ``query``.

    Retrieval is an enrichment: any failure (embedding API, database) is
    logged as a warning and yields an empty list so the coaching turn still
    answers without citations.

    Args:
        query: The user's message.
        conditions: The user's declared conditions (see condition_tags).
        k: Maximum passages to return.

    Returns:
        Passages ordered by descending similarity; empty on error.
    """
    tags = condition_tags(conditions)
    try:
        vector = await embed_text(query)
        distance = GuidelineChunk.embedding.cosine_distance(vector).label("distance")
        stmt = (
            select(GuidelineChunk, distance)
            .where(GuidelineChunk.condition.in_(tags))
            .order_by(distance)
            .limit(k)
        )
        session_factory = get_session()
        async with session_factory() as session:
            rows = (await session.execute(stmt)).all()
    except Exception as exc:  # noqa: BLE001 — see docstring
        logger.warning("guideline retrieval failed, answering without it: %s", exc)
        return []

    return [
        RetrievedChunk(
            id=str(chunk.id),
            source_id=chunk.source_id,
            source_title=chunk.source_title,
            section=chunk.section,
            text=chunk.text,
            score=1.0 - float(dist),
        )
        for chunk, dist in rows
    ]


__all__ = ["RetrievedChunk", "condition_tags", "retrieve"]
```

- [ ] **Step 4: Run unit tests**

Run: `uv run pytest tests/test_guideline_retrieval.py -v`
Expected: 5 passed

- [ ] **Step 5: Add the integration test (live Postgres, migration 012 applied)**

Append to `tests/test_guideline_retrieval.py`:

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_condition_filter_against_live_postgres() -> None:
    """Requires DATABASE_URL with migration 012 applied."""
    import uuid

    from sqlalchemy import delete

    from backend.db.session import dispose_engine, get_session

    marker = f"test-{uuid.uuid4()}"
    near = [1.0] + [0.0] * 767
    far = [0.0] * 767 + [1.0]

    def row(condition: str, text: str, vector: list[float]) -> GuidelineChunk:
        return GuidelineChunk(
            source_id=marker,
            source_title="T",
            source_url="u",
            section=text,
            condition=condition,
            ordinal=0,
            text=text,
            content_hash=f"{marker}-{text}",
            embedding=vector,
        )

    session_factory = get_session()
    try:
        async with session_factory() as session:
            session.add_all(
                [
                    row("general", "general-near", near),
                    row("general", "general-far", far),
                    row("diabetes", "diabetes-near", near),
                ]
            )
            await session.commit()

        with patch(
            "backend.guidelines.retrieval.embed_text",
            new_callable=AsyncMock,
            return_value=near,
        ):
            # k well above the seed row count so the far vector is still
            # returned; with ~20 rows the planner seq-scans (exact results).
            plain = await retrieve("q", [], k=100)
            diabetic = await retrieve("q", ["diabetes"], k=100)

        plain_texts = {c.text for c in plain if c.source_id == marker}
        diabetic_texts = {c.text for c in diabetic if c.source_id == marker}
        assert "diabetes-near" not in plain_texts
        assert {"general-near", "general-far"} <= plain_texts
        assert "diabetes-near" in diabetic_texts
    finally:
        async with session_factory() as session:
            await session.execute(
                delete(GuidelineChunk).where(GuidelineChunk.source_id == marker)
            )
            await session.commit()
        await dispose_engine()
```

Run: `uv run pytest tests/test_guideline_retrieval.py -m integration -v`
Expected: 1 passed (requires the dev Postgres from `DATABASE_URL`)
Run: `uv run pytest tests/test_guideline_retrieval.py -m "not integration" -q`
Expected: 5 passed, 1 deselected

- [ ] **Step 6: Commit**

```bash
git add src/backend/guidelines/retrieval.py tests/test_guideline_retrieval.py
git commit -F - <<'EOF'
feat(guidelines): condition-filtered pgvector retrieval over guideline_chunk

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01E8q5bjtSR2xhaZbUKGTiM4
EOF
```

---

### Task 4: `needs_guidance`, prompt rules, passage block, citations, `CoachingResult`

**Files:**
- Modify: `src/backend/agent/coaching.py` (`QueryParsed` ~line 48; `_ResponseDeps` ~line 118; `_user_context_instructions` ~line 135; `generate_response` ~line 300; `CoachingAgent.handle` ~line 355; `__all__`)
- Modify: `src/backend/config/prompts/query_parse_system.md` (append), `src/backend/config/prompts/coaching_response_system.md` (append inside `<rules>`)
- Test: `tests/test_coaching.py` (append), `tests/test_coaching_guidance.py` (new)

**Interfaces:**
- Consumes: `retrieve`, `RetrievedChunk` (Task 3); `UserGoal.conditions` (Task 1).
- Produces:
  - `QueryParsed.needs_guidance: bool = False`.
  - `class Citation(BaseModel)`: `n: int, chunk_id: str, source_id: str, section: str`.
  - `class CoachingResult(BaseModel)`: `message: str, parsed: QueryParsed, retrieved: list[RetrievedChunk], citations: list[Citation]`.
  - `format_passages(chunks: Sequence[RetrievedChunk]) -> str` (pure; `""` when empty).
  - `extract_citations(text: str, chunks: Sequence[RetrievedChunk]) -> list[Citation]` (pure).
  - `generate_response(message, data, *, context_prompt="", history=(), passages=())`.
  - `CoachingAgent.handle(user_id, message) -> CoachingResult`.

- [ ] **Step 1: Write the failing tests for the pure helpers and the wiring**

```python
# tests/test_coaching_guidance.py
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import capture_run_messages
from pydantic_ai.messages import ModelRequest
from pydantic_ai.models.test import TestModel

from backend.agent import coaching
from backend.agent.coaching import (
    Citation,
    CoachingAgent,
    CoachingResult,
    QueryParsed,
    extract_citations,
    format_passages,
    generate_response,
)
from backend.agent.context import ContextBundle
from backend.db.models import UserGoal
from backend.db.redis_client import TodayTotals
from backend.guidelines.retrieval import RetrievedChunk


@pytest.fixture(autouse=True)
def _no_user_state():
    with (
        patch(
            "backend.agent.coaching.build_context",
            new_callable=AsyncMock,
            return_value=ContextBundle(today_totals=TodayTotals()),
        ),
        patch(
            "backend.agent.coaching.get_coaching_history",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        yield


_CHUNKS = [
    RetrievedChunk(
        id="aaaaaaaa-0000-0000-0000-000000000001",
        source_id="dga-2020",
        source_title="Dietary Guidelines for Americans, 2020-2025",
        section="Limit added sugars",
        text="Limit added sugars to less than 10 percent of calories per day.",
        score=0.8,
    ),
    RetrievedChunk(
        id="aaaaaaaa-0000-0000-0000-000000000002",
        source_id="who-healthy-diet",
        source_title="WHO Healthy Diet fact sheet",
        section="Sugars and salt",
        text="Free sugars should provide less than 10 percent of total energy.",
        score=0.7,
    ),
]


def _mock_session_factory(goal: UserGoal | None) -> MagicMock:
    session = MagicMock()
    session.get = AsyncMock(return_value=goal)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=session)


def test_query_parsed_needs_guidance_defaults_false() -> None:
    parsed = QueryParsed(time_range="today")
    assert parsed.needs_guidance is False


def test_format_passages_numbers_and_titles_each_chunk() -> None:
    block = format_passages(_CHUNKS)

    assert block.startswith("## Guideline passages\n")
    assert "Cite with [n] where you rely on a passage." in block
    assert (
        "[1] Dietary Guidelines for Americans, 2020-2025 — Limit added sugars\n"
        "Limit added sugars to less than 10 percent of calories per day."
    ) in block
    assert "[2] WHO Healthy Diet fact sheet — Sugars and salt\n" in block


def test_format_passages_empty_when_no_chunks() -> None:
    assert format_passages([]) == ""


def test_extract_citations_maps_valid_numbers_and_drops_invalid(
    caplog: pytest.LogCaptureFixture,
) -> None:
    text = "Keep added sugar under 10% [1]. Also see [7] and again [1]."
    with caplog.at_level(logging.WARNING, logger="backend.agent.coaching"):
        citations = extract_citations(text, _CHUNKS)

    assert citations == [
        Citation(
            n=1,
            chunk_id="aaaaaaaa-0000-0000-0000-000000000001",
            source_id="dga-2020",
            section="Limit added sugars",
        )
    ]
    assert "[7]" in caplog.text


async def test_generate_response_puts_passage_block_in_instructions() -> None:
    with (
        coaching._response_agent.override(model=TestModel()),
        capture_run_messages() as msgs,
    ):
        await generate_response(
            "is sugar ok?", {"today_totals": {}}, context_prompt="ctx", passages=_CHUNKS
        )

    first = msgs[0]
    assert isinstance(first, ModelRequest)
    assert "## Guideline passages" in first.instructions
    assert "[2] WHO Healthy Diet fact sheet" in first.instructions
    assert "ctx" in first.instructions


async def test_generate_response_without_passages_has_no_block() -> None:
    with (
        coaching._response_agent.override(model=TestModel()),
        capture_run_messages() as msgs,
    ):
        await generate_response("how am I doing?", {"macros": {}})

    assert "## Guideline passages" not in msgs[0].instructions


@pytest.mark.asyncio
async def test_handle_retrieves_when_needs_guidance_and_returns_result() -> None:
    parsed = QueryParsed(time_range="today", include_goals=True, needs_guidance=True)
    goal = UserGoal(
        user_id="user-1",
        kcal_goal=2000.0,
        protein_goal=120.0,
        fiber_goal=30.0,
        dietary_prefs={},
        conditions=["prediabetes"],
        streak_days=0,
    )
    with (
        patch(
            "backend.agent.coaching.parse_query",
            new_callable=AsyncMock,
            return_value=parsed,
        ),
        patch(
            "backend.agent.coaching.get_today_totals",
            new_callable=AsyncMock,
            return_value=TodayTotals(kcal=900, protein_g=40, fiber_g=8, n_meals=1),
        ),
        patch(
            "backend.agent.coaching.get_session",
            return_value=_mock_session_factory(goal),
        ),
        patch(
            "backend.agent.coaching.retrieve",
            new_callable=AsyncMock,
            return_value=_CHUNKS,
        ) as retrieve_mock,
        patch(
            "backend.agent.coaching.generate_response",
            new_callable=AsyncMock,
            return_value="Keep added sugar under 10% of calories [1].",
        ) as gen_mock,
    ):
        result = await CoachingAgent().handle("user-1", "is sugar ok for me?")

    retrieve_mock.assert_awaited_once_with("is sugar ok for me?", ["prediabetes"])
    assert gen_mock.await_args.kwargs["passages"] == _CHUNKS
    assert isinstance(result, CoachingResult)
    assert result.message == "Keep added sugar under 10% of calories [1]."
    assert result.parsed is parsed
    assert result.retrieved == _CHUNKS
    assert [c.n for c in result.citations] == [1]


@pytest.mark.asyncio
async def test_handle_skips_retrieval_when_needs_guidance_false() -> None:
    parsed = QueryParsed(time_range="today", nutrients=["kcal"])
    with (
        patch(
            "backend.agent.coaching.parse_query",
            new_callable=AsyncMock,
            return_value=parsed,
        ),
        patch(
            "backend.agent.coaching.get_today_totals",
            new_callable=AsyncMock,
            return_value=TodayTotals(kcal=900, n_meals=1),
        ),
        patch("backend.agent.coaching.retrieve", new_callable=AsyncMock) as retrieve_mock,
        patch(
            "backend.agent.coaching.generate_response",
            new_callable=AsyncMock,
            return_value="900 kcal so far.",
        ) as gen_mock,
    ):
        result = await CoachingAgent().handle("user-1", "calories today?")

    retrieve_mock.assert_not_called()
    assert gen_mock.await_args.kwargs["passages"] == []
    assert result.retrieved == [] and result.citations == []


@pytest.mark.asyncio
async def test_handle_no_micronutrient_data_returns_result_not_str() -> None:
    parsed = QueryParsed(time_range="today", nutrients=["Vitamin B-12"])
    with (
        patch(
            "backend.agent.coaching.parse_query",
            new_callable=AsyncMock,
            return_value=parsed,
        ),
        patch(
            "backend.agent.coaching.get_micronutrients_for_range",
            new_callable=AsyncMock,
            return_value={},
        ),
    ):
        result = await CoachingAgent().handle("user-1", "b12 today?")

    assert isinstance(result, CoachingResult)
    assert result.message == "I don't have data on Vitamin B-12 for that period."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_coaching_guidance.py -v`
Expected: FAIL with `ImportError: cannot import name 'Citation' from 'backend.agent.coaching'`

- [ ] **Step 3: Extend `coaching.py`**

Add the import after `from backend.db.session import get_session`:

```python
from backend.guidelines.retrieval import RetrievedChunk, retrieve
```

Add `import re` to the stdlib imports.

In `QueryParsed`, after `include_foods: bool = False`:

```python
    # True when the user asks for a recommendation (what to eat, is X
    # healthy, how to change intake) rather than a readback of their data.
    needs_guidance: bool = False
```

After the `QueryParsed` class add:

```python
class Citation(BaseModel):
    """A bracketed [n] in the reply that resolved to a retrieved passage."""

    n: int
    chunk_id: str
    source_id: str
    section: str

    model_config = ConfigDict(extra="forbid")


class CoachingResult(BaseModel):
    """Everything a coaching turn produced, for the reply and for persistence."""

    message: str
    parsed: QueryParsed
    retrieved: list[RetrievedChunk] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


_CITATION_RE = re.compile(r"\[(\d+)\]")


def format_passages(chunks: Sequence[RetrievedChunk]) -> str:
    """Render retrieved passages as the numbered block appended to instructions.

    Args:
        chunks: Passages in retrieval order; their 1-based position is the
            citation number the model must use.

    Returns:
        The block, or "" when there are no passages.
    """
    if not chunks:
        return ""
    lines = [
        "## Guideline passages",
        "Cite with [n] where you rely on a passage. "
        "Do not cite passages you did not use.",
    ]
    for n, chunk in enumerate(chunks, start=1):
        lines.append(f"[{n}] {chunk.source_title} — {chunk.section}\n{chunk.text}")
    return "\n".join(lines)


def extract_citations(
    text: str, chunks: Sequence[RetrievedChunk]
) -> list[Citation]:
    """Map every [n] in ``text`` to its passage; unknown numbers are dropped.

    Unknown numbers stay in the text (a signal for the eval set) and are
    logged as a warning.

    Args:
        text: The model's reply.
        chunks: Passages in the order they were numbered by format_passages.

    Returns:
        One Citation per distinct valid number, in first-appearance order.
    """
    citations: list[Citation] = []
    seen: set[int] = set()
    for raw in _CITATION_RE.findall(text):
        n = int(raw)
        if n in seen:
            continue
        seen.add(n)
        if 1 <= n <= len(chunks):
            chunk = chunks[n - 1]
            citations.append(
                Citation(
                    n=n,
                    chunk_id=chunk.id,
                    source_id=chunk.source_id,
                    section=chunk.section,
                )
            )
        else:
            logger.warning(
                "coaching reply cited [%d] but only %d passages were provided",
                n,
                len(chunks),
            )
    return citations
```

Replace `_ResponseDeps` and `_user_context_instructions`:

```python
@dataclass
class _ResponseDeps:
    """Per-run input for the response agent's dynamic instructions."""

    context_prompt: str
    passage_block: str = ""


@_response_agent.instructions
def _user_context_instructions(ctx: RunContext[_ResponseDeps]) -> str:
    """Append the per-user context block (today, goals, weekly pattern,
    preferences) built by agent/context.py, then any guideline passages,
    to the static coaching rules."""
    return "\n\n".join(
        block for block in (ctx.deps.context_prompt, ctx.deps.passage_block) if block
    )
```

Replace `generate_response`:

```python
async def generate_response(
    message: str,
    data: dict,
    *,
    context_prompt: str = "",
    history: Sequence[CoachingTurn] = (),
    passages: Sequence[RetrievedChunk] = (),
) -> str:
    """Generate a grounded natural-language answer from fetched data.

    Args:
        message: The user's original question.
        data: Output of fetch_data().
        context_prompt: Per-user context block from build_system_prompt();
            appended to the model instructions. Empty string omits it.
        history: Recent conversation turns, oldest first, replayed as
            message history ahead of this question.
        passages: Retrieved guideline passages; rendered by format_passages
            and appended after the context block. Empty omits the block.

    Returns:
        Natural language response, under 3 sentences, possibly carrying
        [n] citations into ``passages``.
    """
    content = f"User question: {message}\n\nData:\n{json.dumps(data, default=str)}"
    result = await _response_agent.run(
        content,
        deps=_ResponseDeps(
            context_prompt=context_prompt, passage_block=format_passages(passages)
        ),
        message_history=_history_to_messages(history) or None,
    )
    record_run_cost(result, COACHING_MODEL, operation="coaching_response")
    return result.output
```

Add before `class CoachingAgent`:

```python
async def _user_conditions(user_id: str) -> list[str]:
    """Read ``user_goal.conditions`` for retrieval filtering ([] if no row)."""
    session_factory = get_session()
    async with session_factory() as session:
        goal = await session.get(UserGoal, user_id)
        return list(goal.conditions or []) if goal is not None else []


async def _retrieve_for(user_id: str, message: str) -> list[RetrievedChunk]:
    """Retrieve guideline passages for this user; [] on any failure."""
    try:
        conditions = await _user_conditions(user_id)
    except Exception as exc:  # noqa: BLE001 — retrieval must not fail the turn
        logger.warning("reading conditions failed for %s: %s", user_id, exc)
        conditions = []
    return await retrieve(message, conditions)
```

Replace `CoachingAgent.handle`:

```python
    async def handle(self, user_id: str, message: str) -> CoachingResult:
        """Answer a nutrition question grounded in the user's logged data.

        Args:
            user_id: Supabase Auth UUID.
            message: User's nutrition question.

        Returns:
            CoachingResult whose message is the reply (or a graceful
            "no data" message when nothing has been logged for the
            requested range), plus the parsed query, retrieved passages
            and resolved citations for persistence.
        """
        history = await get_coaching_history(user_id)
        # Independent I/O: the parse call and the context fan-out don't
        # depend on each other, so overlap them.
        parsed, context_prompt = await asyncio.gather(
            parse_query(message, history=history),
            _safe_context_prompt(user_id, message),
        )
        # Data fetch and guideline retrieval are independent too.
        data, retrieved = await asyncio.gather(
            fetch_data(user_id, parsed),
            _retrieve_for(user_id, message) if parsed.needs_guidance else _none(),
        )

        micro_nutrients = [n for n in parsed.nutrients if n not in _MACRO_ALIASES]

        if micro_nutrients and not data.get("micronutrients"):
            names = ", ".join(_humanize_nutrient_name(n) for n in micro_nutrients)
            return CoachingResult(
                message=f"I don't have data on {names} for that period.",
                parsed=parsed,
            )

        text = await generate_response(
            message,
            data,
            context_prompt=context_prompt,
            history=history,
            passages=retrieved,
        )
        return CoachingResult(
            message=text,
            parsed=parsed,
            retrieved=list(retrieved),
            citations=extract_citations(text, retrieved),
        )
```

Add this small helper next to `_retrieve_for`:

```python
async def _none() -> list[RetrievedChunk]:
    """Awaitable empty result, so gather() has a uniform shape."""
    return []
```

Update `__all__`:

```python
__all__ = [
    "Citation",
    "CoachingAgent",
    "CoachingResult",
    "QueryParsed",
    "extract_citations",
    "fetch_data",
    "format_passages",
    "generate_response",
    "parse_query",
]
```

- [ ] **Step 4: Run the new tests and the existing coaching suite**

Run: `uv run pytest tests/test_coaching_guidance.py tests/test_coaching.py -v`
Expected: all new tests pass. Existing tests that assert `await CoachingAgent().handle(...) == "..."` (e.g. `test_handle_meal_plan_feeds_today_totals_and_goals` neighbours around line 400, and the test ending `assert response == "You've had 1,240 kcal today."`) now FAIL because `handle` returns `CoachingResult`.

- [ ] **Step 5: Update existing `tests/test_coaching.py` assertions**

For every test in `tests/test_coaching.py` that compares the return of `CoachingAgent().handle(...)` to a string, change `assert response == "..."` to `assert response.message == "..."`. Locate them with:

Run: `grep -n "handle(" tests/test_coaching.py`

Run: `uv run pytest tests/test_coaching.py tests/test_coaching_guidance.py -q`
Expected: all passed

- [ ] **Step 6: Add the parse-prompt rule**

Append to `src/backend/config/prompts/query_parse_system.md`:

```markdown

needs_guidance: true when the user asks what they SHOULD eat, whether a
  food, meal, or eating pattern is healthy or appropriate for them, how to
  change their intake (cut back, add more, swap), or anything else that
  calls for a recommendation rather than a readback of their own data —
  including "is sugar ok for me", "should I eat more fibre", "what's a good
  breakfast", "how do I lower my sodium", and the meal-suggestion and
  holistic-assessment questions above. Pure data questions ("how much
  protein today", "what did I eat yesterday", "average calories last week")
  stay false.
```

- [ ] **Step 7: Add the response-prompt citation rules**

In `src/backend/config/prompts/coaching_response_system.md`, add these bullets at the end of the `<rules>` list (before `</rules>`):

```markdown
- Guideline passages: when a "## Guideline passages" block is present,
  prefer those passages over general knowledge wherever they apply, and
  cite each passage you rely on with its bracketed number, e.g. "keep added
  sugar under 10% of calories [1]". Only cite numbers that appear in the
  block; never invent a citation. If no passage covers the question, answer
  from general knowledge without any bracketed number.
- Guideline passages are population-level recommendations. Never present
  them as medical advice for the user's specific condition, and for
  medication, dosing, or treatment questions suggest the user speak with
  their clinician.
```

- [ ] **Step 8: Confirm the prompts still load and the parse agent accepts the new field**

Run: `uv run python -c "from backend.config import get_tunables; t = get_tunables(); assert 'needs_guidance' in t.prompts.query_parse_system; assert 'Guideline passages' in t.prompts.coaching_response_system; print('ok')"`
Expected: `ok`

Run: `uv run pytest tests/test_coaching.py tests/test_coaching_guidance.py tests/test_config.py -q`
Expected: all passed

- [ ] **Step 9: Commit**

```bash
git add src/backend/agent/coaching.py src/backend/config/prompts/query_parse_system.md src/backend/config/prompts/coaching_response_system.md tests/test_coaching.py tests/test_coaching_guidance.py
git commit -F - <<'EOF'
feat(coaching): retrieve and cite guideline passages when a question needs guidance

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01E8q5bjtSR2xhaZbUKGTiM4
EOF
```

---

### Task 5: Persist `coaching_response`, trace id, span attributes, `response_id`

**Files:**
- Create: `src/backend/agent/coaching_store.py`
- Modify: `src/backend/agent/orchestrator.py` (imports at top; call site at ~line 152 `result = await _handle_coaching(user_id, user_input)`; `_handle_coaching` at ~line 356)
- Modify: `tests/test_orchestrator.py`, `tests/test_orchestrator_quota.py` (mocks of `_coaching_agent.handle` return a `CoachingResult` now)
- Test: `tests/test_coaching_store.py` (new), `tests/test_orchestrator_quota.py` (extend)

**Interfaces:**
- Consumes: `CoachingResult`, `QueryParsed` (Task 4); `CoachingResponse` (Task 1); `COACHING_MODEL` from `backend.agent.llm`.
- Produces:
  - `save_coaching_response(*, user_id: str, conversation_id: str | None, query: str, result: CoachingResult, model: str, trace_id: str | None) -> str | None` — the new row id, or `None` when the write failed.
  - `_handle_coaching(user_id, user_input, conversation_id: str | None = None) -> dict` — adds `"response_id"` when persisted.
  - HTTP `POST /meals/log` coaching replies now carry `response_id` (string) when persisted.

- [ ] **Step 1: Write the failing store tests**

```python
# tests/test_coaching_store.py
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from backend.agent.coaching import Citation, CoachingResult, QueryParsed
from backend.agent.coaching_store import save_coaching_response
from backend.db.models import CoachingResponse
from backend.guidelines.retrieval import RetrievedChunk


def _result() -> CoachingResult:
    chunk = RetrievedChunk(
        id="aaaaaaaa-0000-0000-0000-000000000001",
        source_id="dga-2020",
        source_title="DGA",
        section="Limit added sugars",
        text="...",
        score=0.9,
    )
    return CoachingResult(
        message="Under 10% [1].",
        parsed=QueryParsed(time_range="today", needs_guidance=True),
        retrieved=[chunk],
        citations=[
            Citation(n=1, chunk_id=chunk.id, source_id="dga-2020", section=chunk.section)
        ],
    )


def _session_factory(session: MagicMock) -> MagicMock:
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=session)


@pytest.mark.asyncio
async def test_save_writes_row_and_returns_its_id() -> None:
    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()

    with patch(
        "backend.agent.coaching_store.get_session",
        return_value=_session_factory(session),
    ):
        response_id = await save_coaching_response(
            user_id="user-1",
            conversation_id="thread-1",
            query="is sugar ok?",
            result=_result(),
            model="gemini-2.5-flash",
            trace_id="0" * 32,
        )

    assert response_id is not None
    UUID(response_id)  # valid uuid string
    row = session.add.call_args.args[0]
    assert isinstance(row, CoachingResponse)
    assert row.id == response_id
    assert row.user_id == "user-1"
    assert row.conversation_id == "thread-1"
    assert row.query == "is sugar ok?"
    assert row.parsed_query["needs_guidance"] is True
    assert row.retrieved_chunk_ids == ["aaaaaaaa-0000-0000-0000-000000000001"]
    assert row.citations == [
        {
            "n": 1,
            "chunk_id": "aaaaaaaa-0000-0000-0000-000000000001",
            "source_id": "dga-2020",
            "section": "Limit added sugars",
        }
    ]
    assert row.response_text == "Under 10% [1]."
    assert row.model == "gemini-2.5-flash"
    assert row.trace_id == "0" * 32
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_returns_none_and_logs_when_commit_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock(side_effect=RuntimeError("db down"))

    with (
        patch(
            "backend.agent.coaching_store.get_session",
            return_value=_session_factory(session),
        ),
        caplog.at_level(logging.ERROR, logger="backend.agent.coaching_store"),
    ):
        response_id = await save_coaching_response(
            user_id="user-1",
            conversation_id=None,
            query="q",
            result=_result(),
            model="m",
            trace_id=None,
        )

    assert response_id is None
    assert "coaching_response write failed" in caplog.text
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_coaching_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.agent.coaching_store'`

- [ ] **Step 3: Implement the store**

Create `src/backend/agent/coaching_store.py`:

```python
"""Persist one coaching turn to coaching_response. Never raises."""

from __future__ import annotations

import logging
import uuid

from backend.agent.coaching import CoachingResult
from backend.db.models import CoachingResponse
from backend.db.session import get_session

logger = logging.getLogger(__name__)


async def save_coaching_response(
    *,
    user_id: str,
    conversation_id: str | None,
    query: str,
    result: CoachingResult,
    model: str,
    trace_id: str | None,
) -> str | None:
    """Insert a coaching_response row and return its id.

    The reply has already been generated; persistence is bookkeeping for
    feedback and eval export, so a failure is logged and swallowed rather
    than surfaced to the user.

    Args:
        user_id: Supabase Auth UUID.
        conversation_id: Thread id from the request, if any.
        query: Raw user message.
        result: Output of CoachingAgent.handle().
        model: Model name used for the response (COACHING_MODEL).
        trace_id: OTel trace id as 32 hex chars, or None outside a trace.

    Returns:
        The new row's id as a string, or None if the write failed.
    """
    row_id = str(uuid.uuid4())
    try:
        session_factory = get_session()
        async with session_factory() as session:
            session.add(
                CoachingResponse(
                    id=row_id,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    query=query,
                    parsed_query=result.parsed.model_dump(mode="json"),
                    retrieved_chunk_ids=[c.id for c in result.retrieved],
                    citations=[c.model_dump() for c in result.citations],
                    response_text=result.message,
                    model=model,
                    trace_id=trace_id,
                )
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001 — see docstring
        logger.error("coaching_response write failed for %s: %s", user_id, exc)
        return None
    return row_id


__all__ = ["save_coaching_response"]
```

- [ ] **Step 4: Run store tests**

Run: `uv run pytest tests/test_coaching_store.py -v`
Expected: 2 passed

- [ ] **Step 5: Write the failing orchestrator tests**

Append to `tests/test_orchestrator_quota.py`:

```python
from backend.agent.coaching import CoachingResult, QueryParsed


def _coaching_result(text: str) -> CoachingResult:
    return CoachingResult(message=text, parsed=QueryParsed(time_range="today"))


@pytest.mark.asyncio
async def test_coaching_persists_and_returns_response_id():
    from backend.agent.orchestrator import _handle_coaching

    with (
        patch("backend.agent.orchestrator.consume_llm_credit", new=AsyncMock(return_value=True)),
        patch("backend.agent.orchestrator._coaching_agent") as mock_coaching,
        patch(
            "backend.agent.orchestrator.save_coaching_response",
            new_callable=AsyncMock,
            return_value="resp-123",
        ) as save_mock,
    ):
        mock_coaching.handle = AsyncMock(return_value=_coaching_result("120g today."))
        result = await _handle_coaching("user-1", "protein today?", conversation_id="t-1")

    assert result == {
        "status": "success",
        "message": "120g today.",
        "paused": False,
        "items": [],
        "response_id": "resp-123",
    }
    kwargs = save_mock.await_args.kwargs
    assert kwargs["user_id"] == "user-1"
    assert kwargs["conversation_id"] == "t-1"
    assert kwargs["query"] == "protein today?"
    assert kwargs["result"].message == "120g today."
    assert kwargs["model"]  # COACHING_MODEL value
    assert kwargs["trace_id"] is None or len(kwargs["trace_id"]) == 32


@pytest.mark.asyncio
async def test_coaching_omits_response_id_when_persistence_fails():
    from backend.agent.orchestrator import _handle_coaching

    with (
        patch("backend.agent.orchestrator.consume_llm_credit", new=AsyncMock(return_value=True)),
        patch("backend.agent.orchestrator._coaching_agent") as mock_coaching,
        patch(
            "backend.agent.orchestrator.save_coaching_response",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        mock_coaching.handle = AsyncMock(return_value=_coaching_result("120g today."))
        result = await _handle_coaching("user-1", "protein today?")

    assert "response_id" not in result
    assert result["message"] == "120g today."
```

Also change the existing `test_coaching_under_quota_calls_agent` in that file so the mock returns `_coaching_result("You had 120g protein today.")` and add `patch("backend.agent.orchestrator.save_coaching_response", new=AsyncMock(return_value=None))` to its `with` block.

- [ ] **Step 6: Run to verify failure**

Run: `uv run pytest tests/test_orchestrator_quota.py -v`
Expected: FAIL — `AttributeError: <module 'backend.agent.orchestrator'> does not have the attribute 'save_coaching_response'`

- [ ] **Step 7: Modify the orchestrator**

Add imports at the top of `src/backend/agent/orchestrator.py` (keep stdlib/third-party/local ordering):

```python
from opentelemetry import trace

from backend.agent.coaching import CoachingAgent
from backend.agent.coaching_store import save_coaching_response
from backend.agent.llm import COACHING_MODEL, FLASH_LITE_MODEL, make_llm
```

Change the call site in `handle_message`:

```python
        if is_coaching:
            result = await _handle_coaching(
                user_id, user_input, conversation_id=thread_id
            )
```

Replace `_handle_coaching`:

```python
async def _handle_coaching(
    user_id: str, user_input: str, conversation_id: str | None = None
) -> dict[str, Any]:
    """Answer a nutrition question via the coaching agent.

    Consumes one quota credit per coaching turn (not per internal LLM call
    inside CoachingAgent). Returns an upgrade prompt when over quota.
    Persists the reply to coaching_response so it can be rated and exported;
    a failed write drops ``response_id`` but still returns the reply.

    Args:
        user_id: Supabase Auth UUID.
        user_input: User's nutrition question.
        conversation_id: Thread id from the request, stored with the reply.

    Returns:
        Dict with status, message, paused=False, items=[] — same shape as
        meal logging so web and Telegram channels stay uniform — plus
        response_id when the reply was persisted.
    """
    granted = await consume_llm_credit(user_id)
    if not granted:
        return {
            "status": "success",
            "message": _UPGRADE_MSG,
            "paused": False,
            "items": [],
        }
    with logfire.span("coaching") as span:
        result = await _coaching_agent.handle(user_id, user_input)
        span_ctx = trace.get_current_span().get_span_context()
        trace_id = format(span_ctx.trace_id, "032x") if span_ctx.is_valid else None
        response_id = await save_coaching_response(
            user_id=user_id,
            conversation_id=conversation_id,
            query=user_input,
            result=result,
            model=COACHING_MODEL,
            trace_id=trace_id,
        )
        span.set_attribute("needs_guidance", result.parsed.needs_guidance)
        span.set_attribute("retrieved_count", len(result.retrieved))
        span.set_attribute("citation_count", len(result.citations))
        span.set_attribute("response_id", response_id or "")

    response: dict[str, Any] = {
        "status": "success",
        "message": result.message,
        "paused": False,
        "items": [],
    }
    if response_id is not None:
        response["response_id"] = response_id
    return response
```

- [ ] **Step 8: Update `tests/test_orchestrator.py` mocks**

Add near the top (after the imports):

```python
from backend.agent.coaching import CoachingResult, QueryParsed


def _coaching_result(text: str) -> CoachingResult:
    return CoachingResult(message=text, parsed=QueryParsed(time_range="today"))


@pytest.fixture(autouse=True)
def _no_response_store():
    """Keep coaching_response persistence off the database in every test."""
    with patch(
        "backend.agent.orchestrator.save_coaching_response",
        new_callable=AsyncMock,
        return_value=None,
    ):
        yield
```

Then, at every `patch("backend.agent.orchestrator._coaching_agent.handle", ..., return_value="...")` (lines ~187, ~298, ~403) wrap the string: `return_value=_coaching_result("You've had 1,240 kcal today.")`.

- [ ] **Step 9: Run the orchestrator suites**

Run: `uv run pytest tests/test_orchestrator.py tests/test_orchestrator_quota.py tests/test_telegram.py -q`
Expected: all passed (the Telegram handler only reads `result["message"]`, `paused`, `items`)

- [ ] **Step 10: Commit**

```bash
git add src/backend/agent/coaching_store.py src/backend/agent/orchestrator.py tests/test_coaching_store.py tests/test_orchestrator.py tests/test_orchestrator_quota.py
git commit -F - <<'EOF'
feat(coaching): persist every reply with its inputs and return response_id

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01E8q5bjtSR2xhaZbUKGTiM4
EOF
```

---

### Task 6: Feedback API route

**Files:**
- Create: `src/backend/api/coaching_feedback.py`
- Modify: `src/backend/main.py` (import list at lines 9-20; `include_router` block at lines 65-74)
- Test: `tests/test_coaching_feedback_api.py`

**Interfaces:**
- Consumes: `CoachingResponse` (Task 1), `get_current_user_id` from `backend.auth.supabase`, `user_rate_limiter` from `backend.ratelimit`, `get_session`.
- Produces: `POST /coaching/{response_id}/feedback` with body `FeedbackRequest {rating: "up"|"down", comment?: str<=500}` returning `FeedbackResponse {response_id: str, rating: str}`; `FEEDBACK_RATE_LIMIT = 60`.

- [ ] **Step 1: Write the failing route tests**

```python
# tests/test_coaching_feedback_api.py
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import coaching_feedback
from backend.db.models import CoachingResponse
from backend.ratelimit import RateLimitResult

RESPONSE_ID = "3f7c1a2e-9b4d-4c8e-8f1a-2b3c4d5e6f70"


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(coaching_feedback.router)
    return app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DEV_BYPASS_AUTH", "true")
    return TestClient(_make_app())


@pytest.fixture
def anon_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("DEV_BYPASS_AUTH", raising=False)
    return TestClient(_make_app())


@pytest.fixture(autouse=True)
def _no_rate_limit():
    with patch(
        "backend.ratelimit.check_rate_limit",
        new_callable=AsyncMock,
        return_value=RateLimitResult(allowed=True, remaining=59),
    ):
        yield


def _auth(user_id: str) -> dict[str, str]:
    return {"X-Debug-User-Id": user_id}


def _row(user_id: str) -> CoachingResponse:
    return CoachingResponse(
        id=RESPONSE_ID,
        user_id=user_id,
        query="q",
        parsed_query={},
        retrieved_chunk_ids=[],
        citations=[],
        response_text="r",
        model="m",
        trace_id="ab" * 16,
    )


def _session_with(row: CoachingResponse | None) -> MagicMock:
    session = MagicMock()
    session.get = AsyncMock(return_value=row)
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=session)


def test_unauthenticated_returns_401(anon_client: TestClient) -> None:
    resp = anon_client.post(f"/coaching/{RESPONSE_ID}/feedback", json={"rating": "up"})
    assert resp.status_code == 401


def test_unknown_id_returns_404(client: TestClient) -> None:
    with patch(
        "backend.api.coaching_feedback.get_session", return_value=_session_with(None)
    ):
        resp = client.post(
            f"/coaching/{RESPONSE_ID}/feedback",
            json={"rating": "up"},
            headers=_auth("user-1"),
        )
    assert resp.status_code == 404


def test_foreign_id_returns_404(client: TestClient) -> None:
    with patch(
        "backend.api.coaching_feedback.get_session",
        return_value=_session_with(_row("someone-else")),
    ):
        resp = client.post(
            f"/coaching/{RESPONSE_ID}/feedback",
            json={"rating": "down"},
            headers=_auth("user-1"),
        )
    assert resp.status_code == 404


def test_rating_overwrites_prior_rating_and_sets_rated_at(client: TestClient) -> None:
    row = _row("user-1")
    row.rating = "up"
    factory = _session_with(row)

    with patch("backend.api.coaching_feedback.get_session", return_value=factory):
        resp = client.post(
            f"/coaching/{RESPONSE_ID}/feedback",
            json={"rating": "down", "comment": "wrong number"},
            headers=_auth("user-1"),
        )

    assert resp.status_code == 200
    assert resp.json() == {"response_id": RESPONSE_ID, "rating": "down"}
    assert row.rating == "down"
    assert row.rating_comment == "wrong number"
    assert isinstance(row.rated_at, datetime)
    factory.return_value.commit.assert_awaited_once()


def test_comment_over_500_chars_is_rejected(client: TestClient) -> None:
    resp = client.post(
        f"/coaching/{RESPONSE_ID}/feedback",
        json={"rating": "down", "comment": "x" * 501},
        headers=_auth("user-1"),
    )
    assert resp.status_code == 422


def test_invalid_rating_is_rejected(client: TestClient) -> None:
    resp = client.post(
        f"/coaching/{RESPONSE_ID}/feedback",
        json={"rating": "meh"},
        headers=_auth("user-1"),
    )
    assert resp.status_code == 422


def test_non_uuid_id_is_rejected(client: TestClient) -> None:
    resp = client.post(
        "/coaching/not-a-uuid/feedback", json={"rating": "up"}, headers=_auth("user-1")
    )
    assert resp.status_code == 422
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_coaching_feedback_api.py -v`
Expected: FAIL with `ImportError: cannot import name 'coaching_feedback' from 'backend.api'`

- [ ] **Step 3: Implement the route**

Create `src/backend/api/coaching_feedback.py`:

```python
"""Thumbs up/down on a persisted coaching reply."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

import logfire
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.auth.supabase import get_current_user_id
from backend.db.models import CoachingResponse
from backend.db.session import get_session
from backend.ratelimit import user_rate_limiter

router = APIRouter(prefix="/coaching", tags=["coaching"])

# Per user per minute. Ratings are cheap but each is a DB write.
FEEDBACK_RATE_LIMIT = 60


class FeedbackRequest(BaseModel):
    rating: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=500)

    model_config = ConfigDict(extra="forbid")


class FeedbackResponse(BaseModel):
    response_id: str
    rating: str

    model_config = ConfigDict(extra="forbid")


@router.post(
    "/{response_id}/feedback",
    dependencies=[
        Depends(user_rate_limiter("feedback", limit=FEEDBACK_RATE_LIMIT, window_s=60))
    ],
)
async def rate_response(
    response_id: uuid.UUID,
    req: FeedbackRequest,
    user_id: str = Depends(get_current_user_id),
) -> FeedbackResponse:
    """Store or overwrite the caller's rating of one coaching reply.

    Returns 404 both for unknown ids and for replies that belong to
    another user, so ids cannot be probed.
    """
    session_factory = get_session()
    async with session_factory() as session:
        row = await session.get(CoachingResponse, str(response_id))
        if row is None or row.user_id != user_id:
            raise HTTPException(status_code=404, detail="Coaching response not found")
        row.rating = req.rating
        row.rating_comment = req.comment
        row.rated_at = datetime.now(timezone.utc)
        await session.commit()
        logfire.info(
            "coaching_feedback",
            response_id=str(response_id),
            rating=req.rating,
            trace_id=row.trace_id,
        )
    return FeedbackResponse(response_id=str(response_id), rating=req.rating)
```

- [ ] **Step 4: Run route tests**

Run: `uv run pytest tests/test_coaching_feedback_api.py -v`
Expected: 7 passed

- [ ] **Step 5: Register the router**

In `src/backend/main.py`, add `coaching_feedback` to the `from backend.api import (...)` list (alphabetical), and add after `app.include_router(push.router)`:

```python
app.include_router(coaching_feedback.router)
```

Run: `uv run python -c "from backend.main import app; print([r.path for r in app.routes if 'coaching' in r.path])"`
Expected: `['/coaching/{response_id}/feedback']`

- [ ] **Step 6: Commit**

```bash
git add src/backend/api/coaching_feedback.py src/backend/main.py tests/test_coaching_feedback_api.py
git commit -F - <<'EOF'
feat(api): POST /coaching/{id}/feedback to rate a coaching reply

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01E8q5bjtSR2xhaZbUKGTiM4
EOF
```

---

### Task 7: Goals `conditions` API and Settings UI

**Files:**
- Modify: `src/backend/api/goals.py` (`GoalResponse`, `GoalCreate`, `GoalUpdate`, `_to_response`, `create_goals`, `update_goals`)
- Modify: `frontend/src/api/types.ts` (`GoalData` at line 137)
- Modify: `frontend/src/pages/SettingsPage.tsx` (state at ~line 40, seed at ~line 49, `switchMode` ~line 69, `handleSave` ~line 81, chips card ~line 214)
- Test: `tests/test_goals_api.py` (append)

**Interfaces:**
- Consumes: `UserGoal.conditions` (Task 1).
- Produces: `Condition = Literal["diabetes", "prediabetes", "hypertension", "ckd"]`; `conditions: list[Condition]` on `GoalCreate`/`GoalUpdate` (default `[]`), `conditions: list[str]` on `GoalResponse`; `GoalData.conditions?: string[]` in TS.

- [ ] **Step 1: Write the failing API tests**

Append to `tests/test_goals_api.py`:

```python
def _round_trip_session() -> tuple[MagicMock, dict[str, UserGoal]]:
    store: dict[str, UserGoal] = {}
    session = MagicMock()

    async def fake_get(model, user_id):
        return store.get(user_id)

    def fake_add(goal):
        store[goal.user_id] = goal

    async def noop(*_args):
        pass

    session.get = fake_get
    session.add = fake_add
    session.commit = noop
    session.refresh = noop
    return _mock_session_factory(session), store


def test_conditions_round_trip_through_post_put_get(client: TestClient) -> None:
    factory, _ = _round_trip_session()
    base = {"kcal_goal": 2000, "protein_goal": 150, "fiber_goal": 30, "dietary_prefs": {}}

    with patch("backend.api.goals.get_session", return_value=factory):
        post = client.post(
            "/goals",
            json={**base, "conditions": ["prediabetes"]},
            headers=_auth_headers("user-1"),
        )
        assert post.status_code == 201
        assert post.json()["conditions"] == ["prediabetes"]

        put = client.put(
            "/goals",
            json={**base, "conditions": ["diabetes", "hypertension"]},
            headers=_auth_headers("user-1"),
        )
        assert put.status_code == 200

        get = client.get("/goals", headers=_auth_headers("user-1"))
        assert get.json()["conditions"] == ["diabetes", "hypertension"]


def test_conditions_default_to_empty_list(client: TestClient) -> None:
    factory, _ = _round_trip_session()
    with patch("backend.api.goals.get_session", return_value=factory):
        post = client.post(
            "/goals",
            json={"kcal_goal": 2000, "protein_goal": 150, "fiber_goal": 30},
            headers=_auth_headers("user-1"),
        )
    assert post.status_code == 201
    assert post.json()["conditions"] == []


def test_invalid_condition_is_rejected(client: TestClient) -> None:
    factory, _ = _round_trip_session()
    with patch("backend.api.goals.get_session", return_value=factory):
        resp = client.put(
            "/goals",
            json={
                "kcal_goal": 2000,
                "protein_goal": 150,
                "fiber_goal": 30,
                "conditions": ["gout"],
            },
            headers=_auth_headers("user-1"),
        )
    assert resp.status_code == 422
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_goals_api.py -v -k conditions`
Expected: FAIL — `KeyError: 'conditions'` on the POST response body (and 422 for the first test because `extra="forbid"` rejects the field)

- [ ] **Step 3: Extend `goals.py`**

After `TrackingMode = Literal["goals", "mindful"]` add:

```python
Condition = Literal["diabetes", "prediabetes", "hypertension", "ckd"]
```

Add to `GoalResponse` (after `dietary_prefs: dict`):

```python
    conditions: list[str]
```

Add to both `GoalCreate` and `GoalUpdate` (after `dietary_prefs`):

```python
    conditions: list[Condition] = Field(default_factory=list)
```

In `_to_response` add `conditions=list(goal.conditions or []),`.

In `create_goals` add `conditions=req.conditions,` to the `UserGoal(...)` constructor.

In `update_goals` add `goal.conditions = req.conditions` after `goal.dietary_prefs = req.dietary_prefs`.

- [ ] **Step 4: Run goals tests**

Run: `uv run pytest tests/test_goals_api.py -v`
Expected: all passed

- [ ] **Step 5: Frontend types and Settings UI**

In `frontend/src/api/types.ts`, inside `GoalData` after `dietary_prefs`:

```typescript
  /** Declared health conditions; picks which dietary guidelines the coach may cite. */
  conditions?: string[];
```

In `frontend/src/pages/SettingsPage.tsx`:

After `const [dietaryPrefs, setDietaryPrefs] = useState<string[]>([])` add:

```typescript
  const [conditions, setConditions] = useState<string[]>([])
```

Inside the seed block (`if (goals && seededFrom !== goals) {`) add:

```typescript
    setConditions(goals.conditions ?? [])
```

In both `switchMode` and `handleSave`, add `conditions,` after the `dietary_prefs: prefsObject(),` line of the mutate payload.

After the `preferenceOptions` array add:

```typescript
  const conditionOptions = [
    { label: 'Diabetes', value: 'diabetes' },
    { label: 'Prediabetes', value: 'prediabetes' },
    { label: 'Hypertension', value: 'hypertension' },
    { label: 'Chronic kidney disease', value: 'ckd' },
  ]
```

After the closing `</Card>` of the "Dietary Preferences Card" (before `{/* Action Buttons */}`) add:

```tsx
          {/* Health Conditions Card */}
          <Card className="border border-sand-border bg-sand backdrop-blur-md">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <ShieldAlert className="w-4 h-4 text-sage-deep" />
                Health conditions
              </CardTitle>
              <CardDescription>
                Used to choose which dietary guidelines the coach references. Mealsy does not
                give medical advice.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <PreferenceChips
                options={conditionOptions}
                selectedValues={conditions}
                onChange={setConditions}
              />
            </CardContent>
          </Card>
```

(`ShieldAlert` is already imported from `lucide-react` in this file.)

- [ ] **Step 6: Type-check and lint the frontend**

Run: `cd frontend && npx tsc -b && npx eslint src/pages/SettingsPage.tsx src/api/types.ts`
Expected: no output, exit 0

- [ ] **Step 7: Commit**

```bash
git add src/backend/api/goals.py tests/test_goals_api.py frontend/src/api/types.ts frontend/src/pages/SettingsPage.tsx
git commit -F - <<'EOF'
feat(goals): health conditions on GET/PUT /goals and the Settings page

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01E8q5bjtSR2xhaZbUKGTiM4
EOF
```

---

### Task 8: Frontend feedback buttons, hook, store wiring

**Files:**
- Modify: `frontend/package.json` (dev deps via npm)
- Modify: `frontend/src/api/types.ts` (`LogMealResponse` at line 100)
- Modify: `frontend/src/stores/mealStore.ts` (`ChatMessage` line 14; `logToApi` line 131)
- Create: `frontend/src/hooks/use-coaching-feedback.ts`
- Create: `frontend/src/components/chat/feedback-buttons.tsx`
- Modify: `frontend/src/components/chat/ChatThread.tsx` (import block; agent branch ~line 199 between the bubble row `</div>` and `{hasCard && (`)
- Test: `frontend/src/components/chat/feedback-buttons.test.tsx`

**Interfaces:**
- Consumes: `POST /coaching/{response_id}/feedback` (Task 6); `response_id` in `/meals/log` replies (Task 5); `apiClient`, `ApiError` from `frontend/src/api/client.ts`.
- Produces:
  - `ChatMessage.responseId?: string`; `LogMealResponse.response_id?: string | null`.
  - `useCoachingFeedback(): UseMutationResult<CoachingFeedbackResponse, ApiError, CoachingFeedbackInput>` where `CoachingFeedbackInput = { responseId: string; rating: 'up' | 'down'; comment?: string }`.
  - `FeedbackButtons({ responseId }: { responseId: string })`.

- [ ] **Step 1: Install component-test tooling**

Run: `cd frontend && npm install -D @testing-library/react@^16 @testing-library/dom@^10 jsdom@^25`
Expected: `added N packages`, `package.json` devDependencies gains the three entries.

- [ ] **Step 2: Write the failing component test**

```tsx
// frontend/src/components/chat/feedback-buttons.test.tsx
// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const mutateAsync = vi.fn()

vi.mock('../../hooks/use-coaching-feedback', () => ({
  useCoachingFeedback: () => ({ mutateAsync, isPending: false }),
}))

const { FeedbackButtons } = await import('./feedback-buttons')

/** Typed accessor so `.disabled` is available without jest-dom matchers. */
const button = (name: string) => screen.getByRole('button', { name }) as HTMLButtonElement

describe('FeedbackButtons', () => {
  beforeEach(() => {
    mutateAsync.mockReset()
    mutateAsync.mockResolvedValue({ response_id: 'r1', rating: 'up' })
  })
  afterEach(cleanup)

  it('posts an up rating and disables both buttons once rated', async () => {
    render(<FeedbackButtons responseId="r1" />)

    fireEvent.click(screen.getByRole('button', { name: 'Helpful' }))

    await waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith({ responseId: 'r1', rating: 'up' }),
    )
    await waitFor(() => {
      expect(button('Helpful').disabled).toBe(true)
      expect(button('Not helpful').disabled).toBe(true)
    })
    expect(screen.queryByPlaceholderText('What was off? (optional)')).toBeNull()
  })

  it('posts a down rating, reveals the comment box, and posts again with the comment', async () => {
    mutateAsync.mockResolvedValue({ response_id: 'r1', rating: 'down' })
    render(<FeedbackButtons responseId="r1" />)

    fireEvent.click(screen.getByRole('button', { name: 'Not helpful' }))

    await waitFor(() =>
      expect(mutateAsync).toHaveBeenCalledWith({ responseId: 'r1', rating: 'down' }),
    )
    const input = await screen.findByPlaceholderText('What was off? (optional)')
    fireEvent.change(input, { target: { value: 'wrong protein number' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() =>
      expect(mutateAsync).toHaveBeenLastCalledWith({
        responseId: 'r1',
        rating: 'down',
        comment: 'wrong protein number',
      }),
    )
    await waitFor(() =>
      expect(screen.queryByPlaceholderText('What was off? (optional)')).toBeNull(),
    )
    expect(screen.getByText('Thanks for the feedback.')).toBeTruthy()
  })

  it('shows an error and re-enables the buttons when the request fails', async () => {
    mutateAsync.mockRejectedValue(new Error('network'))
    render(<FeedbackButtons responseId="r1" />)

    fireEvent.click(screen.getByRole('button', { name: 'Helpful' }))

    expect(await screen.findByText("Couldn't send feedback. Try again.")).toBeTruthy()
    expect(button('Helpful').disabled).toBe(false)
    expect(button('Not helpful').disabled).toBe(false)
  })
})
```

- [ ] **Step 3: Run to verify failure**

Run: `cd frontend && npx vitest run src/components/chat/feedback-buttons.test.tsx`
Expected: FAIL — `Failed to resolve import "./feedback-buttons"`

- [ ] **Step 4: Write the hook**

Create `frontend/src/hooks/use-coaching-feedback.ts`:

```typescript
import { useMutation } from '@tanstack/react-query'

import { apiClient, ApiError } from '../api/client'

export interface CoachingFeedbackInput {
  responseId: string
  rating: 'up' | 'down'
  comment?: string
}

export interface CoachingFeedbackResponse {
  response_id: string
  rating: 'up' | 'down'
}

/** Rate a coaching reply. Errors are ApiError; callers surface them inline. */
export function useCoachingFeedback() {
  return useMutation<CoachingFeedbackResponse, ApiError, CoachingFeedbackInput>({
    mutationFn: ({ responseId, rating, comment }) =>
      apiClient.post<CoachingFeedbackResponse>(
        `/coaching/${responseId}/feedback`,
        comment ? { rating, comment } : { rating },
      ),
  })
}
```

- [ ] **Step 5: Write the component**

Create `frontend/src/components/chat/feedback-buttons.tsx`:

```tsx
import { useState } from 'react'

import { ThumbsDown, ThumbsUp } from 'lucide-react'

import { useCoachingFeedback } from '../../hooks/use-coaching-feedback'

interface FeedbackButtonsProps {
  responseId: string
}

type FeedbackState = 'idle' | 'submitting' | 'up' | 'down'

const ERROR_TEXT = "Couldn't send feedback. Try again."

/**
 * Thumbs up / down under a coaching reply. Up posts immediately. Down posts
 * immediately, then offers a one-line optional comment that posts again with
 * the same rating. Once rated, both buttons stay disabled.
 */
export function FeedbackButtons({ responseId }: FeedbackButtonsProps) {
  const feedback = useCoachingFeedback()
  const [state, setState] = useState<FeedbackState>('idle')
  const [comment, setComment] = useState('')
  const [showComment, setShowComment] = useState(false)
  const [sentComment, setSentComment] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const rated = state === 'up' || state === 'down'
  const busy = state === 'submitting'

  const rate = async (rating: 'up' | 'down') => {
    setState('submitting')
    setError(null)
    try {
      await feedback.mutateAsync({ responseId, rating })
      setState(rating)
      setShowComment(rating === 'down')
    } catch {
      setState('idle')
      setError(ERROR_TEXT)
    }
  }

  const sendComment = async () => {
    const trimmed = comment.trim()
    if (!trimmed) {
      setShowComment(false)
      return
    }
    setError(null)
    try {
      await feedback.mutateAsync({ responseId, rating: 'down', comment: trimmed })
      setShowComment(false)
      setSentComment(true)
    } catch {
      setError(ERROR_TEXT)
    }
  }

  const iconClass = (active: boolean) =>
    `press rounded-full p-1.5 border transition-colors disabled:cursor-default ${
      active
        ? 'bg-container border-sage text-sage-deep'
        : 'border-transparent text-muted hover:text-ink hover:border-sand-border disabled:opacity-60'
    }`

  return (
    <div className="ml-7 flex flex-col gap-1.5">
      <div className="flex items-center gap-1">
        <button
          type="button"
          aria-label="Helpful"
          onClick={() => rate('up')}
          disabled={rated || busy}
          className={iconClass(state === 'up')}
        >
          <ThumbsUp className="w-3.5 h-3.5" />
        </button>
        <button
          type="button"
          aria-label="Not helpful"
          onClick={() => rate('down')}
          disabled={rated || busy}
          className={iconClass(state === 'down')}
        >
          <ThumbsDown className="w-3.5 h-3.5" />
        </button>
        {sentComment && <span className="text-[12px] text-muted">Thanks for the feedback.</span>}
        {error && (
          <span role="alert" className="text-[12px] text-red-600">
            {error}
          </span>
        )}
      </div>
      {showComment && (
        <div className="flex items-center gap-1.5">
          <input
            type="text"
            value={comment}
            maxLength={500}
            onChange={(e) => setComment(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void sendComment()
            }}
            placeholder="What was off? (optional)"
            className="flex-1 bg-sand border border-sand-border rounded-full px-3 py-1.5 text-[13px] text-ink placeholder:text-muted/70 focus:outline-none focus:border-sage"
          />
          <button
            type="button"
            onClick={() => void sendComment()}
            className="press text-[13px] font-medium text-sage-deep px-2.5 py-1.5 rounded-full border border-sand-border hover:border-sage"
          >
            Send
          </button>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 6: Run the component test**

Run: `cd frontend && npx vitest run src/components/chat/feedback-buttons.test.tsx`
Expected: 3 passed

- [ ] **Step 7: Wire the store and types**

In `frontend/src/api/types.ts`, inside `LogMealResponse` after `meal_id?: string | null;`:

```typescript
  /** Set on coaching replies once persisted; absent for meal logging. */
  response_id?: string | null;
```

In `frontend/src/stores/mealStore.ts`, inside `ChatMessage` after `resolvedKcal?: number;`:

```typescript
  // Server id of a persisted coaching reply; enables the feedback buttons.
  responseId?: string;
```

In `logToApi`, change the first `addMessage` call to:

```typescript
      get().addMessage({
        sender: 'agent',
        text: data.message,
        paused: data.paused,
        items: data.items,
        responseId: data.response_id ?? undefined,
      })
```

- [ ] **Step 8: Render the buttons in `ChatThread.tsx`**

Add to the import block (after the `ConfirmationCard` import):

```typescript
import { FeedbackButtons } from './feedback-buttons'
```

In the `messages.map` agent branch, directly after the `</div>` that closes `<div className={isUser ? '' : 'flex items-start gap-2.5 w-full'}>` and before `{hasCard && (`, add:

```tsx
              {!isUser && msg.responseId && <FeedbackButtons responseId={msg.responseId} />}
```

- [ ] **Step 9: Type-check, lint, run all frontend tests**

Run: `cd frontend && npx tsc -b && npx eslint src && npx vitest run`
Expected: tsc silent, eslint silent, vitest `Test Files  2 passed` (client.test.ts + feedback-buttons.test.tsx)

- [ ] **Step 10: Manual check against the dev backend**

Run: `cd frontend && npm run dev` with the backend up (`uv run uvicorn backend.main:app --reload --port 8000`). In chat ask "is sugar ok for me?". Expected: an agent bubble ending with `[1]`-style citations when guidelines match, thumbs buttons under it; clicking Not helpful shows the comment input; Network tab shows `POST /coaching/<uuid>/feedback` → 200. A meal-logging reply shows no buttons.

- [ ] **Step 11: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/api/types.ts frontend/src/stores/mealStore.ts frontend/src/hooks/use-coaching-feedback.ts frontend/src/components/chat/feedback-buttons.tsx frontend/src/components/chat/feedback-buttons.test.tsx frontend/src/components/chat/ChatThread.tsx
git commit -F - <<'EOF'
feat(web): thumbs up/down with optional comment under coaching replies

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01E8q5bjtSR2xhaZbUKGTiM4
EOF
```

---

### Task 9: `export_feedback` CLI

**Files:**
- Create: `src/backend/guidelines/export_feedback.py`
- Test: `tests/test_export_feedback.py`

**Interfaces:**
- Consumes: `CoachingResponse`, `GuidelineChunk`, `UserGoal` (Task 1); `get_session`, `dispose_engine`.
- Produces:
  - `build_query(*, rated_only: bool, since: date | None) -> Select` selecting `(CoachingResponse, UserGoal.conditions)`.
  - `row_to_record(resp: CoachingResponse, conditions: list[str] | None, chunks: dict[str, GuidelineChunk]) -> dict`.
  - `export_feedback(session, *, rated_only: bool, since: date | None) -> list[dict]`.
  - `main(argv) -> int`; CLI `python -m backend.guidelines.export_feedback [--rated-only] [--since DATE] --out eval/coaching_feedback.jsonl`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_export_feedback.py
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from backend.db.models import CoachingResponse, GuidelineChunk
from backend.guidelines.export_feedback import (
    build_query,
    export_feedback,
    main,
    row_to_record,
)

CHUNK_ID = "aaaaaaaa-0000-0000-0000-000000000001"


def _chunk() -> GuidelineChunk:
    return GuidelineChunk(
        id=CHUNK_ID,
        source_id="dga-2020",
        source_title="DGA",
        source_url="u",
        section="Limit added sugars",
        condition="general",
        ordinal=3,
        text="Limit added sugars.",
        content_hash="h",
    )


def _response() -> CoachingResponse:
    return CoachingResponse(
        id="3f7c1a2e-9b4d-4c8e-8f1a-2b3c4d5e6f70",
        user_id="user-1",
        conversation_id="t-1",
        query="is sugar ok?",
        parsed_query={"time_range": "today", "needs_guidance": True},
        retrieved_chunk_ids=[CHUNK_ID],
        citations=[{"n": 1, "chunk_id": CHUNK_ID, "source_id": "dga-2020", "section": "x"}],
        response_text="Under 10% [1].",
        model="gemini-2.5-flash",
        trace_id="ab" * 16,
        rating="down",
        rating_comment="too vague",
        created_at=datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc),
    )


def test_row_to_record_has_spec_keys_and_no_user_id() -> None:
    record = row_to_record(_response(), ["prediabetes"], {CHUNK_ID: _chunk()})

    assert set(record) == {
        "response_id",
        "created_at",
        "query",
        "parsed_query",
        "conditions",
        "retrieved",
        "response_text",
        "citations",
        "rating",
        "rating_comment",
        "trace_id",
    }
    assert "user_id" not in json.dumps(record)
    assert record["response_id"] == "3f7c1a2e-9b4d-4c8e-8f1a-2b3c4d5e6f70"
    assert record["created_at"] == "2026-09-09T12:00:00+00:00"
    assert record["conditions"] == ["prediabetes"]
    assert record["retrieved"] == [
        {"source_id": "dga-2020", "section": "Limit added sugars", "text": "Limit added sugars."}
    ]
    assert record["rating"] == "down"


def test_row_to_record_handles_missing_goal_and_chunk() -> None:
    record = row_to_record(_response(), None, {})
    assert record["conditions"] == []
    assert record["retrieved"] == []


def test_build_query_filters() -> None:
    sql_all = str(build_query(rated_only=False, since=None).compile(dialect=postgresql.dialect()))
    sql_rated = str(
        build_query(rated_only=True, since=date(2026, 9, 1)).compile(
            dialect=postgresql.dialect()
        )
    )
    assert "rating IS NOT NULL" not in sql_all
    assert "rating IS NOT NULL" in sql_rated
    assert "created_at >=" in sql_rated
    assert "LEFT OUTER JOIN user_goal" in sql_all


@pytest.mark.asyncio
async def test_export_feedback_joins_chunks_in_one_extra_query() -> None:
    rows_result = MagicMock()
    rows_result.all.return_value = [(_response(), ["diabetes"])]
    chunks_result = MagicMock()
    chunks_result.scalars.return_value.all.return_value = [_chunk()]
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[rows_result, chunks_result])

    records = await export_feedback(session, rated_only=True, since=None)

    assert session.execute.await_count == 2
    assert len(records) == 1
    assert records[0]["retrieved"][0]["section"] == "Limit added sugars"
    assert records[0]["conditions"] == ["diabetes"]


def test_main_writes_jsonl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "out.jsonl"

    async def fake_run(*, rated_only: bool, since: date | None) -> list[dict]:
        assert rated_only is True and since == date(2026, 9, 1)
        return [{"response_id": "a"}, {"response_id": "b"}]

    monkeypatch.setattr("backend.guidelines.export_feedback._run_export", fake_run)

    code = main(["--rated-only", "--since", "2026-09-01", "--out", str(out)])

    assert code == 0
    assert out.read_text().splitlines() == ['{"response_id": "a"}', '{"response_id": "b"}']
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_export_feedback.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.guidelines.export_feedback'`

- [ ] **Step 3: Implement the exporter**

Create `src/backend/guidelines/export_feedback.py`:

```python
"""Export coaching_response rows as JSONL for the coaching eval set.

Usage:
    PYTHONPATH=src uv run python -m backend.guidelines.export_feedback \\
        [--rated-only] [--since YYYY-MM-DD] --out eval/coaching_feedback.jsonl

One JSON object per row; ``user_id`` is never exported. ``conditions`` is
joined from user_goal at export time and ``retrieved`` carries the text of
every chunk that was shown to the model, cited or not.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import CoachingResponse, GuidelineChunk, UserGoal
from backend.db.session import dispose_engine, get_session


def build_query(*, rated_only: bool, since: date | None) -> Select:
    """Select (CoachingResponse, conditions) oldest first, with optional filters."""
    stmt = (
        select(CoachingResponse, UserGoal.conditions)
        .outerjoin(UserGoal, UserGoal.user_id == CoachingResponse.user_id)
        .order_by(CoachingResponse.created_at)
    )
    if rated_only:
        stmt = stmt.where(CoachingResponse.rating.is_not(None))
    if since is not None:
        stmt = stmt.where(CoachingResponse.created_at >= since)
    return stmt


def row_to_record(
    resp: CoachingResponse,
    conditions: list[str] | None,
    chunks: dict[str, GuidelineChunk],
) -> dict:
    """Shape one row as the eval JSONL record (no user_id)."""
    retrieved = [
        {
            "source_id": chunks[cid].source_id,
            "section": chunks[cid].section,
            "text": chunks[cid].text,
        }
        for cid in resp.retrieved_chunk_ids or []
        if cid in chunks
    ]
    return {
        "response_id": resp.id,
        "created_at": resp.created_at.isoformat(),
        "query": resp.query,
        "parsed_query": resp.parsed_query,
        "conditions": list(conditions or []),
        "retrieved": retrieved,
        "response_text": resp.response_text,
        "citations": resp.citations,
        "rating": resp.rating,
        "rating_comment": resp.rating_comment,
        "trace_id": resp.trace_id,
    }


async def export_feedback(
    session: AsyncSession, *, rated_only: bool, since: date | None
) -> list[dict]:
    """Fetch matching rows plus their chunks and return JSONL-ready records."""
    rows = (await session.execute(build_query(rated_only=rated_only, since=since))).all()
    chunk_ids = {cid for resp, _ in rows for cid in (resp.retrieved_chunk_ids or [])}
    chunks: dict[str, GuidelineChunk] = {}
    if chunk_ids:
        result = await session.execute(
            select(GuidelineChunk).where(GuidelineChunk.id.in_(chunk_ids))
        )
        chunks = {str(c.id): c for c in result.scalars().all()}
    return [row_to_record(resp, conditions, chunks) for resp, conditions in rows]


async def _run_export(*, rated_only: bool, since: date | None) -> list[dict]:
    """Open a session, export, and dispose the engine (fresh loop per run)."""
    session_factory = get_session()
    try:
        async with session_factory() as session:
            return await export_feedback(session, rated_only=rated_only, since=since)
    finally:
        await dispose_engine()


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    parser = argparse.ArgumentParser(description="Export coaching feedback as JSONL.")
    parser.add_argument("--rated-only", action="store_true")
    parser.add_argument("--since", type=date.fromisoformat, default=None)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    records = asyncio.run(_run_export(rated_only=args.rated_only, since=args.since))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, default=str) + "\n")
    print(f"wrote {len(records)} records to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_export_feedback.py -v`
Expected: 5 passed

- [ ] **Step 5: Run against the dev database**

Run: `PYTHONPATH=src uv run python -m backend.guidelines.export_feedback --out eval/coaching_feedback.jsonl && head -c 400 eval/coaching_feedback.jsonl`
Expected: `wrote N records to eval/coaching_feedback.jsonl` (N ≥ 1 after the Task 8 manual check) and the first line starts with `{"response_id": "`.

- [ ] **Step 6: Keep the export out of git and run the whole backend suite**

Append `eval/coaching_feedback.jsonl` to `.gitignore`.

Run: `uv run pytest -m "not integration" -q`
Expected: all passed

- [ ] **Step 7: Commit**

```bash
git add src/backend/guidelines/export_feedback.py tests/test_export_feedback.py .gitignore
git commit -F - <<'EOF'
feat(guidelines): export rated coaching replies as JSONL for the eval set

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01E8q5bjtSR2xhaZbUKGTiM4
EOF
```

---

## Spec decisions resolved in this plan

- Prompts live in `src/backend/config/prompts/*.md`, not `tunables.yaml`; the plan edits those files.
- `coaching_response.user_id` is a FK to `user_goal.user_id` (ON DELETE CASCADE), matching `user_memory`; the Supabase `auth.users` table is not referenced by any project table.
- `coaching_response.id` is generated client-side (`uuid4`) so the row id is known without a `refresh()`.
- `conversation_id` is the `thread_id` already passed to `handle_message` (falls back to `user_id` in `/meals/log`).
- Retrieval calls `backend.agent.llm.embed_text` directly (it is already async); no thread.
- "Roughly 400 tokens" is approximated as `MAX_CHUNK_WORDS = 300` (no tokenizer dependency).
- `source_id` must equal the filename stem; seed ids are `dga-2020`, `who-healthy-diet`, `ada-soc-nutrition`.
- No toast library exists in the frontend; `FeedbackButtons` surfaces errors inline.
- Component tests need `@testing-library/react`, `@testing-library/dom`, `jsdom` (added in Task 8) with a per-file `// @vitest-environment jsdom` pragma.
- Non-UUID `response_id` path params return 422 (FastAPI type coercion) rather than 404.
