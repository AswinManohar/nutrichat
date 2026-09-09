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
