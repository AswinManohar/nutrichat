from __future__ import annotations

from typing import Any
from langgraph.graph import StateGraph, MessagesState
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

def build_graph(checkpointer: AsyncPostgresSaver | None = None) -> Any:
    workflow = StateGraph(MessagesState)
    
    async def dummy_node(state: MessagesState) -> dict[str, Any]:
        # Minimal skeleton setup that just returns immediately
        return {"messages": []}

    workflow.add_node("agent", dummy_node)
    workflow.set_entry_point("agent")
    
    return workflow.compile(checkpointer=checkpointer)
