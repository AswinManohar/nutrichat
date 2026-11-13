"""The dietitian review queue (spec 013, US6; contracts/review-api.md).

Backend only: there is no screen. Every route needs ``require_reviewer`` and
every decision is recorded as ``reviewer:<user id>``. This router is the only
writer of ``source='clinician'`` profile entries (FR-031).

Single source of truth: pending profile entries and red-flag escalations are
not copied into ``review_item``. They are listed straight from their own
tables, and a ``review_item`` row is created only when a reviewer decides
(its ``subject_id`` then points back at the entry or escalation). Conflicts,
plan samples and unknown medications are queued by ``agent/suggest.py``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.reviewer import require_reviewer
from backend.db.models import (
    ProfileEntry,
    Recommendation,
    RedFlagEscalation,
    ReviewItem,
)
from backend.db.session import get_session
from backend.safety import profile
from backend.safety.profile import (
    _ensure_room,
    _get_row,
    _lock,
    _new_row,
    _retire_row,
)
from backend.safety.tables import ClinicalTables, TablesUnavailable, load_tables

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/review", tags=["review"], dependencies=[Depends(require_reviewer)]
)

Kind = Literal[
    "pending_entry", "rule_conflict", "escalation", "plan_sample", "unknown_medication"
]
Decision = Literal["approved", "rejected", "edited", "handled"]

# Kinds listed from their own table until a decision creates the review_item.
_DERIVED_KINDS = ("pending_entry", "escalation")

# The decision table of the contract: which decisions each kind accepts.
_ALLOWED: dict[str, frozenset[str]] = {
    "pending_entry": frozenset({"approved", "rejected", "edited"}),
    "rule_conflict": frozenset({"edited"}),
    "escalation": frozenset({"handled"}),
    "plan_sample": frozenset({"approved", "rejected"}),
    "unknown_medication": frozenset({"handled"}),
}


class EditIn(BaseModel):
    """The clinician's replacement value."""

    type: profile.EntryType
    value: dict
    label: str | None = Field(default=None, max_length=200)

    model_config = ConfigDict(extra="forbid")


class DecisionIn(BaseModel):
    """Body of POST /admin/review/items/{id}/decision."""

    decision: Decision
    edit: EditIn | None = None
    comment: str | None = Field(default=None, max_length=2000)

    model_config = ConfigDict(extra="forbid")


class ItemOut(BaseModel):
    """One queue item. Patients appear by id only (FR-040c)."""

    id: str
    kind: Kind
    patient_id: str
    created_at: datetime
    content: dict
    decision: Decision | None = None
    decided_at: datetime | None = None
    comment: str | None = None

    model_config = ConfigDict(extra="forbid")


class ItemsOut(BaseModel):
    """Response of GET /admin/review/items."""

    items: list[ItemOut]
    next_before: datetime | None

    model_config = ConfigDict(extra="forbid")


class EscalationOut(BaseModel):
    """A red-flag escalation with the patient's message (reviewer-only read)."""

    id: str
    patient_id: str
    message: str
    rule_id: str
    rule_label: str
    rules_version: str
    notify_status: str
    notify_attempts: int
    notified_at: datetime | None
    created_at: datetime
    decision: Decision | None
    decided_at: datetime | None
    comment: str | None

    model_config = ConfigDict(extra="forbid")


class EntryOut(BaseModel):
    """A profile entry written by a decision or by the reviewer."""

    id: str
    patient_id: str
    type: profile.EntryType
    label: str
    value: dict
    source: profile.EntrySource
    state: profile.EntryState
    created_by: str

    model_config = ConfigDict(extra="forbid")


class DecisionOut(BaseModel):
    """The stored decision and the entry it produced, if any."""

    id: str
    kind: Kind
    decision: Decision
    decided_by: str
    decided_at: datetime
    entry: EntryOut | None

    model_config = ConfigDict(extra="forbid")


class ClinicianEntryIn(BaseModel):
    """Body of POST /admin/review/patients/{patient_id}/entries."""

    type: profile.EntryType
    value: dict
    label: str | None = Field(default=None, max_length=200)
    client_request_id: str | None = Field(default=None, min_length=1, max_length=64)

    model_config = ConfigDict(extra="forbid")


def _actor(reviewer_id: str) -> str:
    return f"reviewer:{reviewer_id}"


def _uuid_or_404(value: str, what: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=f"{what} not found") from exc


def _tables() -> ClinicalTables:
    try:
        return load_tables()
    except TablesUnavailable as exc:
        logger.error("clinical tables unavailable: %s", exc)
        raise HTTPException(
            status_code=503, detail="Clinical tables unavailable"
        ) from exc


def _parse(edit: EditIn) -> profile.EntryValue:
    try:
        return profile.parse_value(edit.type, edit.value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _entry_out(row: ProfileEntry, tables: ClinicalTables) -> EntryOut:
    entry = profile._to_entry(row)  # noqa: SLF001 - same package, one row mapper
    return EntryOut(
        id=entry.id,
        patient_id=row.user_id,
        type=entry.type,
        label=profile.label_for(entry, tables),
        value=entry.value.model_dump(exclude_none=True),
        source=entry.source,
        state=entry.state,
        created_by=entry.created_by,
    )


def _plan_content(rec: Recommendation) -> dict:
    snapshot = rec.check_snapshot
    return {
        "recipe_name": rec.recipe.get("name"),
        "patient_status": rec.status,
        "check": {
            "passed": snapshot.get("passed"),
            "attempt": snapshot.get("attempt"),
            "applied": [a.get("phrase") for a in snapshot.get("applied", [])],
            "conflicts": len(snapshot.get("conflicts", [])),
            "missing_values": snapshot.get("missing_values", []),
        },
    }


async def _subjects(
    session: AsyncSession, items: list[ReviewItem | ProfileEntry | RedFlagEscalation]
) -> tuple[
    dict[str, ProfileEntry], dict[str, RedFlagEscalation], dict[str, Recommendation]
]:
    """Load the rows the listed items point at, one query per kind."""
    ids: dict[str, set[str]] = {"entry": set(), "escalation": set(), "plan": set()}
    for item in items:
        if isinstance(item, ProfileEntry):
            ids["entry"].add(item.id)
        elif isinstance(item, RedFlagEscalation):
            ids["escalation"].add(item.id)
        elif item.kind == "pending_entry":
            ids["entry"].add(item.subject_id)
        elif item.kind == "escalation":
            ids["escalation"].add(item.subject_id)
        elif item.kind == "plan_sample":
            ids["plan"].add(item.subject_id)

    async def fetch(model, wanted: set[str]) -> dict:
        if not wanted:
            return {}
        rows = await session.execute(select(model).where(model.id.in_(wanted)))
        return {row.id: row for row in rows.scalars()}

    return (
        await fetch(ProfileEntry, ids["entry"]),
        await fetch(RedFlagEscalation, ids["escalation"]),
        await fetch(Recommendation, ids["plan"]),
    )


def _escalation_content(esc: RedFlagEscalation) -> dict:
    # No message text in the list: it is read on the detail route only.
    return {
        "rule_id": esc.rule_id,
        "rule_label": esc.rule_label,
        "occurred_at": esc.created_at.isoformat(),
        "notify_status": esc.notify_status,
    }


def _entry_content(row: ProfileEntry, tables: ClinicalTables) -> dict:
    return {
        "type": row.entry_type,
        "label": profile.label_for(profile._to_entry(row), tables),  # noqa: SLF001
        "evidence": row.evidence,
    }


@router.get("/items")
async def list_items(
    kind: Kind | None = None,
    open: bool = True,  # noqa: A002 - query parameter named by the contract
    limit: int = Query(default=50, ge=1, le=100),
    before: datetime | None = None,
) -> ItemsOut:
    """Queue items, newest first.

    ``open=true`` lists items without a decision (pending entries and
    escalations are derived from their tables); ``open=false`` lists decided
    items. ``before`` is the previous page's ``next_before``.
    """
    tables = _tables()
    async with get_session()() as session:
        stored = select(ReviewItem)
        if open:
            stored = stored.where(
                ReviewItem.decision.is_(None),
                ReviewItem.kind.not_in(_DERIVED_KINDS),
            )
        else:
            stored = stored.where(ReviewItem.decision.is_not(None))
        if kind:
            stored = stored.where(ReviewItem.kind == kind)
        if before:
            stored = stored.where(ReviewItem.created_at < before)
        candidates: list[ReviewItem | ProfileEntry | RedFlagEscalation] = list(
            (
                await session.execute(
                    stored.order_by(ReviewItem.created_at.desc()).limit(limit + 1)
                )
            ).scalars()
        )
        if open and kind in (None, "pending_entry"):
            q = select(ProfileEntry).where(
                ProfileEntry.state == "pending",
                ~exists().where(
                    ReviewItem.kind == "pending_entry",
                    ReviewItem.subject_id == ProfileEntry.id,
                ),
            )
            if before:
                q = q.where(ProfileEntry.created_at < before)
            candidates += (
                await session.execute(
                    q.order_by(ProfileEntry.created_at.desc()).limit(limit + 1)
                )
            ).scalars()
        if open and kind in (None, "escalation"):
            q = select(RedFlagEscalation).where(
                ~exists().where(
                    ReviewItem.kind == "escalation",
                    ReviewItem.subject_id == RedFlagEscalation.id,
                )
            )
            if before:
                q = q.where(RedFlagEscalation.created_at < before)
            candidates += (
                await session.execute(
                    q.order_by(RedFlagEscalation.created_at.desc()).limit(limit + 1)
                )
            ).scalars()
        candidates.sort(key=lambda c: c.created_at, reverse=True)
        page = candidates[:limit]
        entries, escalations, plans = await _subjects(session, page)

    out: list[ItemOut] = []
    for c in page:
        if isinstance(c, ProfileEntry):
            out.append(
                ItemOut(
                    id=c.id,
                    kind="pending_entry",
                    patient_id=c.user_id,
                    created_at=c.created_at,
                    content=_entry_content(c, tables),
                )
            )
            continue
        if isinstance(c, RedFlagEscalation):
            out.append(
                ItemOut(
                    id=c.id,
                    kind="escalation",
                    patient_id=c.user_id,
                    created_at=c.created_at,
                    content=_escalation_content(c),
                )
            )
            continue
        content: dict | None
        item_id = c.id
        if c.kind == "pending_entry":
            item_id = c.subject_id
            row = entries.get(c.subject_id)
            content = _entry_content(row, tables) if row else None
        elif c.kind == "escalation":
            item_id = c.subject_id
            esc = escalations.get(c.subject_id)
            content = _escalation_content(esc) if esc else None
        elif c.kind == "plan_sample":
            rec = plans.get(c.subject_id)
            content = _plan_content(rec) if rec else None
        else:
            content = c.detail or {}
        if content is None:
            logger.warning("review item %s has no subject %s", c.id, c.subject_id)
            continue
        out.append(
            ItemOut(
                id=item_id,
                kind=c.kind,
                patient_id=c.user_id,
                created_at=c.created_at,
                content=content,
                decision=c.decision,
                decided_at=c.decided_at,
                comment=c.comment,
            )
        )
    more = len(candidates) > limit
    return ItemsOut(
        items=out, next_before=page[-1].created_at if more and page else None
    )


@router.get("/escalations/{escalation_id}")
async def get_escalation(escalation_id: str) -> EscalationOut:
    """One escalation with the patient's message (the webhook links here)."""
    escalation_id = _uuid_or_404(escalation_id, "Escalation")
    async with get_session()() as session:
        esc = await session.get(RedFlagEscalation, escalation_id)
        if esc is None:
            raise HTTPException(status_code=404, detail="Escalation not found")
        item = (
            await session.execute(
                select(ReviewItem).where(
                    ReviewItem.kind == "escalation",
                    ReviewItem.subject_id == escalation_id,
                )
            )
        ).scalar_one_or_none()
    return EscalationOut(
        id=esc.id,
        patient_id=esc.user_id,
        message=esc.message,
        rule_id=esc.rule_id,
        rule_label=esc.rule_label,
        rules_version=esc.rules_version,
        notify_status=esc.notify_status,
        notify_attempts=esc.notify_attempts,
        notified_at=esc.notified_at,
        created_at=esc.created_at,
        decision=item.decision if item else None,
        decided_at=item.decided_at if item else None,
        comment=item.comment if item else None,
    )


async def _resolve_item(session: AsyncSession, item_id: str) -> ReviewItem:
    """Lock the item, creating it for a pending entry or escalation.

    ``item_id`` is a review_item id, or the subject id of a derived item.

    Raises:
        HTTPException: 404 when nothing matches, 409 when already decided.
    """
    item = (
        await session.execute(
            select(ReviewItem)
            .where(
                (ReviewItem.id == item_id)
                | (
                    (ReviewItem.subject_id == item_id)
                    & ReviewItem.kind.in_(_DERIVED_KINDS)
                )
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if item is not None:
        if item.decision is not None:
            raise HTTPException(status_code=409, detail="Already decided")
        return item
    entry = (
        await session.execute(
            select(ProfileEntry).where(ProfileEntry.id == item_id).with_for_update()
        )
    ).scalar_one_or_none()
    if entry is not None:
        if entry.state != "pending":
            raise HTTPException(status_code=409, detail="Entry is no longer pending")
        item = ReviewItem(
            user_id=entry.user_id, kind="pending_entry", subject_id=item_id
        )
    else:
        esc = await session.get(RedFlagEscalation, item_id)
        if esc is None:
            raise HTTPException(status_code=404, detail="Review item not found")
        item = ReviewItem(user_id=esc.user_id, kind="escalation", subject_id=item_id)
    session.add(item)
    await session.flush()
    return item


def _validate(item: ReviewItem, body: DecisionIn) -> None:
    """The decision table's 422 cells and the body rules that go with them."""
    if body.decision not in _ALLOWED[item.kind]:
        raise HTTPException(
            status_code=422,
            detail=f"A {item.kind} item cannot be {body.decision}",
        )
    if (body.decision == "edited") != (body.edit is not None):
        raise HTTPException(
            status_code=422, detail="edit is required for, and only for, 'edited'"
        )
    if (
        item.kind == "rule_conflict"
        and body.edit
        and body.edit.type != "nutrient_limit"
    ):
        raise HTTPException(
            status_code=422, detail="A conflict is resolved by a nutrient_limit"
        )
    if item.kind == "plan_sample" and body.decision == "rejected":
        if not (body.comment and body.comment.strip()):
            raise HTTPException(
                status_code=422, detail="A rejected plan sample needs a comment"
            )


async def _replace_with_clinician_entry(
    session: AsyncSession,
    user_id: str,
    retiring: list[ProfileEntry],
    replaces_id: str,
    edit: EditIn,
    actor: str,
) -> ProfileEntry:
    """Retire entries and insert the confirmed clinician entry, in the open txn."""
    value = _parse(edit)
    for row in retiring:
        _retire_row(row, actor, "replaced")
    await session.flush()
    await _ensure_room(session, user_id)
    new = _new_row(
        user_id,
        value,
        label=edit.label,
        source="clinician",
        state="confirmed",
        created_by=actor,
        client_request_id=None,
        replaces_id=replaces_id,
    )
    session.add(new)
    await session.flush()
    return new


async def _apply(
    session: AsyncSession, item: ReviewItem, body: DecisionIn, actor: str
) -> ProfileEntry | None:
    """Carry out the decision's effect on the subject; return the entry it made."""
    if item.kind == "pending_entry":
        await _lock(session, item.user_id)
        row = await _get_row(session, item.user_id, item.subject_id)
        if row.state != "pending":
            raise HTTPException(status_code=409, detail="Entry is no longer pending")
        if body.decision == "approved":
            row.state = "confirmed"
            row.confirmed_at = datetime.now(UTC)
            row.confirmed_by = actor
            return row
        if body.decision == "rejected":
            _retire_row(row, actor, "denied")
            return None
        assert body.edit is not None
        return await _replace_with_clinician_entry(
            session, item.user_id, [row], row.id, body.edit, actor
        )
    if item.kind == "rule_conflict":
        assert body.edit is not None
        await _lock(session, item.user_id)
        ids = (item.detail or {}).get("entries", [])
        rows = (
            await session.execute(
                select(ProfileEntry)
                .where(
                    ProfileEntry.user_id == item.user_id,
                    ProfileEntry.id.in_(ids),
                    ProfileEntry.state == "confirmed",
                )
                .with_for_update()
            )
        ).scalars()
        return await _replace_with_clinician_entry(
            session, item.user_id, list(rows), item.subject_id, body.edit, actor
        )
    return None


@router.post("/items/{item_id}/decision")
async def decide(
    item_id: str, body: DecisionIn, reviewer_id: str = Depends(require_reviewer)
) -> DecisionOut:
    """Record a decision and apply its effect in one transaction.

    422 for a combination the decision table does not allow, 409 when the
    item was already decided (or its entry is no longer pending), 404 when
    the id matches nothing.
    """
    item_id = _uuid_or_404(item_id, "Review item")
    actor = _actor(reviewer_id)
    tables = _tables()
    try:
        async with get_session()() as session, session.begin():
            item = await _resolve_item(session, item_id)
            _validate(item, body)
            try:
                entry = await _apply(session, item, body, actor)
            except profile.StateConflict as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except profile.EntryNotFound as exc:
                raise HTTPException(status_code=404, detail="Entry not found") from exc
            except profile.ProfileFull as exc:
                raise HTTPException(
                    status_code=409, detail="The patient's profile is full"
                ) from exc
            item.decision = body.decision
            item.decided_by = actor
            item.decided_at = datetime.now(UTC)
            item.comment = body.comment
            await session.flush()
            logger.info("review %s %s by %s", item.kind, body.decision, actor)
            return DecisionOut(
                id=item.subject_id if item.kind in _DERIVED_KINDS else item.id,
                kind=item.kind,
                decision=body.decision,
                decided_by=actor,
                decided_at=item.decided_at,
                entry=_entry_out(entry, tables) if entry else None,
            )
    except IntegrityError as exc:
        # A concurrent reviewer created the same derived item first.
        raise HTTPException(status_code=409, detail="Already decided") from exc


@router.post("/patients/{patient_id}/entries", status_code=201)
async def add_clinician_entry(
    patient_id: str,
    body: ClinicianEntryIn,
    reviewer_id: str = Depends(require_reviewer),
) -> EntryOut:
    """A confirmed, clinician-sourced hard entry (e.g. a sodium limit).

    Raises:
        HTTPException: 404 for an unknown patient, 409 when the patient's
            profile is full, 422 for an invalid value.
    """
    patient_id = _uuid_or_404(patient_id, "Patient")
    try:
        value = profile.parse_value(body.type, body.value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        entry = await profile.add_entry(
            patient_id,
            value,
            source="clinician",
            state="confirmed",
            created_by=_actor(reviewer_id),
            label=body.label,
            client_request_id=body.client_request_id,
        )
    except profile.ProfileFull as exc:
        raise HTTPException(
            status_code=409, detail="The patient's profile is full"
        ) from exc
    except IntegrityError as exc:
        raise HTTPException(status_code=404, detail="Patient not found") from exc
    logger.info("clinician entry %s added by %s", entry.id, _actor(reviewer_id))
    return EntryOut(
        id=entry.id,
        patient_id=patient_id,
        type=entry.type,
        label=profile.label_for(entry, _tables()),
        value=entry.value.model_dump(exclude_none=True),
        source=entry.source,
        state=entry.state,
        created_by=entry.created_by,
    )
