# `backend.agent` — the meal-logging & coaching agent

See [Architecture](../architecture.md) for how these modules fit together.

## Orchestrator

```{automodule} backend.agent.orchestrator
:members:
```

## LangGraph meal-logging graph

```{automodule} backend.agent.meal_logging.graph
:members:
```

## Coaching agent (Pydantic AI)

```{automodule} backend.agent.coaching.agent
:members:
```

## Coaching response store

```{automodule} backend.agent.coaching.store
:members:
```

## Context building

```{automodule} backend.agent.coaching.context
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

```{automodule} backend.agent.meal_logging.meals
:members:
```

### USDA FoodData Central lookup

```{automodule} backend.agent.food.usda
:members:
```

### History & aggregates

```{automodule} backend.agent.intake.history
:members:
```
