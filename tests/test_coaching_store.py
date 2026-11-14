from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from backend.agent.coaching.agent import Citation, CoachingResult, QueryParsed
from backend.agent.coaching.store import save_coaching_response
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


async def test_save_writes_row_and_returns_its_id() -> None:
    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()

    with patch(
        "backend.agent.coaching.store.get_session",
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


async def test_save_returns_none_and_logs_when_commit_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock(side_effect=RuntimeError("db down"))

    with (
        patch(
            "backend.agent.coaching.store.get_session",
            return_value=_session_factory(session),
        ),
        caplog.at_level(logging.ERROR, logger="backend.agent.coaching.store"),
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
        "backend.agent.coaching.store.get_session",
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


async def test_save_without_routing_has_no_routing_key() -> None:
    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()

    with patch(
        "backend.agent.coaching.store.get_session",
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


async def test_link_recommendation_sets_the_response_id(db_user: str) -> None:
    import uuid

    from backend.agent.coaching.store import link_recommendation
    from backend.db.models import Recommendation
    from backend.db.session import get_session

    rec_id = str(uuid.uuid4())
    response_id = await save_coaching_response(
        user_id=db_user,
        conversation_id=None,
        query="dinner?",
        result=_result(),
        model="m",
        trace_id=None,
    )
    async with get_session()() as session:
        session.add(
            Recommendation(
                id=rec_id,
                user_id=db_user,
                recipe={},
                check_snapshot={},
                attempts=1,
                status="shown",
            )
        )
        await session.commit()

    await link_recommendation(rec_id, response_id)

    async with get_session()() as session:
        assert (await session.get(Recommendation, rec_id)).coaching_response_id == (
            response_id
        )


async def test_link_recommendation_logs_a_failure_and_does_not_raise(caplog) -> None:
    from backend.agent.coaching.store import link_recommendation

    with (
        patch(
            "backend.agent.coaching.store.get_session",
            side_effect=OSError("postgres down"),
        ),
        caplog.at_level(logging.ERROR),
    ):
        await link_recommendation("rec", "resp")

    assert "linking recommendation rec" in caplog.text


async def test_the_orchestrator_links_a_recipe_to_its_reply() -> None:
    from backend.agent.coaching import handler
    from backend.agent.coaching.agent import QueryParsed

    result = CoachingResult(
        message="Recipe",
        parsed=QueryParsed(time_range="today", suggests_meal=True),
        recommendation_id="rec-1",
    )
    for response_id, expected in (("resp-1", 1), (None, 0)):
        with (
            patch.object(handler, "consume_llm_credit", AsyncMock(return_value=True)),
            patch.object(
                handler._coaching_agent, "handle", AsyncMock(return_value=result)
            ),
            patch.object(
                handler,
                "save_coaching_response",
                AsyncMock(return_value=response_id),
            ),
            patch.object(handler, "link_recommendation", AsyncMock()) as link,
        ):
            await handler.handle_coaching("user-1", "dinner?")

        assert link.await_count == expected
        if expected:
            link.assert_awaited_once_with("rec-1", "resp-1")


async def test_a_recipe_reply_carries_the_constraint_note_on_its_own() -> None:
    from backend.agent.coaching import handler
    from backend.agent.coaching.agent import QueryParsed
    from tests.recipe_helpers import make_recipe

    note = "Kept this free of peanut because of your peanut allergy."
    result = CoachingResult(
        message=f"Rice bowl\n\n{note}",
        parsed=QueryParsed(time_range="today", suggests_meal=True),
        recipe=make_recipe("rice"),
        recommendation_id="rec-1",
        constraint_note=note,
    )
    with (
        patch.object(handler, "consume_llm_credit", AsyncMock(return_value=True)),
        patch.object(handler._coaching_agent, "handle", AsyncMock(return_value=result)),
        patch.object(handler, "save_coaching_response", AsyncMock(return_value=None)),
    ):
        response = await handler.handle_coaching("user-1", "dinner?")

    assert response["constraint_note"] == note
    assert response["recommendation_id"] == "rec-1"
    assert note in response["message"]


async def test_a_reply_without_a_recipe_has_no_constraint_note() -> None:
    from backend.agent.coaching import handler
    from backend.agent.coaching.agent import QueryParsed

    result = CoachingResult(
        message="120 g today.", parsed=QueryParsed(time_range="today")
    )
    with (
        patch.object(handler, "consume_llm_credit", AsyncMock(return_value=True)),
        patch.object(handler._coaching_agent, "handle", AsyncMock(return_value=result)),
        patch.object(handler, "save_coaching_response", AsyncMock(return_value=None)),
    ):
        response = await handler.handle_coaching("user-1", "protein?")

    assert "constraint_note" not in response
