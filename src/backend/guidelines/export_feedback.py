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
