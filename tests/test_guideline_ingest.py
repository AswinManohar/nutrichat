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
