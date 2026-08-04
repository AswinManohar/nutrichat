# Coaching meal plans — "what can I eat to hit today's goals"

How the coaching agent turns a user's remaining daily goals into a concrete,
proportioned meal plan. Covers the request shape, the three-stage pipeline, the
data contract that makes the *remaining-gap* math possible, and how to verify it.

## What it does

When a user asks any "what / how should I eat" question — e.g.

- "what can I eat today to hit today's goals"
- "what should I have for dinner to finish my protein goal?"
- "give me a simple one-day meal plan that meets my goals"
- "I have 600 calories left, suggest a meal"

…the agent computes, per macro,

```
REMAINING = daily goal − today's logged total      (kcal, protein_g, fiber_g)
```

and returns a **recipe-card** answer: 2–4 concrete foods with approximate
gram/portion amounts and their rough macro contributions that together close the
remaining gap, respecting the user's `dietary_prefs`.

This is treated as a **core NutriChat function**, never refused or deferred to a
dietitian. Only clinical/medical or weight-loss *calorie-prescription* requests
("how many calories should I eat to lose 5kg") are declined.

## Pipeline

The coaching agent (`src/backend/agent/coaching.py`) is a linear three-stage
pipeline. The orchestrator routes here when the intent is `coaching` (see
Routing below).

```
parse_query  ──▶  fetch_data  ──▶  generate_response
 (Flash-Lite)      (Redis/PG)        (Gemini 2.5 Flash)
```

### 1. `parse_query` — classify the question

Prompt: `src/backend/config/prompts/query_parse_system.md`. Produces a
`QueryParsed` (time range, nutrients, `include_goals`, `include_foods`).

The decisive rule for meal plans: **any** meal-suggestion / "what should I eat" /
"plan my remaining meals" phrasing is forced to

```
time_range   = "today"
include_goals = True
```

regardless of other period language in the question — so we always have *today's*
remaining totals to work against the daily goals.

### 2. `fetch_data` — assemble grounding data

For a meal-plan query (`today` + `include_goals`, no specific nutrients) it
returns:

| key            | source                              | purpose                          |
|----------------|-------------------------------------|----------------------------------|
| `today_totals` | Redis (`get_today_totals`)          | what's already eaten today       |
| `period`       | computed                            | `days: 1`, label `today`         |
| `goals`        | Postgres `user_goal`                | `kcal_goal`, `protein_goal`, `fiber_goal`, `dietary_prefs` |

`today_totals` falls back to Postgres (`get_macros_for_range`) if Redis is down.
`dietary_prefs` is always included with the goals so the model can avoid
restricted foods.

This **two-block contract — `today_totals` *and* `goals` together — is what makes
the remaining-gap math possible.** It is pinned by
`test_handle_meal_plan_feeds_today_totals_and_goals` in `tests/test_coaching.py`.

### 3. `generate_response` — render the recipe card

Prompt: `src/backend/config/prompts/coaching_response_system.md`. The model
computes `REMAINING = goal − today` per macro and emits markdown:

```
**🥗 Your plan to hit today's goals**

_Remaining today: 42g protein · 16g fiber · 550 kcal_

**🍽️ Dinner**
- Grilled chicken breast, 120g — ~37g protein, ~200 kcal
- Cooked black beans, 1/2 cup — ~8g protein, ~7g fiber, ~115 kcal
- Steamed broccoli, 1 cup — ~3g protein, ~5g fiber, ~55 kcal

**🥜 Snack**
- Almonds, 1/4 cup — ~6g protein, ~4g fiber, ~170 kcal

**Daily total: ~54g protein · ~16g fiber · ~540 kcal**
```

Card structure (per the prompt's *meal-plan output format* rule): bold title →
italic remaining line → per-meal emoji headers (🍳 Breakfast / 🥗 Lunch /
🍽️ Dinner / 🥜 Snack) with `- Food, amount — ~Xg protein, ~Y kcal` bullets → bold
daily-total line. **Only** multi-item meal plans use this card; totals/history,
single-fact, decline, and "nothing logged" answers stay as plain 1–3 sentence
prose.

## Routing into coaching

`_classify_intent` (`src/backend/agent/orchestrator.py`) is a cheap keyword
pre-filter (zero LLM / zero quota), with an LLM fallback only when ambiguous.
A message matching any `routing.query_signals` substring (`tunables.yaml`) routes
to coaching; query signals beat log signals. Meal-plan phrasings are covered by
signals such as `what should`, `should i eat`, `meal plan`, `plan my`, `today`,
`goal`, plus the macro names. So "what can I eat **today** to hit today's
**goal**s" routes to coaching deterministically (matches `today` + `goal`).

Each coaching turn consumes one quota credit (`_handle_coaching`), not one per
internal LLM call.

## Edge cases (all verified)

- **Empty day** (`n_meals: 0`) → remaining == full daily goal → a full-day plan
  across breakfast/lunch/dinner/snack.
- **Partial day** → remaining = goal − logged; plan targets just the gap. E.g.
  logged 1450 kcal / 78g protein / 14g fiber against 2000 / 120 / 30 →
  "Remaining today: 42g protein · 16g fiber · 550 kcal".
- **Dietary prefs** (`{"vegan": true}`, allergies, dislikes) → every suggestion
  respects them (tofu/beans/rice instead of meat/dairy).
- **Stated target overrides stored goal** — "I want to hit 140g protein" uses
  140, not the stored `protein_goal`.
- **Multi-day ranges** are normalized per-day before comparing to daily goals.

## Verifying

Deterministic regression tests (no live LLM):

```bash
python -m pytest tests/test_coaching.py tests/test_orchestrator.py -q
```

Key tests: `test_handle_meal_plan_feeds_today_totals_and_goals` (grounding
contract), `test_classify_intent_what_should_i_eat_is_coaching` and
`test_classify_intent_meal_plan_suggestion_is_coaching` (routing).

Live smoke check against the seeded user (needs `GOOGLE_API_KEY`, `DATABASE_URL`,
`REDIS_URL`):

```bash
python eval_coaching.py
# or a one-off:
python -c "import asyncio; from dotenv import load_dotenv; load_dotenv(); \
from backend.agent.coaching import CoachingAgent; \
print(asyncio.run(CoachingAgent().handle('<user-id>', \
'what can I eat today to hit todays goals')))"
```

## Tuning

All behavior lives in editable prompt/config files (no code change needed):

- `src/backend/config/prompts/query_parse_system.md` — when a question counts as
  a meal-plan request and how it's parsed.
- `src/backend/config/prompts/coaching_response_system.md` — remaining-gap rule,
  recipe-card format, refusal boundary, dietary-pref enforcement.
- `src/backend/config/tunables.yaml` → `routing.query_signals` — keyword
  pre-filter that routes meal-plan phrasings to coaching.

See `docs/tuning-prompts.md` for the prompt-tuning workflow.

## Known limitations

- Goals cover `kcal` / `protein` / `fiber` only; there is no carbs or fat target,
  so plans optimize against those three.
- `today_totals` from Redis exposes kcal / protein / fiber (not carbs/fat), so
  the remaining math is limited to those macros.
- Per-day breakdowns over multi-day ranges aren't available; the data layer
  returns period aggregates.
