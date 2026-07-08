from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Annotated

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from backend.agent.tools.decompose import decompose_to_entities
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
    # Cache for the "Break into ingredients" decomposition — populated on first
    # LLM call; subsequent presses read from here and skip the LLM.
    decomposed_entities: list[dict]


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


async def router_node(state: AgentState) -> dict:
    """No-op — routing is handled by conditional edges."""
    return {}


async def classify_node(state: AgentState) -> dict:
    """Identify food items in the image. Routes to END if no food found."""
    image_b64 = state.get("image_b64") or ""
    # Offload the blocking LLM round-trip so the event loop isn't frozen
    # while one request is classifying an image (see decompose/extract below).
    result = await asyncio.to_thread(classify_food_image, image_b64)
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

    Returns cached result from decomposed_entities if available, skipping the
    LLM call. On cache miss, calls decompose_to_entities (one structured LLM
    call — no separate re-extract) and warms the cache. On failure, returns a
    graceful no-op (re-presents same card).
    """
    cached = state.get("decomposed_entities") or []
    if cached:
        return {"action": None, "entities": cached}

    # Use current entities (what's on the card) rather than the first human
    # message — the first message may belong to an earlier turn on the same
    # thread if the user typed a new meal without confirming the previous card.
    entities = state.get("entities") or []
    if entities:
        description = ", ".join(f"{e['qty_g']:g} g {e['food_name']}" for e in entities)
    else:
        first_human = next(
            (m for m in state["messages"] if isinstance(m, HumanMessage)), None
        )
        description = first_human.content if first_human else ""
    parsed = await asyncio.to_thread(decompose_to_entities, description)
    valid = [e for e in parsed if e.qty_g > 0]
    if not valid:
        return {"action": None}
    serialised = [e.model_dump() for e in valid]
    return {"action": None, "entities": serialised, "decomposed_entities": serialised}


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
            FoodEntity(
                food_name=dish, qty_g=1, unit="g", is_composite=True
            ).model_dump()
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
        result = await asyncio.to_thread(extract_entities, last_human.content)
        # Filter out any entity the LLM returned with qty_g <= 0 (can't be logged)
        valid = [e for e in result.entities if e.qty_g > 0]
    except Exception:
        valid = []
    return {"entities": [e.model_dump() for e in valid]}


def _auto_decompose_enabled() -> bool:
    """Feature flag for automatic composite-dish decomposition."""
    return get_tunables().features.auto_decompose_enabled


async def _decompose_one(entity: FoodEntity) -> list[FoodEntity]:
    """Decompose a single entity into its ingredients (one LLM call, or none).

    Composite entities are broken via the shared primitive (portion-aware: the
    entity's gram weight is included so ingredients scale) and each ingredient
    is tagged with source_dish provenance. Atomic entities and any failure
    (empty decompose) degrade to keeping the original entity as-is.
    """
    if not entity.is_composite:
        return [entity]
    desc = f"{entity.qty_g:g} g {entity.food_name}"
    sub = await asyncio.to_thread(decompose_to_entities, desc)
    sub = [e for e in sub if e.qty_g > 0]
    if not sub:
        return [entity]
    for ing in sub:
        ing.source_dish = entity.food_name
    return sub


async def auto_decompose_node(state: AgentState) -> dict:
    """Break only is_composite entities into ingredients, all dishes in parallel.

    Each entity is decomposed by _decompose_one; the calls run concurrently
    (asyncio.gather) so a multi-dish meal costs one round-trip of wall-clock,
    not one per dish. Order is preserved: gather returns per-entity groups in
    input order and they are spliced back in place. Atomic entities pass
    through untouched.
    """
    if not _auto_decompose_enabled():
        return {"entities": state["entities"]}

    entities = [FoodEntity(**raw) for raw in state["entities"]]
    groups = await asyncio.gather(*(_decompose_one(e) for e in entities))
    out = [ing.model_dump() for group in groups for ing in group]
    return {"entities": out}


async def usda_batch_node(state: AgentState) -> dict:
    """Resolve all food entities against USDA FoodData Central (cache-first)."""
    entities = [FoodEntity(**e) for e in state["entities"]]
    results = await usda_lookup_batch(entities)
    for entity, result in zip(entities, results):
        result.source_dish = entity.source_dish
        result.is_composite = entity.is_composite
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
    result = await asyncio.to_thread(
        apply_correction, state["entities"], correction_text
    )
    return {"entities": [e.model_dump() for e in result.entities]}


async def cancel_node(state: AgentState) -> dict:
    """Acknowledge cancellation — no meal is logged."""
    return {"messages": [AIMessage(content="Cancelled. No meal logged.")]}


async def log_node(state: AgentState) -> dict:
    """Persist confirmed meal to Postgres and Redis."""
    from backend.agent.tools.meals import _meal_label, normalize_meal_type
    from backend.agent.tools.usda import USDAResult

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
