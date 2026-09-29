from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from backend.db.models import CoachingResponse
from backend.guidelines.export_feedback import (
    build_query,
    export_feedback,
    main,
    row_to_record,
)

CHUNK_ID = "aaaaaaaa-0000-0000-0000-000000000001"


def _response() -> CoachingResponse:
    return CoachingResponse(
        id="3f7c1a2e-9b4d-4c8e-8f1a-2b3c4d5e6f70",
        user_id="user-1",
        conversation_id="t-1",
        query="is sugar ok?",
        parsed_query={"time_range": "today", "needs_guidance": True},
        retrieved_chunk_ids=[CHUNK_ID],
        retrieved=[
            {
                "chunk_id": CHUNK_ID,
                "source_id": "dga-2020",
                "source_title": "DGA",
                "section": "Limit added sugars",
                "text": "Limit added sugars.",
            }
        ],
        citations=[
            {"n": 1, "chunk_id": CHUNK_ID, "source_id": "dga-2020", "section": "x"}
        ],
        response_text="Under 10% [1].",
        model="gemini-2.5-flash",
        trace_id="ab" * 16,
        rating="down",
        rating_comment="too vague",
        created_at=datetime(2026, 9, 9, 12, 0, tzinfo=UTC),
    )


def test_row_to_record_has_spec_keys_and_no_user_id() -> None:
    record = row_to_record(_response(), ["prediabetes"])

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
        {
            "source_id": "dga-2020",
            "section": "Limit added sugars",
            "text": "Limit added sugars.",
        }
    ]
    assert record["rating"] == "down"


def test_row_to_record_uses_the_stored_snapshot_not_the_chunk_table() -> None:
    resp = _response()
    resp.retrieved = [
        {
            "chunk_id": CHUNK_ID,
            "source_id": "dga-2020",
            "source_title": "DGA",
            "section": "Older wording",
            "text": "The passage as the model saw it.",
        }
    ]

    record = row_to_record(resp, ["prediabetes"])

    assert record["retrieved"] == [
        {
            "source_id": "dga-2020",
            "section": "Older wording",
            "text": "The passage as the model saw it.",
        }
    ]


def test_row_to_record_with_empty_snapshot_exports_empty_retrieved() -> None:
    resp = _response()
    resp.retrieved = []

    record = row_to_record(resp, None)

    assert record["conditions"] == []
    assert record["retrieved"] == []


def test_build_query_filters() -> None:
    sql_all = str(
        build_query(rated_only=False, since=None).compile(dialect=postgresql.dialect())
    )
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
async def test_export_feedback_reads_rows_without_touching_guideline_chunk() -> None:
    rows_result = MagicMock()
    rows_result.all.return_value = [(_response(), ["diabetes"])]
    session = MagicMock()
    session.execute = AsyncMock(return_value=rows_result)

    records = await export_feedback(session, rated_only=True, since=None)

    assert session.execute.await_count == 1
    sql = str(session.execute.await_args.args[0].compile(dialect=postgresql.dialect()))
    assert "guideline_chunk" not in sql
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
    assert out.read_text().splitlines() == [
        '{"response_id": "a"}',
        '{"response_id": "b"}',
    ]
