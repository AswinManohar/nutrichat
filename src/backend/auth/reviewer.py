"""Reviewer access for the dietitian queue (spec 013, research R16)."""

from __future__ import annotations

import logging
import os

from fastapi import Depends, HTTPException

from backend.auth.supabase import get_current_user_id

logger = logging.getLogger(__name__)

_REVIEWERS_ENV = "REVIEWER_USER_IDS"


def reviewer_ids() -> frozenset[str]:
    """User ids allowed to review, read from the environment on every call.

    Reading per request means a Railway variable change needs no code path
    beyond the service restart it already triggers, and tests can set it.

    Returns:
        The lower-cased ids; empty when the variable is unset or blank.
    """
    raw = os.environ.get(_REVIEWERS_ENV, "")
    return frozenset(part.strip().lower() for part in raw.split(",") if part.strip())


async def require_reviewer(user_id: str = Depends(get_current_user_id)) -> str:
    """Dependency: a valid Supabase user whose id is in ``REVIEWER_USER_IDS``.

    Args:
        user_id: The authenticated user (401 when the token is invalid).

    Returns:
        The reviewer's user id.

    Raises:
        HTTPException: 403 when the user is not a reviewer.
    """
    if user_id.lower() not in reviewer_ids():
        logger.warning("non-reviewer %s tried to use the review queue", user_id)
        raise HTTPException(status_code=403, detail="Reviewer access required")
    return user_id
