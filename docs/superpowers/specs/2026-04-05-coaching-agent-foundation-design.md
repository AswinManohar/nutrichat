# Coaching Agent Foundation — Design Spec
**Date:** 2026-04-05
**Status:** Approved
**Scope:** Phase 2 foundation — intent routing + natural language macronutrient/micronutrient query answering

---

## 1. Overview

Users can ask nutrition questions in the same chat thread as meal logging. The system routes each message to either the existing logging agent or the new coaching agent without the user doing anything special.

This spec covers the foundation layer: intent classification and query answering. Proactive coaching (daily nudges, protein alerts, weekly check-ins) is built on top of this in a later phase.

---

## 2. Architecture

```
user message
      │
 [intent_classifier]   Flash-Lite · two-stage (keyword → LLM fallback)
      │
  ┌───┴──────────────────────────┐
  │                              │
log_meal                    coaching
  │                              │
[existing LangGraph]      [CoachingAgent]
                                 │
                          [parse_query]      Flash-Lite structured output
                                 │
                          [fetch_data]       Python — Redis or Postgres
                                 │
                          [generate_response] Gemini 2.5 Flash
```

**Key constraints:**
- Agents never call each other — all routing goes through the orchestrator
- Coaching agent responses must be grounded in logged data only — no invented numbers
- No LangGraph graph for the coaching agent (linear pipeline, no interrupt needed)

---

## 3. Intent Classifier

### Two-stage design (token-minimal)

**Stage 1 — keyword pre-filter (zero LLM cost)**

```python
_LOG_SIGNALS   = {"had", "ate", "just had", "for breakfast", "for lunch",
                  "for dinner", "logged", "i ate", "i had"}
_QUERY_SIGNALS = {"how much", "how many", "did i", "what was", "show me",
                  "vitamin", "mineral", "protein", "calories", "fiber",
                  "carbs", "fat", "nutrient", "today", "this week", "yesterday"}
```

If any log signal is present and no query signal → `log_meal` without LLM.
If any query signal is present → `coaching` without LLM.
If ambiguous → LLM fallback.

**Stage 2 — LLM fallback (Flash-Lite, ~30 input + 1 output token)**

```
log_meal or coaching?
log_meal: user describes food they ate ("2 eggs", "had pasta")
coaching: user asks about nutrition ("how much protein", "vitamin B12")
Reply with one word.
```

Structured output: `IntentResult(type: Literal["log_meal", "coaching"])`
`max_output_tokens=5` — single token answer, no explanation. (`log_meal` is one token in Flash-Lite's tokeniser; `coaching` is one token. 5 is a safe ceiling.)

### File
`src/backend/agent/orchestrator.py` — `_classify_intent(message: str) -> str`

---

## 4. Coaching Agent

### 4.1 Query Parser

Flash-Lite structured output. Extracts time range and nutrient list from the user's message.

```python
class QueryParsed(BaseModel):
    time_range: Literal["today", "yesterday", "this_week", "last_7_days", "custom"]
    date_from: Optional[date]   # populated for "custom" and "yesterday"
    date_to: Optional[date]
    nutrients: list[str]        # USDA nutrient names or macro aliases
                                # e.g. ["kcal", "protein_g", "Vitamin B12, total"]
    include_goals: bool         # True when user asks "did I hit my goal"
```

Prompt (short, direct):
```
Extract the time range and nutrients from this nutrition question.
time_range: today | yesterday | this_week | last_7_days | custom
nutrients: use USDA names for micros, macro aliases (kcal/protein_g/carbs_g/fat_g/fiber_g) for macros.
include_goals: true if the user asks about goals or targets.
```

### 4.2 Data Fetcher

Pure Python — no LLM. Selects data source based on parsed query.

| Condition | Source | Function |
|---|---|---|
| `time_range == "today"` + macro only | Redis | `get_today_totals(user_id)` |
| Any other range + macro | `meal_log` columns | `get_macros_for_range(user_id, date_from, date_to)` |
| Any range + micronutrient | `meal_log.entities` JSONB | `get_micronutrients_for_range(user_id, date_from, date_to, nutrient_names)` |
| `include_goals=True` | `user_goal` table | fetched alongside any of the above |

JSONB micronutrient query (unnests `entities` array):
```sql
SELECT
    SUM((item->'nutrients'->:nutrient->>'amount')::float) AS total,
    MAX(item->'nutrients'->:nutrient->>'unit') AS unit
FROM meal_log,
     jsonb_array_elements(entities) AS item
WHERE user_id = :user_id
  AND logged_at::date BETWEEN :date_from AND :date_to
  AND item->'nutrients' ? :nutrient
```

### 4.3 Response Generator

Gemini 2.5 Flash. Data injected as a compact JSON block, LLM formats into natural language.

System prompt:
```
You are a concise nutrition assistant.
Answer using only the data provided — never invent numbers.
Include goal comparisons when goal data is present.
Keep answers under 3 sentences.
```

Example outputs:
- "You've had 1,240 kcal today — 62% of your 2,000 kcal goal."
- "Your average protein this week was 87g/day, against a 150g goal."
- "You got about 2.1 mcg of vitamin B12 today, mostly from the salmon."
- "No meals logged yet today, so I can't answer that yet."

### 4.4 Files

| File | Action | Responsibility |
|---|---|---|
| `src/backend/agent/coaching.py` | Create | `CoachingAgent` — parse_query, fetch_data, generate_response |
| `src/backend/agent/tools/history.py` | Create | `get_macros_for_range()`, `get_micronutrients_for_range()` |
| `src/backend/agent/orchestrator.py` | Modify | `_classify_intent()`, route to CoachingAgent |
| `src/backend/api/meals.py` | Modify | Pass coaching response through same response shape |

---

## 5. Data Flow

```
"how much vitamin B12 did I have today?"
    │
[_classify_intent]  → keyword: "how much", "vitamin" → "coaching"
    │
[parse_query]       → QueryParsed(time_range="today", nutrients=["Vitamin B12, total"], include_goals=False)
    │
[fetch_data]        → time_range=today + micronutrient → JSONB query on meal_log.entities
    │
[generate_response] → "You got 2.1 mcg of vitamin B12 today, from the scrambled eggs and salmon."
```

---

## 6. Error Handling

| Case | Response |
|---|---|
| No meals logged in range | "No meals logged for that period yet." |
| Nutrient not found in any logged meal | "I don't have data on [nutrient] for that period." |
| Redis unavailable (today macro) | Fall back to Postgres `meal_log` aggregation |
| Ambiguous time range | Default to "today", note assumption in response |

---

## 7. Testing Strategy

| Test | Input | Pass criteria |
|---|---|---|
| Keyword pre-filter — log | "2 scrambled eggs" | `log_meal`, no LLM call |
| Keyword pre-filter — query | "how much protein today" | `coaching`, no LLM call |
| LLM fallback | "coffee" (ambiguous) | routes correctly |
| Query parser — today macro | "how many calories today?" | `time_range=today`, `nutrients=["kcal"]` |
| Query parser — micronutrient | "how much B12 this week?" | `time_range=this_week`, `nutrients=["Vitamin B12, total"]` |
| Fetch — today macro | Redis returns totals | response includes kcal + goal % |
| Fetch — micronutrient | JSONB query returns values | response names the food sources |
| No data | Empty meal_log | graceful "no data" message |

---

## 8. What this is NOT (yet)

- **Proactive coaching** — daily protein alerts, weekly check-ins (Phase 2 next layer)
- **Recipe suggestions** — recipe agent is a separate specialist
- **Trend analysis** — "am I improving?" comparisons over weeks/months
- **Streaming responses** — full response returned at once for now
