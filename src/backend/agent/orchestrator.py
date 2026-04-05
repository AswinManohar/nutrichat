from __future__ import annotations

from typing import Any
from langchain_core.messages import HumanMessage
from backend.agent.graph import build_graph

async def handle_message(user_id: str, user_input: str, thread_id: str, checkpointer: Any) -> dict[str, Any]:
    graph = build_graph(checkpointer)
    config = {"configurable": {"thread_id": thread_id, "user_id": user_id}}
    
    result = await graph.ainvoke(
        {"messages": [HumanMessage(content=user_input)]}, 
        config=config
    )
    
    return {
        "status": "success", 
        "messages": [m.content for m in result["messages"]]
    }
