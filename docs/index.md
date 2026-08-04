# NutriChat documentation

NutriChat is a learning project for building robust agentic systems: users
describe meals in natural language, the agent extracts food entities,
resolves them against USDA FoodData Central, and tracks daily nutrition
goals — over a web app, and Telegram.

Start with [Architecture](architecture.md) for the system-level picture,
then drill into a guide or the API reference below.

```{toctree}
:maxdepth: 1
:caption: Architecture & guides

architecture
observability
tuning-prompts
coaching-meal-plans
telegram-bot
integration-api
frontend-design
```

```{toctree}
:maxdepth: 1
:caption: Deployment

deployment/railway
deployment/2026-04-05-vertex-ai-migration
```

```{toctree}
:maxdepth: 2
:caption: API reference

reference/index
```

```{toctree}
:maxdepth: 1
:caption: Drafts

pregnancy-features-requirements
```
