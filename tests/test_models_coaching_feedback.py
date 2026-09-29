from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

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
    assert isinstance(cols.retrieved.type, JSONB)
    assert cols.retrieved.nullable is False
    assert str(cols.retrieved.server_default.arg) == "[]"
    assert cols.rating.nullable is True
    assert cols.trace_id.nullable is True
    assert cols.user_id.nullable is False
    assert {"query", "parsed_query", "citations", "response_text", "model"} <= set(
        cols.keys()
    )
