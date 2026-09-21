# Data Model: Calibrated Intent Routing

**Spec**: [spec.md](spec.md) · **Research**: [research.md](research.md)

No new tables, columns or migrations. Two in-memory models, one new
configuration block, one extra key inside an existing JSONB value, and an
extended eval-case shape.

## RoutingJudgment (in-memory, Pydantic, `extra="forbid"`)

What Jev said about one message. Produced by the System One module; `None`
stands for "unavailable" (no key, timeout, error, malformed answer).

| Field | Type | Rule |
|---|---|---|
| `intent` | `"log_meal"` \| `"coaching"` | `log_meal` iff `p_log_meal >= 0.5` |
| `certainty` | float 0–1 | `max(p_log_meal, 1 - p_log_meal)`; always ≥ 0.5 |
| `raw_choice` | `"log_meal"` \| `"coaching"` \| `"other"` | Jev's top option, for the record only |
| `reports_food` | float 0–1 | Noul; meaningful only when `intent == "coaching"` |
| `needs_guidance` | float 0–1 | Noul; recorded, never acted on (FR-014) |
| `latency_ms` | float ≥ 0 | wall-clock of the request |

## RouteDecision (in-memory, Pydantic, `extra="forbid"`)

What the orchestrator acts on for one fresh message.

| Field | Type | Rule |
|---|---|---|
| `intent` | `"log_meal"` \| `"coaching"` | the handler to run |
| `path` | `"judgment"` \| `"second_opinion_unsure"` \| `"second_opinion_unavailable"` | which step decided |
| `judgment` | `RoutingJudgment \| None` | `None` iff path is `second_opinion_unavailable` |
| `offer_to_log` | bool | `intent == "coaching"` and `judgment.reports_food >= log_offer_min_probability`; always `False` when `judgment is None` |

**Decision rule** (the only state transition in the feature):

```text
judgment is None                         -> Gemini decides, path = second_opinion_unavailable
judgment.certainty >= intent_min_prob    -> judgment.intent,  path = judgment
otherwise                                -> Gemini decides, path = second_opinion_unsure
```

No path reads or changes the user's usage credits (FR-005). Turns with a pending
card or a photo never produce a `RouteDecision` (FR-009).

## TypeSafeConfig (new `typesafe:` block in `tunables.yaml`)

| Key | Type | Initial | Meaning |
|---|---|---|---|
| `model` | str | `"jev-latest"` | System One model id |
| `intent_min_probability` | float 0.5–1.0 | `0.75` | certainty bar (Story 2) |
| `log_offer_min_probability` | float 0–1 | `0.7` | bar for appending the offer (FR-002a) |
| `log_offer_text` | str, non-empty | `"Want me to log that? Send me what you had and I'll add it."` | the appended sentence |
| `request_timeout_s` | float > 0 | `0.8` | judgment wait limit (FR-007) |

Removed from `routing:` / `RoutingConfig`: `log_signals`, `query_signals`,
`weak_query_signals`. Kept: `confirm_keywords`, `reject_keywords`,
`new_meal_leadins`, `new_meal_exclusions` (card-reply classifier, out of scope).

Environment: `TYPESAFE_API_KEY` (optional; absent ⇒ every fresh message takes
the Gemini path and one startup warning is logged).

## Routing record

**Span `route_message`** (every fresh message): `path`, `intent`, `certainty`,
`raw_choice`, `reports_food`, `needs_guidance_jev`, `offer_to_log`,
`judgment_ms`, `failure` (exception class name or `"not_configured"`, else
absent).

**`coaching_response.parsed_query["routing"]`** (coaching turns only; existing
JSONB column, no migration):

```json
{
  "path": "judgment",
  "certainty": 0.98,
  "raw_choice": "coaching",
  "reports_food": 0.97,
  "needs_guidance_jev": 0.94,
  "offer_to_log": true
}
```

Sits beside Gemini's `parsed_query["needs_guidance"]` (bool), so SC-010
agreement is one query or one pass over the feedback JSONL export. The key is
omitted when the judgment was unavailable (Story 5, scenario 4).

## Eval case (extended shape, `eval/cases/intent_routing.jsonl`)

| Field | Type | Notes |
|---|---|---|
| `text` | str | real user phrasing; must not equal any example embedded in the Jev questions |
| `expect` | `"log_meal"` \| `"coaching"` | expected handler |
| `category` | str | `bare_food`, `bare_food_nutrient_word`, `explicit_report`, `food_question`, `data_question`, `advice`, `non_english`, `smalltalk`, `mixed` |
| `expect_offer` | bool, optional | required on `mixed` (true) and on coaching cases used for the ≤ 5% false-offer check (false) |
| `note` | str | why the case exists |

Minimums (FR-011): ≥ 60 total; ≥ 15 `bare_food_nutrient_word`; ≥ 10
`food_question`; ≥ 5 `non_english`; ≥ 5 `smalltalk`; ≥ 8 `mixed`.
