"""The patient's safety profile: hard entries, history and today's limits.

Contract: specs/013-patient-safety-profile/contracts/profile-api.md. Every
body is a Pydantic model with ``extra="forbid"``. Repeating an action that
was already applied returns the entry; a state the action cannot reach is a 409.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.agent.memory import load_state
from backend.auth.supabase import get_current_user_id
from backend.config import get_tunables
from backend.db.models import Recommendation
from backend.db.session import get_session
from backend.safety import profile
from backend.safety.limits import LimitsToday, limits_today
from backend.safety.tables import ClinicalTables, TablesUnavailable, load_tables

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/profile", tags=["profile"])


class EntryOut(BaseModel):
    """One hard entry."""

    id: str
    type: profile.EntryType
    label: str
    value: dict
    source: profile.EntrySource
    state: profile.EntryState
    created_at: datetime
    confirmed_at: datetime | None
    retire_requested: bool

    model_config = ConfigDict(extra="forbid")


class HistoryEntryOut(EntryOut):
    """A hard entry with how it ended."""

    retired_at: datetime | None
    retired_by: str | None
    retired_reason: str | None
    replaces_id: str | None


class SoftFactOut(BaseModel):
    """One soft preference."""

    id: str
    kind: str
    text: str
    source: str
    created_at: datetime | None
    updated_at: datetime | None

    model_config = ConfigDict(extra="forbid")


class CareTeamMember(BaseModel):
    """A clinician the profile is shared with (the role does not exist yet)."""

    name: str
    role: str

    model_config = ConfigDict(extra="forbid")


class ProfileOut(BaseModel):
    """Response of GET /profile."""

    version: str
    hard: list[EntryOut]
    pending_count: int
    care_team: list[CareTeamMember]
    soft: list[SoftFactOut]
    missing_values: list[str]

    model_config = ConfigDict(extra="forbid")


class EntryIn(BaseModel):
    """Body of POST /profile/entries."""

    type: profile.EntryType
    value: dict
    label: str | None = Field(default=None, max_length=200)
    client_request_id: str | None = Field(default=None, min_length=1, max_length=64)
    source: profile.EntrySource = "patient"
    replaces_id: str | None = Field(
        default=None, description="Edit: the confirmed entry this one supersedes"
    )

    model_config = ConfigDict(extra="forbid")


class RetireIn(BaseModel):
    """Body of POST /profile/entries/{id}/retire."""

    confirm: Literal[True]
    # Retiring is idempotent by state, so the key needs no storage of its own.
    client_request_id: str | None = Field(default=None, min_length=1, max_length=64)

    model_config = ConfigDict(extra="forbid")


class MealFeedbackIn(BaseModel):
    """Body of POST /profile/meals/{recommendation_id}/feedback."""

    status: Literal["accepted", "rejected"]
    reason: str | None = Field(default=None, max_length=500)

    model_config = ConfigDict(extra="forbid")


class MealFeedbackOut(BaseModel):
    """The recommendation's status after the feedback."""

    recommendation_id: str
    status: Literal["accepted", "rejected"]

    model_config = ConfigDict(extra="forbid")


def _unavailable() -> HTTPException:
    return HTTPException(
        status_code=503, detail=get_tunables().safety.profile_unavailable_text
    )


def _tables() -> ClinicalTables:
    try:
        return load_tables()
    except TablesUnavailable as exc:
        logger.error("clinical tables unavailable: %s", exc)
        raise _unavailable() from exc


def _entry_out(entry: profile.HardEntry, tables: ClinicalTables) -> EntryOut:
    return EntryOut(
        id=entry.id,
        type=entry.type,
        label=profile.label_for(entry, tables),
        value=entry.value.model_dump(exclude_none=True),
        source=entry.source,
        state=entry.state,
        created_at=entry.created_at,
        confirmed_at=entry.confirmed_at,
        retire_requested=entry.retire_requested_at is not None
        and entry.state == "confirmed",
    )


async def _act(action: Awaitable[profile.HardEntry]) -> EntryOut:
    """Run one profile write and map domain errors to HTTP statuses."""
    try:
        entry = await action
    except profile.EntryNotFound as exc:
        raise HTTPException(status_code=404, detail="Entry not found") from exc
    except profile.StateConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except profile.ProfileFull as exc:
        raise HTTPException(
            status_code=409, detail="The profile is full; remove an entry first"
        ) from exc
    return _entry_out(entry, _tables())


@router.get("")
async def get_profile(user_id: str = Depends(get_current_user_id)) -> ProfileOut:
    """The caller's live hard entries and soft preferences.

    Returns 503 with the retry message when the hard profile cannot be read:
    never a partial list.
    """
    try:
        entries = await profile.load_hard_profile(user_id)
        state = await load_state(user_id)
    except Exception as exc:  # noqa: BLE001 - any failure must not look like "empty"
        logger.error("loading profile failed for %s: %s", user_id, exc)
        raise _unavailable() from exc
    tables = _tables()
    return ProfileOut(
        version=profile.version_of(entries),
        hard=[_entry_out(e, tables) for e in entries],
        pending_count=sum(1 for e in entries if e.state == "pending"),
        care_team=[],
        soft=[
            SoftFactOut(
                id=f.id,
                kind=f.kind,
                text=f.fact,
                source=f.source,
                created_at=f.created_at,
                updated_at=f.updated_at,
            )
            for f in state.facts
        ],
        missing_values=profile.missing_values(entries, tables),
    )


@router.get("/history")
async def get_history(
    user_id: str = Depends(get_current_user_id),
) -> list[HistoryEntryOut]:
    """Every hard entry, retired ones included, newest first."""
    try:
        entries = await profile.load_history(user_id)
    except Exception as exc:  # noqa: BLE001 - see get_profile
        logger.error("loading profile history failed for %s: %s", user_id, exc)
        raise _unavailable() from exc
    tables = _tables()
    return [
        HistoryEntryOut(
            **_entry_out(e, tables).model_dump(),
            retired_at=e.retired_at,
            retired_by=e.retired_by,
            retired_reason=e.retired_reason,
            replaces_id=e.replaces_id,
        )
        for e in entries
    ]


@router.get("/limits/today")
async def get_limits_today(
    user_id: str = Depends(get_current_user_id),
) -> LimitsToday:
    """Today's progress against the confirmed nutrient limits."""
    try:
        return await limits_today(user_id)
    except Exception as exc:  # noqa: BLE001 - see get_profile
        logger.error("limits for today failed for %s: %s", user_id, exc)
        raise _unavailable() from exc


@router.post("/entries", status_code=201)
async def create_entry(
    req: EntryIn, user_id: str = Depends(get_current_user_id)
) -> EntryOut:
    """Add (or, with ``replaces_id``, edit) an entry the patient typed in the app.

    Entering it is the confirmation: it is created confirmed with source
    ``patient``. Any other source is refused.
    """
    if req.source != "patient":
        raise HTTPException(
            status_code=403, detail="Only patient entries can be created here"
        )
    try:
        value = profile.parse_value(req.type, req.value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if req.replaces_id is not None:
        return await _act(
            profile.replace(
                user_id,
                req.replaces_id,
                value,
                label=req.label,
                client_request_id=req.client_request_id,
            )
        )
    return await _act(
        profile.add_entry(
            user_id,
            value,
            source="patient",
            state="confirmed",
            created_by="patient",
            label=req.label,
            client_request_id=req.client_request_id,
        )
    )


@router.post("/entries/{entry_id}/confirm")
async def confirm_entry(
    entry_id: str, user_id: str = Depends(get_current_user_id)
) -> EntryOut:
    """Confirm a pending entry (or acknowledge an inferred one)."""
    return await _act(profile.confirm(user_id, entry_id))


@router.post("/entries/{entry_id}/deny")
async def deny_entry(
    entry_id: str, user_id: str = Depends(get_current_user_id)
) -> EntryOut:
    """Reject a pending entry; it never binds."""
    return await _act(profile.deny(user_id, entry_id))


@router.post("/entries/{entry_id}/retire")
async def retire_entry(
    entry_id: str, req: RetireIn, user_id: str = Depends(get_current_user_id)
) -> EntryOut:
    """Retire a confirmed entry. ``confirm: true`` is required."""
    return await _act(profile.retire(user_id, entry_id, reason="retired_by_patient"))


@router.post("/meals/{recommendation_id}/feedback")
async def meal_feedback(
    recommendation_id: str,
    req: MealFeedbackIn,
    user_id: str = Depends(get_current_user_id),
) -> MealFeedbackOut:
    """Record whether the patient accepted or rejected a recipe they were shown.

    Repeating the same status returns 200 and changes nothing. A reason is kept
    only with ``rejected``.
    """
    try:
        uuid.UUID(recommendation_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Recommendation not found") from exc
    async with get_session()() as session, session.begin():
        row = await session.get(Recommendation, recommendation_id, with_for_update=True)
        if row is None or row.user_id != user_id:
            raise HTTPException(status_code=404, detail="Recommendation not found")
        if row.status != req.status:
            row.status = req.status
            row.rejection_reason = req.reason if req.status == "rejected" else None
            row.status_at = datetime.now(UTC)
    return MealFeedbackOut(recommendation_id=recommendation_id, status=req.status)
