"""Export coaching_response rows as JSONL for the coaching eval set.

Usage:
    PYTHONPATH=src uv run python -m backend.guidelines.export_feedback \\
        [--rated-only] [--since YYYY-MM-DD] --out eval/coaching_feedback.jsonl

One JSON object per row; ``user_id`` is never exported. ``conditions`` is
joined from user_goal at export time; ``retrieved`` is the snapshot of every
passage shown to the model (cited or not) that was stored on the row when the
reply was written, so a later re-ingest of the corpus cannot rewrite history.

Every record has a ``source``: ``coaching`` for a coaching turn, ``plan_sample``
for a recipe a dietitian rejected in the review queue (with their comment).
Plan samples are always exported, whether or not ``--rated-only`` is given.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import CoachingResponse, ProfileEntry, Recommendation, ReviewItem
from backend.db.session import dispose_engine, get_session


def build_query(*, rated_only: bool, since: date | None) -> Select:
    """Select (CoachingResponse, conditions) oldest first, with optional filters."""
    conditions = (
        select(func.array_agg(ProfileEntry.value["condition"].as_string()))
        .where(
            ProfileEntry.user_id == CoachingResponse.user_id,
            ProfileEntry.entry_type == "diagnosis",
            ProfileEntry.state == "confirmed",
        )
        .scalar_subquery()
    )
    stmt = select(CoachingResponse, conditions).order_by(CoachingResponse.created_at)
    if rated_only:
        stmt = stmt.where(CoachingResponse.rating.is_not(None))
    if since is not None:
        stmt = stmt.where(CoachingResponse.created_at >= since)
    return stmt


def row_to_record(resp: CoachingResponse, conditions: list[str] | None) -> dict:
    """Shape one row as the eval JSONL record (no user_id).

    Args:
        resp: The stored coaching turn, carrying its own ``retrieved`` snapshot.
        conditions: The user's declared conditions at export time, or None.

    Returns:
        A JSON-serializable record with the spec's keys.
    """
    retrieved = [
        {
            "source_id": passage.get("source_id"),
            "section": passage.get("section"),
            "text": passage.get("text"),
        }
        for passage in resp.retrieved or []
    ]
    return {
        "source": "coaching",
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
    """Fetch matching rows and return JSONL-ready records (one query)."""
    rows = (
        await session.execute(build_query(rated_only=rated_only, since=since))
    ).all()
    return [row_to_record(resp, conditions) for resp, conditions in rows]


def build_plan_sample_query(*, since: date | None) -> Select:
    """Select (ReviewItem, Recommendation) for rejected plan samples, oldest first."""
    stmt = (
        select(ReviewItem, Recommendation)
        .join(Recommendation, Recommendation.id == ReviewItem.subject_id)
        .where(ReviewItem.kind == "plan_sample", ReviewItem.decision == "rejected")
        .order_by(ReviewItem.decided_at)
    )
    if since is not None:
        stmt = stmt.where(ReviewItem.decided_at >= since)
    return stmt


def plan_sample_to_record(item: ReviewItem, rec: Recommendation) -> dict:
    """Shape one rejected plan sample as a JSONL record (no user_id).

    Args:
        item: The decided review item; its comment says why it was rejected.
        rec: The recommendation that was sampled.

    Returns:
        A JSON-serializable record.
    """
    snapshot = rec.check_snapshot
    return {
        "source": "plan_sample",
        "recommendation_id": rec.id,
        "created_at": rec.created_at.isoformat(),
        "decided_at": item.decided_at.isoformat() if item.decided_at else None,
        "recipe": rec.recipe,
        "check": {
            "passed": snapshot.get("passed"),
            "applied": [a.get("phrase") for a in snapshot.get("applied", [])],
            "notes": snapshot.get("notes", []),
        },
        "review_comment": item.comment,
    }


async def export_plan_samples(
    session: AsyncSession, *, since: date | None
) -> list[dict]:
    """Rejected plan samples with the reviewer's comment (one query)."""
    rows = (await session.execute(build_plan_sample_query(since=since))).all()
    return [plan_sample_to_record(item, rec) for item, rec in rows]


async def _run_export(*, rated_only: bool, since: date | None) -> list[dict]:
    """Open a session, export, and dispose the engine (fresh loop per run)."""
    session_factory = get_session()
    try:
        async with session_factory() as session:
            records = await export_feedback(session, rated_only=rated_only, since=since)
            return records + await export_plan_samples(session, since=since)
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
