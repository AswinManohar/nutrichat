# `backend.agent` — the meal-logging & coaching agent

See [Architecture](../architecture.md) for how these modules fit together.

## Orchestrator

```{automodule} backend.agent.orchestrator
:members:
```

## LangGraph meal-logging graph

```{automodule} backend.agent.graph
:members:
```

## Coaching agent (Pydantic AI)

```{automodule} backend.agent.coaching
:members:
```

## Context building

```{automodule} backend.agent.context
:members:
```

## LLM clients

```{automodule} backend.agent.llm
:members:
```

## Cost tracking

```{automodule} backend.agent.cost
:members:
```

## Tools

### Meal extraction & logging

```{automodule} backend.agent.tools.meals
:members:
```

### USDA FoodData Central lookup

```{automodule} backend.agent.tools.usda
:members:
```

### History & aggregates

```{automodule} backend.agent.tools.history
:members:
```
