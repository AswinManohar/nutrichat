"""The patient's safety profile: hard entries, history and today's limits.

Contract: specs/013-patient-safety-profile/contracts/profile-api.md. Every
body is a Pydantic model with ``extra="forbid"``. Repeating an action that
was already applied returns the entry; a state the action cannot reach is a 409.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import Literal, get_args

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from backend.agent import meal_history
from backend.agent.memory.facts import (
    MAX_FACT_CHARS,
    FactKind,
    MemoryFact,
    RemoveFact,
    ReplaceFact,
    apply_ops,
    load_state,
    normalize_fact,
)
from backend.auth.supabase import get_current_user_id
from backend.config import get_tunables
from backend.db.models import Recommendation, RedFlagEscalation
from backend.db.session import get_session
from backend.ratelimit import user_rate_limiter
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
    # An inferred entry the patient has agreed with in the app; the app stops
    # showing the "Inferred" prompt for it.
    acknowledged: bool

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


class SoftFactPatch(BaseModel):
    """Body of PATCH /profile/soft/{id}: the fields to change."""

    text: str | None = Field(default=None, min_length=1, max_length=MAX_FACT_CHARS)
    kind: FactKind | None = None

    model_config = ConfigDict(extra="forbid")


class MealsOut(BaseModel):
    """Response of GET /profile/meals."""

    days: int
    recommendations: list[meal_history.SuggestedMeal]
    eaten: list[meal_history.EatenMeal]

    model_config = ConfigDict(extra="forbid")


class ExportedRecommendation(BaseModel):
    """A recipe that was shown, as exported."""

    id: str
    created_at: datetime
    recipe: dict
    status: str
    rejection_reason: str | None
    status_at: datetime

    model_config = ConfigDict(extra="forbid")


class ExportedEscalation(BaseModel):
    """A message that matched a red-flag rule; the message is the patient's own."""

    id: str
    created_at: datetime
    rule_label: str
    notify_status: str
    message: str

    model_config = ConfigDict(extra="forbid")


class ExportOut(BaseModel):
    """Everything remembered about the patient (FR-040b)."""

    exported_at: datetime
    hard: list[HistoryEntryOut]
    soft: list[SoftFactOut]
    recommendations: list[ExportedRecommendation]
    escalations: list[ExportedEscalation]

    model_config = ConfigDict(extra="forbid")


def _soft_out(fact: MemoryFact) -> SoftFactOut:
    return SoftFactOut(
        id=fact.id,
        kind=fact.kind,
        text=fact.fact,
        source=fact.source,
        created_at=fact.created_at,
        updated_at=fact.updated_at,
    )


def _history_out(entry: profile.HardEntry, tables: ClinicalTables) -> HistoryEntryOut:
    return HistoryEntryOut(
        **_entry_out(entry, tables).model_dump(),
        retired_at=entry.retired_at,
        retired_by=entry.retired_by,
        retired_reason=entry.retired_reason,
        replaces_id=entry.replaces_id,
    )


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
        acknowledged=entry.acknowledged_at is not None,
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
        soft=[_soft_out(f) for f in state.facts],
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
    return [_history_out(e, tables) for e in entries]


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


def _fact_id(fact_id: str) -> str:
    try:
        return str(uuid.UUID(fact_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Preference not found") from exc


@router.patch("/soft/{fact_id}")
async def edit_soft_fact(
    fact_id: str, req: SoftFactPatch, user_id: str = Depends(get_current_user_id)
) -> SoftFactOut:
    """Change a preference's text or kind; the patient's edit counts as stated.

    If the new text equals another live preference the two merge and that one
    is returned. 404 for an unknown id (or another patient's).
    """
    fact_id = _fact_id(fact_id)
    if req.text is None and req.kind is None:
        raise HTTPException(status_code=422, detail="Give a text or a kind")
    facts = (await load_state(user_id)).facts
    current = next((f for f in facts if f.id == fact_id), None)
    if current is None:
        raise HTTPException(status_code=404, detail="Preference not found")
    text = req.text if req.text is not None else current.fact
    if req.kind is not None:
        kind = req.kind
    elif current.kind in get_args(FactKind):
        kind = current.kind
    else:
        raise HTTPException(status_code=422, detail="Choose a kind for this older note")
    outcome = await apply_ops(
        user_id, [ReplaceFact(id=fact_id, fact=text, kind=kind)], "user"
    )
    if outcome.n_applied == 0:
        raise HTTPException(status_code=404, detail="Preference not found")
    key = normalize_fact(text)
    saved = next(
        (f for f in (await load_state(user_id)).facts if normalize_fact(f.fact) == key),
        None,
    )
    if saved is None:
        raise HTTPException(status_code=404, detail="Preference not found")
    return _soft_out(saved)


@router.delete("/soft/{fact_id}", status_code=204)
async def delete_soft_fact(
    fact_id: str, user_id: str = Depends(get_current_user_id)
) -> Response:
    """Delete a preference. It is not learned again unless the patient restates it.

    Idempotent: 204 whether the preference was live, already deleted or never
    existed, so ids cannot be probed.
    """
    await apply_ops(user_id, [RemoveFact(id=_fact_id(fact_id))], "user")
    return Response(status_code=204)


@router.get("/meals")
async def get_meals(
    days: int = Query(default=21, ge=1, le=90),
    user_id: str = Depends(get_current_user_id),
) -> MealsOut:
    """Recipes shown (with accepted or rejected status and reason) and the
    labelled meals logged in the last ``days`` days, newest first."""
    limit = get_tunables().memory.history_api_max_rows
    try:
        suggested, eaten = await asyncio.gather(
            meal_history.load_suggested(user_id, days, limit),
            meal_history.load_eaten(user_id, days, limit),
        )
    except Exception as exc:  # noqa: BLE001 - any failure must not look like "empty"
        logger.error("loading meal history failed for %s: %s", user_id, exc)
        raise _unavailable() from exc
    return MealsOut(days=days, recommendations=suggested, eaten=eaten)


@router.get(
    "/export",
    dependencies=[Depends(user_rate_limiter("profile_export", limit=10, window_s=60))],
)
async def export_profile(user_id: str = Depends(get_current_user_id)) -> Response:
    """Everything remembered about the patient as one JSON file (FR-040b).

    Hard entries with their history, live preferences (deleted ones are not
    kept in the file), recipes shown, and red-flag matches with the message.
    """
    try:
        history = await profile.load_history(user_id)
        state = await load_state(user_id)
        async with get_session()() as session:
            recs = (
                (
                    await session.execute(
                        select(Recommendation)
                        .where(Recommendation.user_id == user_id)
                        .order_by(Recommendation.created_at.desc())
                    )
                )
                .scalars()
                .all()
            )
            escalations = (
                (
                    await session.execute(
                        select(RedFlagEscalation)
                        .where(RedFlagEscalation.user_id == user_id)
                        .order_by(RedFlagEscalation.created_at.desc())
                    )
                )
                .scalars()
                .all()
            )
    except Exception as exc:  # noqa: BLE001 - never hand out a partial export
        logger.error("profile export failed for %s: %s", user_id, exc)
        raise _unavailable() from exc
    tables = _tables()
    body = ExportOut(
        exported_at=datetime.now(UTC),
        hard=[_history_out(e, tables) for e in history],
        soft=[_soft_out(f) for f in state.facts],
        recommendations=[
            ExportedRecommendation(
                id=r.id,
                created_at=r.created_at,
                recipe=r.recipe,
                status=r.status,
                rejection_reason=r.rejection_reason,
                status_at=r.status_at,
            )
            for r in recs
        ],
        escalations=[
            ExportedEscalation(
                id=e.id,
                created_at=e.created_at,
                rule_label=e.rule_label,
                notify_status=e.notify_status,
                message=e.message,
            )
            for e in escalations
        ],
    )
    return Response(
        content=body.model_dump_json(),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="mealsy-profile.json"'},
    )
