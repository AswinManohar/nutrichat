from __future__ import annotations

from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage

from backend.agent.graph import build_graph


async def handle_message(
    user_id: str,
    user_input: str,
    thread_id: str,
    checkpointer: Any,
    image_b64: Optional[str] = None,
) -> dict[str, Any]:
    """Route a user message through the meal logging graph.

    Checks existing checkpoint to determine whether this is a fresh
    conversation or a resume after the confirmation-card interrupt.

    Args:
        user_id: Supabase Auth UUID.
        user_input: Raw text from the user.
        thread_id: LangGraph thread ID (defaults to user_id in Phase 1).
        checkpointer: AsyncPostgresSaver instance from app.state.
        image_b64: Optional base64-encoded image string.

    Returns:
        Dict with status, message (last AI response), and paused flag.
    """
    graph = build_graph(checkpointer)
    config = {"configurable": {"thread_id": thread_id, "user_id": user_id}}

    # Check if graph is paused at the confirmation interrupt
    current_state = await graph.aget_state(config)
    is_paused = bool(current_state.next)

    if is_paused:
        # Resume: inject new message into checkpoint state, then resume with None
        await graph.aupdate_state(
            config,
            {"messages": [HumanMessage(content=user_input)]},
        )
        result = await graph.ainvoke(None, config=config)
    else:
        # Fresh start: supply full initial state
        result = await graph.ainvoke(
            {
                "messages": [HumanMessage(content=user_input)],
                "user_id": user_id,
                "image_b64": image_b64 or "",
                "entities": [],
                "usda_results": [],
                "meal_type": None,
            },
            config=config,
        )

    # Check if graph paused again (e.g. after correction loop re-presents card)
    new_state = await graph.aget_state(config)
    still_paused = bool(new_state.next)

    last_ai = next(
        (m for m in reversed(result["messages"]) if isinstance(m, AIMessage)), None
    )
    return {
        "status": "success",
        "message": last_ai.content if last_ai else "",
        "paused": still_paused,
    }
