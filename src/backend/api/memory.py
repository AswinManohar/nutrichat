"""What Mealsy remembers about the user: read the profile, remove a fact.

Deprecated: ``/profile`` (api/profile.py) replaces these routes. They stay for
the released app and go once the app release that uses ``/profile`` is live.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import logfire
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict

from backend.agent.coaching.context import fetch_staples
from backend.agent.memory.facts import (
    RemoveFact,
    apply_ops,
    load_state,
)
from backend.auth.supabase import get_current_user_id
from backend.ratelimit import user_rate_limiter

router = APIRouter(prefix="/memory", tags=["memory"])

# Per user per minute. Reads are one indexed query plus a Redis get.
READ_RATE_LIMIT = 60
DELETE_RATE_LIMIT = 30


class FactOut(BaseModel):
    """One remembered fact."""

    id: str
    fact: str
    kind: str
    source: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(extra="forbid")


class MemoryResponse(BaseModel):
    """Response for GET /memory.

    ``facts`` are stored and can be removed. ``diet_settings`` are the
    user's own Settings chips, and ``staples`` are computed from their meal
    log; both are shown for transparency and changed elsewhere.
    ``coach_uses_profile`` is always true now; the field stays for the
    released app.
    """

    coach_uses_profile: bool
    facts: list[FactOut]
    diet_settings: list[str]
    staples: dict[str, list[str]]

    model_config = ConfigDict(extra="forbid")


@router.get(
    "",
    deprecated=True,
    dependencies=[
        Depends(user_rate_limiter("memory_read", limit=READ_RATE_LIMIT, window_s=60))
    ],
)
async def get_memory(user_id: str = Depends(get_current_user_id)) -> MemoryResponse:
    """Return everything the coach remembers about the caller (use GET /profile)."""
    state = await load_state(user_id)
    return MemoryResponse(
        coach_uses_profile=True,
        facts=[FactOut(**fact.model_dump()) for fact in state.facts],
        diet_settings=state.diet_chips,
        staples=await fetch_staples(user_id),
    )


@router.delete(
    "/{fact_id}",
    status_code=204,
    deprecated=True,
    dependencies=[
        Depends(
            user_rate_limiter("memory_delete", limit=DELETE_RATE_LIMIT, window_s=60)
        )
    ],
)
async def delete_fact(
    fact_id: uuid.UUID, user_id: str = Depends(get_current_user_id)
) -> Response:
    """Remove one fact; it is not learned again unless the user restates it.

    Returns 404 both for unknown ids and for facts that belong to another
    user, so ids cannot be probed.
    """
    outcome = await apply_ops(user_id, [RemoveFact(id=str(fact_id))], "user")
    if outcome.n_applied == 0:
        raise HTTPException(status_code=404, detail="Fact not found")
    logfire.info("memory_fact_deleted", fact_id=str(fact_id))
    return Response(status_code=204)
