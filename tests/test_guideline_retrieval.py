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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_condition_filter_against_live_postgres() -> None:
    """Requires DATABASE_URL with migration 014 applied."""
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
