# Data Model: Jev → GLiDE

**Spec**: [spec.md](spec.md) · **Research**: [research.md](research.md)

No tables, columns or migrations. One in-memory model gains two fields, one
JSONB value gains a key, and one configuration block is renamed.

## RoutingJudgment (in-memory, Pydantic, `extra="forbid"`)

Unchanged fields keep the rules in
[001 data-model](../001-jev-intent-routing/data-model.md).

| Field | Type | Change |
|---|---|---|
| `intent`, `certainty`, `raw_choice`, `reports_food`, `needs_guidance`, `latency_ms` | as today | none |
| `model` | str | new: the `model` echoed by the response (`"glide"`) |
| `input_tokens` | int ≥ 0 | new: `usage.input_tokens`, for cost per 1,000 messages |

`None` still means "unavailable". Reasons returned beside it:
`not_configured`, `malformed_response`, `timeout`, or `http_<status>`
(for example `http_425`, `http_402`). Never the response body.

## Routing record (`coaching_turn.routing`, JSONB) and Logfire span

| Key | Change |
|---|---|
| `path`, `certainty`, `raw_choice`, `reports_food`, `needs_guidance_jev`, `offer_to_log` | kept, including the `_jev` name (research R6) |
| `judge_model` | new: `"glide"`; absent on records written before the move |
| `judgment_input_tokens` | new, span only |

## Configuration (`config/tunables.yaml`)

The `typesafe:` block becomes `glide:`; `TypeSafeConfig` becomes `GlideConfig`.

| Key | Value | Note |
|---|---|---|
| `base_url` | `https://api.fastino.ai` | new |
| `model` | `fastino/GLiDE` | was `jev-latest` |
| `intent_min_probability` | re-derived | was 0.75 for Jev |
| `log_offer_min_probability` | re-derived | was 0.7 for Jev |
| `log_offer_text` | unchanged | |
| `request_timeout_s` | 0.8 | unchanged; reply path |
| `warm_up_timeout_s` | 90 | new; covers a `425` warm-up at startup |

## Environment

| Variable | Change |
|---|---|
| `FASTINO_API_KEY` | new; web and bot services, local `.env` |
| `TYPESAFE_API_KEY` | removed after cutover is verified |
