from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Request
from pydantic import BaseModel

from backend.agent.orchestrator import handle_message

router = APIRouter(prefix="/meals", tags=["meals"])

class LogMealRequest(BaseModel):
    user_input: str
    conversation_id: Optional[str] = None

@router.post("/log")
async def log_meal(req: LogMealRequest, request: Request) -> dict:
    # Phase 1: Simple dummy mapping until auth integration
    user_id = "default_user_123" 
    
    # Setup conversation_id fallback from user plan
    thread_id = req.conversation_id or user_id
    
    checkpointer = request.app.state.checkpointer
    
    response = await handle_message(
        user_id=user_id, 
        user_input=req.user_input, 
        thread_id=thread_id, 
        checkpointer=checkpointer
    )
    
    return response
