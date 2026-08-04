# Decompose Cache — Design Spec

**Date:** 2026-06-21
**Status:** Approved

---

## Overview

"Break into ingredients" currently calls the LLM every time the button is pressed, even when the user cycles Break → Log as single item → Break again on the same confirmation card. This spec adds a within-thread cache so the second press returns the already-computed result instantly.

Cross-session caching is out of scope: repeated dish names are handled by My Meals.

---

## Approach

Store the decompose result in LangGraph checkpoint state. The checkpoint is PostgreSQL-backed, so the cache survives across HTTP calls for the same paused thread without any new infrastructure.

---

## State change

Add one field to `AgentState`:

```python
decomposed_entities: list[dict]   # default []
```

Populated by `decompose_node` on the first successful decompose. Reset to `[]` only on fresh graph invocations (never on resumes).

---

## decompose_node logic

```
if state["decomposed_entities"]:
    # Cache hit — return immediately, no LLM call
    return {"action": None, "entities": state["decomposed_entities"]}

# Cache miss — call LLM as before
lines = decompose_to_ingredients(description)
...
valid = [extracted entities]
if not valid:
    return {"action": None}   # graceful no-op, don't populate cache

return {
    "action": None,
    "entities": valid,
    "decomposed_entities": valid,   # warm the cache
}
```

---

## combine_node

No changes. It rebuilds the composite view from `source_dish` provenance on the current `entities`. `decomposed_entities` is left intact so a subsequent Break press still hits the cache.

---

## Orchestrator (fresh invocations)

`decomposed_entities` must be included in the initial state dict passed to `graph.ainvoke` on fresh (non-resume) calls:

```python
result = await graph.ainvoke(
    {
        ...existing fields...,
        "decomposed_entities": [],
    },
    config=config,
)
```

This ensures new meals always get a live LLM call.

---

## Files changed

| File | Change |
|---|---|
| `src/backend/agent/graph.py` | Add `decomposed_entities` to `AgentState`; update `decompose_node`; add field to initial state in the orchestrator call |

No schema migrations, no Redis keys, no new tables.

---

## Out of scope

- Cross-session decompose caching (My Meals already covers repeated dishes)
- UI changes (button stays available; caching is transparent)
- Caching failed decompose attempts (empty result → no cache entry, next press retries LLM)
