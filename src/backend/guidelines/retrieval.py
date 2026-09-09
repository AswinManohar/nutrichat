"""pgvector retrieval over guideline_chunk, filtered by user conditions."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from backend.agent.llm import embed_text
from backend.db.models import GuidelineChunk
from backend.db.session import get_session

logger = logging.getLogger(__name__)

# user_goal.conditions value -> guideline_chunk.condition tag. Conditions
# without a curated source yet (hypertension, ckd) are stored but unmapped.
_CONDITION_TO_TAG: dict[str, str] = {
    "diabetes": "diabetes",
    "prediabetes": "diabetes",
}


class RetrievedChunk(BaseModel):
    """One guideline passage with its cosine similarity to the query."""

    id: str
    source_id: str
    source_title: str
    section: str
    text: str
    score: float

    model_config = ConfigDict(extra="forbid")


def condition_tags(conditions: Sequence[str]) -> list[str]:
    """Map declared conditions to chunk tags, always including ``general``.

    Args:
        conditions: Values from ``user_goal.conditions``.

    Returns:
        Ordered, de-duplicated tags starting with "general".
    """
    tags = ["general"]
    for condition in conditions:
        tag = _CONDITION_TO_TAG.get(condition)
        if tag is not None and tag not in tags:
            tags.append(tag)
    return tags


async def retrieve(
    query: str, conditions: Sequence[str], k: int = 5
) -> list[RetrievedChunk]:
    """Return the ``k`` guideline passages nearest to ``query``.

    Retrieval is an enrichment: any failure (embedding API, database) is
    logged as a warning and yields an empty list so the coaching turn still
    answers without citations.

    Args:
        query: The user's message.
        conditions: The user's declared conditions (see condition_tags).
        k: Maximum passages to return.

    Returns:
        Passages ordered by descending similarity; empty on error.
    """
    tags = condition_tags(conditions)
    try:
        vector = await embed_text(query)
        distance = GuidelineChunk.embedding.cosine_distance(vector).label("distance")
        stmt = (
            select(GuidelineChunk, distance)
            .where(GuidelineChunk.condition.in_(tags))
            .order_by(distance)
            .limit(k)
        )
        session_factory = get_session()
        async with session_factory() as session:
            rows = (await session.execute(stmt)).all()
    except Exception as exc:  # noqa: BLE001 — see docstring
        logger.warning("guideline retrieval failed, answering without it: %s", exc)
        return []

    return [
        RetrievedChunk(
            id=str(chunk.id),
            source_id=chunk.source_id,
            source_title=chunk.source_title,
            section=chunk.section,
            text=chunk.text,
            score=1.0 - float(dist),
        )
        for chunk, dist in rows
    ]


__all__ = ["RetrievedChunk", "condition_tags", "retrieve"]
