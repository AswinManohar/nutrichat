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
            Citation(
                n=1, chunk_id=chunk.id, source_id="dga-2020", section=chunk.section
            )
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
    assert row.retrieved == [
        {
            "chunk_id": "aaaaaaaa-0000-0000-0000-000000000001",
            "source_id": "dga-2020",
            "source_title": "DGA",
            "section": "Limit added sugars",
            "text": "...",
        }
    ]
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


@pytest.mark.asyncio
async def test_save_stores_routing_record_beside_gemini_parse() -> None:
    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    routing = {
        "path": "judgment",
        "certainty": 0.98,
        "raw_choice": "coaching",
        "reports_food": 0.97,
        "needs_guidance_jev": 0.94,
        "offer_to_log": True,
    }

    with patch(
        "backend.agent.coaching_store.get_session",
        return_value=_session_factory(session),
    ):
        await save_coaching_response(
            user_id="user-1",
            conversation_id="thread-1",
            query="I had pizza, was that bad?",
            result=_result(),
            model="gemini-2.5-flash",
            trace_id=None,
            routing=routing,
        )

    parsed = session.add.call_args.args[0].parsed_query
    assert parsed["routing"] == routing
    assert parsed["needs_guidance"] is True  # Gemini's own decision, untouched


@pytest.mark.asyncio
async def test_save_without_routing_has_no_routing_key() -> None:
    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()

    with patch(
        "backend.agent.coaching_store.get_session",
        return_value=_session_factory(session),
    ):
        await save_coaching_response(
            user_id="user-1",
            conversation_id=None,
            query="hi",
            result=_result(),
            model="gemini-2.5-flash",
            trace_id=None,
        )

    assert "routing" not in session.add.call_args.args[0].parsed_query
