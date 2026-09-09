from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.sql.dml import Delete

from backend.guidelines.chunking import Chunk, content_hash
from backend.guidelines.ingest import (
    IngestStats,
    _run,
    delete_missing_sources,
    sync_source,
)


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


def _sources_session(stored_source_ids: list[str]) -> MagicMock:
    session = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = stored_source_ids
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_source_whose_file_is_gone_is_deleted() -> None:
    session = _sources_session(["demo", "retired"])

    removed = await delete_missing_sources(session, ["demo"])

    assert removed == 1
    delete_stmt = session.execute.await_args_list[1].args[0]
    assert isinstance(delete_stmt, Delete)
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_deletion_when_every_stored_source_still_has_a_file() -> None:
    session = _sources_session(["demo"])

    removed = await delete_missing_sources(session, ["demo"])

    assert removed == 0
    assert session.execute.await_count == 1
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_dry_run_counts_missing_sources_without_deleting() -> None:
    session = _sources_session(["demo", "retired"])

    removed = await delete_missing_sources(session, ["demo"], dry_run=True)

    assert removed == 1
    assert session.execute.await_count == 1
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_directory_exits_2_without_opening_a_session(
    tmp_path: Path,
) -> None:
    """A mistyped --dir must not let the orphan sweep empty the corpus."""
    with patch("backend.guidelines.ingest.get_session") as get_session:
        code = await _run(tmp_path / "no-such-dir", dry_run=False)

    assert code == 2
    get_session.assert_not_called()


@pytest.mark.asyncio
async def test_empty_directory_skips_the_orphan_sweep(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with patch("backend.guidelines.ingest.get_session") as get_session:
        code = await _run(tmp_path, dry_run=False)

    assert code == 0
    get_session.assert_not_called()
    assert "orphan sweep skipped" in capsys.readouterr().out
