# Contract: GLiDE routing request (outbound)

**Direction**: backend → Fastino `POST https://api.fastino.ai/v1/systemone`
(plain `httpx`, no SDK) · **Model**: `glide.model` (`fastino/GLiDE`)

Replaces [jev-routing-request.md](../../001-jev-intent-routing/contracts/jev-routing-request.md).
The user-facing API is unchanged.

Taken from Fastino's docs on 2026-10-13 and **not yet confirmed by a live
response**. Plan step 1 confirms it and corrects this file.

## Request

Headers: `X-API-Key: $FASTINO_API_KEY`, `Content-Type: application/json`.

```json
{
  "model": "fastino/GLiDE",
  "state": { "message": "<raw user text>" },
  "questions": {
    "intent":         { "type": "choice", "instructions": "…", "criteria": { "log_meal": …, "coaching": …, "other": "…" } },
    "reports_food":   { "type": "noul",   "instructions": "…", "criteria": { "true": "…", "false": "…" } },
    "needs_guidance": { "type": "noul",   "instructions": "…" }
  }
}
```

- Exactly these three top-level keys. Anything else returns `422`.
- State is the current message text only. No user id, history, goals,
  conditions or profile (001 FR-015).
- Question text is the Jev wording, unchanged. `intent.criteria.log_meal` and
  `.coaching` are objects today (`covers`, `excludes`, `examples`); if GLiDE
  rejects that, they are rendered to one string each (research R2).
- Any wording or shape change re-runs the routing gate.
- **Holdout rule** (unchanged): no string in any criteria text equals a `text`
  in `eval/cases/intent_routing.jsonl`; enforced by a unit test.

## Response (fields the backend reads)

```json
{
  "model": "glide",
  "answers": {
    "intent":         { "type": "choice", "choice": "log_meal", "confidence": 0.99,
                        "probabilities": { "log_meal": 0.995, "coaching": 0.004, "other": 0.001 } },
    "reports_food":   { "type": "noul", "noul": 0.03, "confidence": 0.94 },
    "needs_guidance": { "type": "noul", "noul": 0.10, "confidence": 0.80 }
  },
  "usage": { "input_tokens": 700, "output_tokens": 3 }
}
```

| Read | Used for |
|---|---|
| `answers.intent.probabilities.log_meal` | `intent`, `certainty` (P(log_meal) against the rest; the response's own `confidence` is not used) |
| `answers.intent.choice` | `raw_choice` |
| `answers.reports_food.noul` | offer to log |
| `answers.needs_guidance.noul` | recorded only |
| `model` | `judge_model` |
| `usage.input_tokens` | cost tracking |

A missing answer, an unknown choice or a probability outside 0–1 is
`malformed_response`.

## Failure handling on the reply path

One attempt, `glide.request_timeout_s` (0.8 s), no retries.

| Outcome | Reason recorded | Then |
|---|---|---|
| No `FASTINO_API_KEY` | `not_configured` | Gemini routes |
| Timeout or transport error | `timeout` / exception class | Gemini routes |
| `425` warming, `429`, `503` | `http_<status>` | Gemini routes; not retried here |
| `401`, `402`, `403`, `404`, `422` | `http_<status>`, logged at error level | Gemini routes; needs operator action |
| Bad shape | `malformed_response` | Gemini routes |

Logs carry the status or exception class only, never the request or response
body.

## Startup warm-up

One canned request (`{"message": "warm up"}`) with `glide.warm_up_timeout_s`.
On `425`, wait for `Retry-After` (default 60 s) and try once more. Never
raises; never blocks startup.
