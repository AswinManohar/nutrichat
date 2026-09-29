# Contract: Jev routing request (outbound)

**Direction**: backend → TypeSafe `POST /v1/systemone` (via `typesafe-sdk`
`AsyncTypeSafeClient.system_one`) · **Model**: `typesafe.model` (`jev-latest`)

This is the one external interface the feature adds. The user-facing API
(`POST /meals/log`, Telegram text handler) keeps its request and response
shapes; see [chat-response.md](chat-response.md) for the only visible change.

## Request

State is the current message text only (FR-015). No user id, history, goals,
conditions or profile.

```json
{
  "model": "jev-latest",
  "state": { "message": "<raw user text>" },
  "questions": {
    "intent": {
      "type": "choice",
      "instructions": "`message` was sent by a user to a nutrition-tracking assistant. What is the user doing in `message`?",
      "criteria": {
        "log_meal": {
          "covers": "Reporting or naming food or drink they ate, drank, are eating, or are about to eat, so that it can be recorded. A bare food, drink, or dish name with no verb and no question is a report, with or without a quantity.",
          "excludes": "Any question or request for advice, even when it mentions food. A food name that contains a nutrient word is still a report, not a question about that nutrient.",
          "examples": ["oatmeal with blueberries", "greek yogurt", "I had chicken tikka masala and naan for lunch", "a high protein yogurt", "half a glass of 3.8% fat milk"]
        },
        "coaching": {
          "covers": "Asking a question or requesting help about nutrition: totals, history, trends, goals, progress, whether a food is healthy, what to eat, meal plans, or advice.",
          "excludes": "Statements that only report what was eaten.",
          "examples": ["how much protein did I eat last week?", "what food do I eat the most?", "is oatmeal good for cholesterol?", "plan my remaining meals to hit my goals", "suggest a high-fiber snack"]
        },
        "other": "A greeting, thanks, small talk, or anything that is neither a food report nor a nutrition question."
      }
    },
    "reports_food": {
      "type": "noul",
      "instructions": "Does `message` state that the user ate, drank, is eating, or is about to eat a specific food or drink at a specific meal or moment?",
      "criteria": {
        "true": "Names something they had or are having now, e.g. 'I had pizza, was that bad?', 'just ate two donuts, how bad is that'.",
        "false": "Only asks about a food in general, about their totals or history, or for advice, without saying they ate a specific thing just now, e.g. 'is pizza healthy?', 'how much protein have I had today?'."
      }
    },
    "needs_guidance": {
      "type": "noul",
      "instructions": "Assume `message` is addressed to a nutrition coach. Does answering it call for a dietary recommendation or a judgment about what is healthy or appropriate, rather than only reading back the user's own logged data?"
    }
  }
}
```

Question wording above is the probed version (research R1). Any wording change
is a behaviour change and must re-run the routing eval gate.

**Holdout rule**: no string in any `examples` / `criteria` text may equal a
`text` in `eval/cases/intent_routing.jsonl` (enforced by a unit test).

## Response (fields the backend reads)

```json
{
  "model": "jev-1.13.0",
  "answers": {
    "intent":         { "type": "choice", "choice": "log_meal", "confidence": 0.94,
                        "probabilities": { "log_meal": 0.97, "coaching": 0.02, "other": 0.01 } },
    "reports_food":   { "type": "noul", "noul": 0.03 },
    "needs_guidance": { "type": "noul", "noul": 0.04 }
  },
  "usage": { "input_tokens": 700, "output_tokens": 40 }
}
```

Read via the SDK's typed views: `response.choices["intent"].probabilities["log_meal"]`,
`response.choices["intent"].choice`, `response.nouls["reports_food"].noul`,
`response.nouls["needs_guidance"].noul`, `response.usage.input_tokens`.

## Client settings

| Setting | Value | Source |
|---|---|---|
| API key | `TYPESAFE_API_KEY` env var | absent ⇒ client never built |
| Per-attempt timeout | `typesafe.request_timeout_s` (0.8 s) | FR-007 |
| Retries | `RetryPolicy(max_retries=0)` | FR-007: no stacked retries |
| Client lifetime | one `AsyncTypeSafeClient` per process, created lazily | reuses the HTTP connection |

## Failure contract

Every one of these yields `RoutingJudgment = None` ("unavailable"), a
`route_message` span with `failure` set, and the Gemini second opinion — never
an exception to the caller:

| Condition | `failure` value |
|---|---|
| `TYPESAFE_API_KEY` unset | `not_configured` (span attribute only; warning logged once at startup) |
| Timeout | `TypeSafeAPITimeoutError` |
| Network error | `TypeSafeAPIConnectionError` |
| 401 / 403 | `TypeSafeAuthenticationError` / `TypeSafePermissionDeniedError` |
| 429 | `TypeSafeRateLimitError` |
| 4xx / 5xx other | `TypeSafeBadRequestError`, `TypeSafeInternalServerError`, … |
| Response missing an expected answer or option | `malformed_response` |

`asyncio.CancelledError` (the turn turned out to be a pending-card reply) is
not a failure; it is re-raised so the cancelled task ends cleanly.
