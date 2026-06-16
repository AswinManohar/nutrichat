from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from backend.agent.tools.meals import (
    apply_correction,
    classify_food_image,
    classify_intent,
    extract_entities,
    format_confirmation_card,
    log_meal,
)
from backend.agent.tools.usda import usda_lookup_batch

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    user_id: str
    image_b64: str | None
    entities: list[dict]
    usda_results: list[dict]
    meal_type: str | None


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


async def router_node(state: AgentState) -> dict:
    """No-op — routing is handled by conditional edges."""
    return {}


async def classify_node(state: AgentState) -> dict:
    """Identify food items in the image. Routes to END if no food found."""
    image_b64 = state.get("image_b64") or ""
    result = classify_food_image(image_b64)
    if not result.is_food:
        reason = result.reason or "No food visible."
        return {
            "messages": [
                AIMessage(
                    content=(
                        f"I couldn't identify food in that image. {reason} "
                        "Try describing your meal instead."
                    )
                )
            ]
        }
    combined = ", ".join(result.food_items + result.ingredients)
    # Inject as HumanMessage so extract_node reads it as the meal description
    return {"messages": [HumanMessage(content=combined)]}


async def extract_node(state: AgentState) -> dict:
    """Parse the last human message into structured FoodEntity list."""
    last_human = next(
        (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), None
    )
    if last_human is None:
        return {"entities": []}
    try:
        result = extract_entities(last_human.content)
        # Filter out any entity the LLM returned with qty_g <= 0 (can't be logged)
        valid = [e for e in result.entities if e.qty_g > 0]
    except Exception:
        valid = []
    return {"entities": [e.model_dump() for e in valid]}


async def usda_batch_node(state: AgentState) -> dict:
    """Resolve all food entities against USDA FoodData Central (cache-first)."""
    from backend.agent.tools.meals import FoodEntity

    entities = [FoodEntity(**e) for e in state["entities"]]
    results = await usda_lookup_batch(entities)
    return {"usda_results": [r.model_dump() for r in results]}


async def present_node(state: AgentState) -> dict:
    """Format and send the confirmation card to the user."""
    from backend.agent.tools.usda import USDAResult

    if not state["usda_results"]:
        return {
            "messages": [
                AIMessage(
                    content="I didn't catch any food items in that. What did you eat?"
                )
            ]
        }
    results = [USDAResult(**r) for r in state["usda_results"]]
    card = format_confirmation_card(results)
    return {"messages": [AIMessage(content=card)]}


async def intent_router_node(state: AgentState) -> dict:
    """No-op — reads last user message; routing done in conditional edge."""
    return {}


async def apply_correction_node(state: AgentState) -> dict:
    """Apply user correction to the current entity list."""
    last_human = next(
        (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), None
    )
    correction_text = last_human.content if last_human else ""
    result = apply_correction(state["entities"], correction_text)
    return {"entities": [e.model_dump() for e in result.entities]}


async def cancel_node(state: AgentState) -> dict:
    """Acknowledge cancellation — no meal is logged."""
    return {"messages": [AIMessage(content="Cancelled. No meal logged.")]}


async def log_node(state: AgentState) -> dict:
    """Persist confirmed meal to Postgres and Redis."""
    from backend.agent.tools.usda import USDAResult

    from backend.agent.tools.meals import normalize_meal_type

    results = [USDAResult(**r) for r in state["usda_results"]]
    meal_type = normalize_meal_type(state.get("meal_type"))
    result = await log_meal(state["user_id"], results, meal_type)
    return {"messages": [AIMessage(content=result.message)]}


# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------


def _route_input(state: AgentState) -> str:
    return "classify" if state.get("image_b64") else "extract"


def _route_after_classify(state: AgentState) -> str:
    last = state["messages"][-1] if state["messages"] else None
    if isinstance(last, AIMessage) and "couldn't identify" in last.content:
        return END
    return "extract"


def _route_response(state: AgentState) -> str:
    last_human = next(
        (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), None
    )
    if last_human is None:
        return "cancel"
    intent = classify_intent(last_human.content)
    if intent == "confirm":
        return "log"
    if intent == "correct":
        return "apply_correction"
    return "cancel"  # reject


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_graph(checkpointer=None):
    """Build and compile the meal logging StateGraph.

    Args:
        checkpointer: Optional AsyncPostgresSaver for multi-session history.

    Returns:
        Compiled LangGraph graph with interrupt_after=["present"].
    """
    workflow = StateGraph(AgentState)

    workflow.add_node("router", router_node)
    workflow.add_node("classify", classify_node)
    workflow.add_node("extract", extract_node)
    workflow.add_node("usda_batch", usda_batch_node)
    workflow.add_node("present", present_node)
    workflow.add_node("intent_router", intent_router_node)
    workflow.add_node("apply_correction", apply_correction_node)
    workflow.add_node("cancel", cancel_node)
    workflow.add_node("log", log_node)

    workflow.set_entry_point("router")

    workflow.add_conditional_edges(
        "router",
        _route_input,
        {"classify": "classify", "extract": "extract"},
    )
    workflow.add_conditional_edges(
        "classify",
        _route_after_classify,
        {"extract": "extract", END: END},
    )
    workflow.add_edge("extract", "usda_batch")
    workflow.add_edge("usda_batch", "present")
    # present → interrupt → intent_router (on resume)
    workflow.add_edge("present", "intent_router")
    workflow.add_conditional_edges(
        "intent_router",
        _route_response,
        {"log": "log", "apply_correction": "apply_correction", "cancel": "cancel"},
    )
    workflow.add_edge("apply_correction", "usda_batch")
    workflow.add_edge("log", END)
    workflow.add_edge("cancel", END)

    return workflow.compile(
        checkpointer=checkpointer,
        interrupt_after=["present"],
    )
