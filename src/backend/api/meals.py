from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from backend.agent.orchestrator import handle_message
from backend.auth.supabase import get_current_user_id

router = APIRouter(prefix="/meals", tags=["meals"])


class LogMealRequest(BaseModel):
    user_input: str
    conversation_id: str | None = None
    image_b64: str | None = None


@router.post("/log")
async def log_meal(
    req: LogMealRequest,
    request: Request,
    user_id: str = Depends(get_current_user_id),
) -> dict:
    thread_id = req.conversation_id or user_id
    checkpointer = request.app.state.checkpointer

    return await handle_message(
        user_id=user_id,
        user_input=req.user_input,
        thread_id=thread_id,
        checkpointer=checkpointer,
        image_b64=req.image_b64,
    )
