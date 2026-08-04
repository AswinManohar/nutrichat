from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy import text as sa_text

from backend.auth.supabase import get_current_user_id
from backend.db.models import NutrientCheckup
from backend.db.session import get_session

router = APIRouter(prefix="/nutrient-checkup", tags=["nutrient-checkup"])


class NutrientCheckupItem(BaseModel):
    """One nutrient's rolling 7-day average, trend, and RDA comparison."""

    name: str
    avg: float
    prev_avg: float
    unit: str
    trend_pct: float | None
    direction: str
    # Defaults to None so rows persisted before rda_pct was added (the field is
    # simply absent from their stored JSONB) still deserialize instead of 500ing.
    rda_pct: float | None = None

    model_config = ConfigDict(extra="forbid")


class NutrientCheckupResponse(BaseModel):
    date: date
    nutrients: list[NutrientCheckupItem]
    generated_at: datetime
    notable: list[str]
    summary_text: str | None

    model_config = ConfigDict(extra="forbid")


class PendingNudgeResponse(BaseModel):
    summary_text: str | None

    model_config = ConfigDict(extra="forbid")


@router.get("")
async def get_nutrient_checkup(
    user_id: str = Depends(get_current_user_id),
) -> NutrientCheckupResponse:
    """Return the most recent Daily Nutrient Check-up for the user.

    Raises:
        HTTPException: 404 if `build_nutrient_checkup` has not run for this
            user yet (e.g. brand-new account with no meals).
    """
    session_factory = get_session()
    async with session_factory() as session:
        result = await session.execute(
            select(NutrientCheckup)
            .where(NutrientCheckup.user_id == user_id)
            .order_by(NutrientCheckup.date.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()

    if row is None:
        raise HTTPException(status_code=404, detail="No nutrient check-up yet")

    return NutrientCheckupResponse(
        date=row.date,
        generated_at=row.generated_at,
        nutrients=[
            NutrientCheckupItem(name=name, **values)
            for name, values in row.nutrients.items()
        ],
        notable=[item["name"] for item in row.notable_nutrients],
        summary_text=row.summary_text,
    )


@router.get("/pending-nudge")
async def get_pending_nudge(
    user_id: str = Depends(get_current_user_id),
) -> PendingNudgeResponse:
    """Return the most recent unseen daily summary, if any.

    Returns `{summary_text: null}` if there's no nutrient-checkup row yet,
    the most recent row has already been acknowledged
    (`chat_nudge_seen_at` is set), or it has no `summary_text`.
    """
    session_factory = get_session()
    async with session_factory() as session:
        result = await session.execute(
            select(NutrientCheckup)
            .where(NutrientCheckup.user_id == user_id)
            .order_by(NutrientCheckup.date.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()

    if row is None or row.chat_nudge_seen_at is not None:
        return PendingNudgeResponse(summary_text=None)

    return PendingNudgeResponse(summary_text=row.summary_text)


@router.post("/pending-nudge/ack", status_code=status.HTTP_204_NO_CONTENT)
async def ack_pending_nudge(
    user_id: str = Depends(get_current_user_id),
) -> Response:
    """Mark the most recent nutrient-checkup row's nudge as seen."""
    session_factory = get_session()
    async with session_factory() as session:
        await session.execute(
            sa_text(
                "UPDATE nutrient_checkup SET chat_nudge_seen_at = now() "
                "WHERE user_id = :user_id "
                "AND date = (SELECT MAX(date) FROM nutrient_checkup WHERE user_id = :user_id)"
            ),
            {"user_id": user_id},
        )
        await session.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)
