from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.sql import func

from backend.auth.supabase import get_current_user_id
from backend.db.models import DeviceToken
from backend.db.session import get_session

router = APIRouter(prefix="/devices", tags=["devices"])


class RegisterDeviceRequest(BaseModel):
    token: str = Field(min_length=1)
    platform: Literal["fcm"]

    model_config = ConfigDict(extra="forbid")


class RegisterDeviceResponse(BaseModel):
    status: str

    model_config = ConfigDict(extra="forbid")


@router.post("/register", status_code=201, response_model=RegisterDeviceResponse)
async def register_device(
    req: RegisterDeviceRequest, user_id: str = Depends(get_current_user_id)
) -> RegisterDeviceResponse:
    """Upsert an FCM token; re-registration rebinds it to the current user.

    A device token is unique across users: if the same physical device logs
    in as a different account, re-registering moves the token to the new
    user rather than creating a duplicate row.

    Args:
        req: The FCM token and platform reported by the client.
        user_id: Supabase Auth UUID resolved from the bearer token.

    Returns:
        RegisterDeviceResponse with status "registered".
    """
    session_factory = get_session()
    async with session_factory() as session:
        stmt = (
            pg_insert(DeviceToken)
            .values(user_id=user_id, platform=req.platform, token=req.token)
            .on_conflict_do_update(
                index_elements=[DeviceToken.token],
                set_={"user_id": user_id, "last_seen_at": func.now()},
            )
        )
        await session.execute(stmt)
        await session.commit()
    return RegisterDeviceResponse(status="registered")


@router.delete("/{token}", status_code=204)
async def delete_device(
    token: str, user_id: str = Depends(get_current_user_id)
) -> Response:
    """Remove a device token for the authenticated user (e.g. on logout).

    Args:
        token: The FCM token to remove.
        user_id: Supabase Auth UUID resolved from the bearer token.

    Returns:
        An empty 204 response.
    """
    session_factory = get_session()
    async with session_factory() as session:
        await session.execute(
            delete(DeviceToken).where(
                DeviceToken.token == token, DeviceToken.user_id == user_id
            )
        )
        await session.commit()
    return Response(status_code=204)
