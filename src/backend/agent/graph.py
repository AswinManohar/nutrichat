from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from backend.agent.tools.decompose import decompose_to_ingredients
from backend.agent.tools.meals import (
    FoodEntity,
    apply_correction,
    classify_food_image,
    classify_intent,
    extract_entities,
    format_confirmation_card,
    log_meal,
)
from backend.agent.tools.saved_meals import find_saved_meal, saved_meal_to_results
from backend.agent.tools.usda import usda_lookup_batch
from backend.config import get_tunables

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
    # My Meals: action="decompose" triggers the break-into-ingredients branch;
    # from_saved is set when the card was prefilled from a saved meal.
    action: str | None
    from_saved: bool
    meal_id: str | None


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


async def saved_lookup_node(state: AgentState) -> dict:
    """Check if the typed meal matches a saved My Meal; prefill if so.

    On a hit, loads the saved ingredients into usda_results (verbatim, so a
    straight confirm logs exactly what was saved) and entities (so a correction
    can still re-resolve), and flags from_saved to skip extraction/USDA.
    """
    first_human = next(
        (m for m in state["messages"] if isinstance(m, HumanMessage)), None
    )
    text = first_human.content if first_human else ""
    meal = await find_saved_meal(state["user_id"], text)
    if meal is None:
        return {"from_saved": False}
    usda_results, entities = saved_meal_to_results(meal)
    return {"from_saved": True, "usda_results": usda_results, "entities": entities}


async def decompose_node(state: AgentState) -> dict:
    """Break the original dish into ingredients (the "Break into ingredients" toggle).

    Decomposes the user's first description into ingredient lines, re-parses them
    into entities, and falls through to usda_batch → present. On failure, keeps
    the current entities (graceful no-op → re-presents the same single item).
    """
    first_human = next(
        (m for m in state["messages"] if isinstance(m, HumanMessage)), None
    )
    description = first_human.content if first_human else ""
    lines = decompose_to_ingredients(description)
    if not lines:
        return {"action": None}
    try:
        result = extract_entities(", ".join(lines))
        valid = [e for e in result.entities if e.qty_g > 0]
    except Exception:
        valid = []
    if not valid:
        return {"action": None}
    return {"action": None, "entities": [e.model_dump() for e in valid]}


async def combine_node(state: AgentState) -> dict:
    """Collapse every auto-decomposed ingredient group back to its source dish.

    Triggered by the card's "Log as single item" action. Each source_dish group
    becomes a single entity named after the dish (default 1g placeholder qty so
    usda_batch re-resolves it); entities without provenance are kept as-is.
    Falls through to usda_batch → present.
    """
    rebuilt: list[dict] = []
    seen: set[str] = set()
    for raw in state["entities"]:
        dish = raw.get("source_dish")
        if dish is None:
            keep = dict(raw)
            keep["source_dish"] = None
            rebuilt.append(keep)
            continue
        if dish in seen:
            continue
        seen.add(dish)
        rebuilt.append(
            FoodEntity(food_name=dish, qty_g=1, unit="g").model_dump()
        )
    return {"action": None, "entities": rebuilt}


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


def _auto_decompose_enabled() -> bool:
    """Feature flag for automatic composite-dish decomposition."""
    return get_tunables().features.auto_decompose_enabled


async def auto_decompose_node(state: AgentState) -> dict:
    """Break only is_composite entities into ingredients, per food, in order.

    Composite entities are decomposed via the shared primitive (portion-aware:
    the entity's gram weight is included so ingredients scale), re-parsed into
    ingredient entities tagged with source_dish provenance, and spliced in place.
    Atomic entities pass through untouched. Any failure (empty decompose, empty
    re-extract) degrades to keeping the original dish as a single entity.
    """
    if not _auto_decompose_enabled():
        return {"entities": state["entities"]}

    out: list[dict] = []
    for raw in state["entities"]:
        entity = FoodEntity(**raw)
        if not entity.is_composite:
            out.append(entity.model_dump())
            continue
        desc = f"{entity.qty_g:g} g {entity.food_name}"
        lines = decompose_to_ingredients(desc)
        if not lines:
            out.append(entity.model_dump())
            continue
        try:
            parsed = extract_entities(", ".join(lines)).entities
            sub = [e for e in parsed if e.qty_g > 0]
        except Exception:
            sub = []
        if not sub:
            out.append(entity.model_dump())
            continue
        for ing in sub:
            ing.source_dish = entity.food_name
            out.append(ing.model_dump())
    return {"entities": out}


async def usda_batch_node(state: AgentState) -> dict:
    """Resolve all food entities against USDA FoodData Central (cache-first)."""
    entities = [FoodEntity(**e) for e in state["entities"]]
    results = await usda_lookup_batch(entities)
    for entity, result in zip(entities, results):
        result.source_dish = entity.source_dish
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

    from backend.agent.tools.meals import normalize_meal_type, _meal_label

    results = [USDAResult(**r) for r in state["usda_results"]]
    meal_type = normalize_meal_type(state.get("meal_type"))
    label = _meal_label(state["entities"])
    result = await log_meal(state["user_id"], results, meal_type, label=label)
    return {"meal_id": result.meal_id, "messages": [AIMessage(content=result.message)]}


# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------


def _route_input(state: AgentState) -> str:
    return "classify" if state.get("image_b64") else "saved_lookup"


def _route_after_saved_lookup(state: AgentState) -> str:
    # Saved meal matched → straight to the card; otherwise extract as usual.
    return "present" if state.get("from_saved") else "extract"


def _route_after_classify(state: AgentState) -> str:
    last = state["messages"][-1] if state["messages"] else None
    if isinstance(last, AIMessage) and "couldn't identify" in last.content:
        return END
    return "extract"


def _route_response(state: AgentState) -> str:
    # "Break into ingredients" takes priority over confirm/correct/reject.
    if state.get("action") == "decompose":
        return "decompose"
    if state.get("action") == "combine":
        return "combine"
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
    workflow.add_node("saved_lookup", saved_lookup_node)
    workflow.add_node("extract", extract_node)
    workflow.add_node("auto_decompose", auto_decompose_node)
    workflow.add_node("decompose", decompose_node)
    workflow.add_node("combine", combine_node)
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
        {"classify": "classify", "saved_lookup": "saved_lookup"},
    )
    # Text input first checks for a saved My Meal; hit → present, miss → extract.
    workflow.add_conditional_edges(
        "saved_lookup",
        _route_after_saved_lookup,
        {"present": "present", "extract": "extract"},
    )
    workflow.add_conditional_edges(
        "classify",
        _route_after_classify,
        {"extract": "extract", END: END},
    )
    workflow.add_edge("extract", "auto_decompose")
    workflow.add_edge("auto_decompose", "usda_batch")
    workflow.add_edge("decompose", "usda_batch")
    workflow.add_edge("combine", "usda_batch")
    workflow.add_edge("usda_batch", "present")
    # present → interrupt → intent_router (on resume)
    workflow.add_edge("present", "intent_router")
    workflow.add_conditional_edges(
        "intent_router",
        _route_response,
        {
            "log": "log",
            "apply_correction": "apply_correction",
            "decompose": "decompose",
            "combine": "combine",
            "cancel": "cancel",
        },
    )
    workflow.add_edge("apply_correction", "usda_batch")
    workflow.add_edge("log", END)
    workflow.add_edge("cancel", END)

    return workflow.compile(
        checkpointer=checkpointer,
        interrupt_after=["present"],
    )
