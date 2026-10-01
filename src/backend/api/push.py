from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from backend.auth.supabase import get_current_user_id
from backend.db.models import PushSubscription
from backend.db.session import get_session

# TODO: no push sender exists yet (deferred per the onboarding rewrite). These
# endpoints only store PushSubscription rows; they are retained for that sender.
router = APIRouter(prefix="/push", tags=["push"])


class VapidKeyResponse(BaseModel):
    public_key: str

    model_config = ConfigDict(extra="forbid")


class SubscriptionKeys(BaseModel):
    p256dh: str = Field(min_length=1)
    auth: str = Field(min_length=1)

    model_config = ConfigDict(extra="forbid")


class SubscribeRequest(BaseModel):
    """Mirror of the browser PushSubscription.toJSON() shape."""

    endpoint: str = Field(min_length=1)
    keys: SubscriptionKeys

    model_config = ConfigDict(extra="forbid")


class SubscribeResponse(BaseModel):
    status: str

    model_config = ConfigDict(extra="forbid")


@router.get("/vapid-public-key", response_model=VapidKeyResponse)
async def get_vapid_public_key() -> VapidKeyResponse:
    """Return the server's VAPID public key for the browser to subscribe with.

    Returns:
        VapidKeyResponse with the base64url-encoded public key.

    Raises:
        HTTPException: 404 when web push is not configured (no VAPID key set),
            so the frontend can gracefully skip the reminder feature.
    """
    public_key = os.environ.get("VAPID_PUBLIC_KEY", "").strip()
    if not public_key:
        raise HTTPException(status_code=404, detail="Web push is not configured")
    return VapidKeyResponse(public_key=public_key)


@router.post("/subscribe", status_code=201, response_model=SubscribeResponse)
async def subscribe(
    req: SubscribeRequest, user_id: str = Depends(get_current_user_id)
) -> SubscribeResponse:
    """Store (or update) a Web Push subscription for the authenticated user.

    Upserts on endpoint: re-subscribing the same browser refreshes the keys and
    re-points the subscription at the current user rather than duplicating it.

    Args:
        req: The browser subscription (endpoint + p256dh/auth keys).
        user_id: Supabase Auth UUID resolved from the bearer token.

    Returns:
        SubscribeResponse with status "ok".
    """
    session_factory = get_session()
    async with session_factory() as session:
        existing = await session.scalar(
            select(PushSubscription).where(
                PushSubscription.endpoint == req.endpoint
            )
        )
        if existing is not None:
            existing.user_id = user_id
            existing.p256dh = req.keys.p256dh
            existing.auth = req.keys.auth
        else:
            session.add(
                PushSubscription(
                    user_id=user_id,
                    endpoint=req.endpoint,
                    p256dh=req.keys.p256dh,
                    auth=req.keys.auth,
                )
            )
        await session.commit()
    return SubscribeResponse(status="ok")
