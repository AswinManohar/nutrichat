from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

from backend.agent.orchestrator import handle_message

router = APIRouter(prefix="/meals", tags=["meals"])


class LogMealRequest(BaseModel):
    user_input: str
    conversation_id: Optional[str] = None
    image_b64: Optional[str] = None


@router.post("/log")
async def log_meal(req: LogMealRequest, request: Request) -> dict:
    # Phase 1: placeholder until auth integration (must be a valid UUID)
    user_id = "00000000-0000-0000-0000-000000000001"
    thread_id = req.conversation_id or user_id
    checkpointer = request.app.state.checkpointer

    return await handle_message(
        user_id=user_id,
        user_input=req.user_input,
        thread_id=thread_id,
        checkpointer=checkpointer,
        image_b64=req.image_b64,
    )
