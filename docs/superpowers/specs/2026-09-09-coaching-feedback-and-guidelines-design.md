# Coaching feedback loop and guideline retrieval — design

**Date:** 2026-09-09
**Status:** approved in chat, pending spec review
**Branch:** feat/coaching-telegram-estimation-deploy

## Goal

Two subsystems that together make coaching answers auditable and grounded:

1. **Feedback loop.** Every coaching reply is persisted server-side with the
   inputs that produced it. Users can rate a reply up or down from web chat.
   Rated replies export to JSONL as the seed for a coaching eval set.
2. **Guideline retrieval.** Advice-type questions are answered with retrieved
   passages from curated public dietary guidelines, filtered to the user's
   declared conditions, and cited inline.

Modelled on Omada Health's flywheel (protocol-grounded answers, human review,
up/down votes feeding annotation queues). This pass builds the collection and
grounding halves. Review tooling, Telegram buttons, hard safety constraints,
and fine-tuning are out of scope.

## Non-goals

- Human review UI or reviewer roles.
- Telegram inline buttons for rating.
- Deterministic safety constraints on replies (separate spec).
- Streaming or a general chat-message table.
- Automatic PDF parsing of guideline sources.

## Current state (verified)

- Coaching runs in `src/backend/agent/coaching.py` as a linear Pydantic AI
  pipeline: `parse_query` (Flash-Lite, structured `QueryParsed`) then
  `fetch_data` then `generate_response` (Flash, `instructions` slot carries
  system prompt plus per-user context). `CoachingAgent.handle(user_id,
  message)` returns a plain string.
- `orchestrator._handle_coaching` wraps it in `logfire.span("coaching")` and
  returns `{"status", "message", "paused": False, "items": []}`. No id.
- Frontend `mealStore.addMessage` mints a client-side uuid per message.
- `user_goal` has `dietary_prefs` JSONB but no conditions.
- pgvector tables use `Vector(768)` with IVFFlat cosine indexes.
  `backend.agent.llm.embed_text` embeds via Gemini.
- No feedback tables, routes, or components exist.

## Data model

One Alembic migration, revision `012`.

### `guideline_chunk`

| column | type | notes |
|---|---|---|
| id | uuid pk | |
| source_id | text | e.g. `dga-2020`, `ada-soc-2026-ch5` |
| source_title | text | human title shown in citations |
| source_url | text | |
| section | text | heading path, e.g. `Chapter 1 > Core elements` |
| condition | text | `general` or `diabetes`; more later |
| ordinal | int | order within source for stable citation numbering |
| text | text | chunk body |
| content_hash | text unique | sha256 of source_id + section + text |
| embedding | vector(768) | |
| created_at | timestamptz | |

Index: IVFFlat cosine on `embedding`, btree on `(condition)`, unique on
`content_hash`.

### `coaching_response`

| column | type | notes |
|---|---|---|
| id | uuid pk | returned to client as `response_id` |
| user_id | uuid | fk to auth user id, indexed |
| conversation_id | text nullable | thread id from the request |
| query | text | raw user message |
| parsed_query | jsonb | `QueryParsed.model_dump()` |
| retrieved_chunk_ids | uuid[] | empty when no retrieval |
| citations | jsonb | `[{"n": 1, "chunk_id": ..., "source_id": ..., "section": ...}]` |
| response_text | text | |
| model | text | `COACHING_MODEL` value |
| trace_id | text nullable | OTel trace id as 32-hex string |
| rating | text nullable | `up` or `down` |
| rating_comment | text nullable | max 500 chars |
| rated_at | timestamptz nullable | |
| created_at | timestamptz | indexed |

### `user_goal.conditions`

`text[]`, not null, server default `'{}'`. Allowed values enforced in the API
layer: `diabetes`, `prediabetes`, `hypertension`, `ckd`. Only `diabetes` and
`prediabetes` affect retrieval in this pass (both map to condition tag
`diabetes`); the others are stored for later.

## Guideline ingestion

### Source files

`docs/guidelines/<source_id>.md`. YAML frontmatter:

```yaml
source_id: dga-2020
title: Dietary Guidelines for Americans, 2020-2025
url: https://www.dietaryguidelines.gov/
condition: general
license: public domain (US government work)
```

Body is markdown. Every `##` or `###` heading starts a new chunk. Chunks longer
than roughly 400 tokens are split at paragraph boundaries with one-paragraph
overlap. Chunk `section` is the heading path joined with ` > `.

Initial seed, written by hand for this pass:

- `dga-2020.md` from Dietary Guidelines for Americans 2020-2025 (public
  domain). Core elements, nutrient-dense foods, limits on added sugar,
  saturated fat, sodium, alcohol, life-stage notes for adults.
- `who-healthy-diet.md` from the WHO healthy diet fact sheet (CC BY-NC-SA).
  Short.
- `ada-soc-nutrition.md` from ADA Standards of Care, nutrition therapy
  section. ADA text is copyrighted, so this file paraphrases the
  recommendations and quotes only short evidence-graded statements, with the
  section reference kept so a user can look it up.

### CLI

`python -m backend.guidelines.ingest [--dir docs/guidelines] [--dry-run]`

- Parses each file, chunks, hashes.
- Loads existing hashes for that `source_id`.
- Embeds only new hashes with `embed_text`, batched, and inserts.
- Deletes rows for that `source_id` whose hash is no longer present.
- Prints per-source counts: unchanged, added, removed.

Idempotent: a second run with no file changes makes no writes and no
embedding calls.

### Module layout

```
src/backend/guidelines/
  __init__.py
  chunking.py      # parse_markdown(path) -> list[Chunk]; pure, testable
  ingest.py        # CLI + upsert logic
  retrieval.py     # retrieve(query, conditions, k) -> list[RetrievedChunk]
  export_feedback.py
```

## Retrieval in the coach

### Parser change

Add to `QueryParsed`:

```python
needs_guidance: bool = False
```

The query-parse system prompt in `tunables.yaml` gains a rule: set
`needs_guidance` true when the user asks what they should eat, whether a food
or pattern is healthy or appropriate, how to change intake, or anything else
that calls for a recommendation rather than a readback of their own data.
Pure data questions ("how much protein today", "what did I eat yesterday")
stay false.

### Retrieval

`retrieval.retrieve(query, conditions, k=5)`:

- Maps user conditions to chunk condition tags (`diabetes`, `prediabetes` to
  `diabetes`). Always includes `general`.
- Embeds the query with the existing `_embed_query` pattern (runs
  `embed_text` in a thread).
- `SELECT ... WHERE condition = ANY(:tags) ORDER BY embedding <=> :q LIMIT k`.
- Returns `RetrievedChunk(id, source_id, source_title, section, text, score)`.
- On any error, logs a warning and returns `[]`. Retrieval failure must not
  fail the coaching turn.

### Prompting

When `needs_guidance` is true and chunks came back, `generate_response`
appends a block to the per-run context:

```
## Guideline passages
Cite with [n] where you rely on a passage. Do not cite passages you did not use.
[1] Dietary Guidelines for Americans 2020-2025 — Chapter 1 > Core elements
<text>
[2] ...
```

The coaching response system prompt in `tunables.yaml` gains: prefer
guideline passages over general knowledge when they apply; cite with bracketed
numbers; if no passage covers the question, answer from general knowledge
without inventing a citation; never present guideline content as medical
advice for the user's specific condition, and suggest a clinician for
medication or treatment questions.

### Citation mapping

After the model responds, `re.findall(r"\[(\d+)\]", text)` yields the numbers
used. Each valid number maps to its chunk and is stored in
`coaching_response.citations`. Numbers with no matching chunk are left in the
text and logged as a warning (this is a signal for the eval set). The
frontend renders `[n]` as-is; a hover or footnote list is a later UI pass.

### Pipeline output

`CoachingAgent.handle` returns a `CoachingResult` instead of `str`:

```python
class CoachingResult(BaseModel):
    message: str
    parsed: QueryParsed
    retrieved: list[RetrievedChunk]
    citations: list[Citation]
```

`_handle_coaching` writes the `coaching_response` row, adds
`"response_id": str(row.id)` to the returned dict, and keeps `message` so
Telegram and the frontend stay uniform. Telegram ignores `response_id`.

### Trace id

Inside the `coaching` span:

```python
ctx = trace.get_current_span().get_span_context()
trace_id = format(ctx.trace_id, "032x") if ctx.is_valid else None
```

## Feedback API

`src/backend/api/coaching_feedback.py`, router prefix `/coaching`.

`POST /coaching/{response_id}/feedback`

Request:

```python
class FeedbackRequest(BaseModel):
    rating: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=500)
    model_config = ConfigDict(extra="forbid")
```

- Auth via the existing Supabase dependency.
- 404 if the row does not exist or belongs to another user (same code for
  both, to avoid leaking ids).
- Overwrites any prior rating. Sets `rated_at = now()`.
- Returns `{"response_id", "rating"}`.
- Rate limit reuses the pattern in `api/meals.py`, 60/min.

## Frontend

- `ChatMessage` gains `responseId?: string`.
- `logToApi` passes `data.response_id` into `addMessage` when present.
- New `components/chat/feedback-buttons.tsx`: two icon buttons under an agent
  bubble, shown only when `responseId` is set. Up posts immediately. Down
  posts immediately and then reveals a one-line optional comment input with a
  Send action that posts again with the comment. State per message: idle,
  submitting, rated up, rated down. Rated state disables both buttons.
- New hook `hooks/use-coaching-feedback.ts` wrapping a TanStack mutation
  against `POST /coaching/{id}/feedback`. Errors surface via the existing
  toast.
- `ChatThread.tsx` renders `FeedbackButtons` after the markdown bubble in the
  `!isUser` branch.

## Settings: conditions

- `GET/PUT /goals` gain `conditions: list[str]` with the allowed values
  validated by a `Literal`.
- `SettingsPage.tsx` gains a "Health conditions" multi-select with the four
  values and a one-line note: "Used to choose which dietary guidelines the
  coach references. Mealsy does not give medical advice."

## Export for eval

`python -m backend.guidelines.export_feedback [--rated-only] [--since DATE]
--out eval/coaching_feedback.jsonl`

One JSON object per row:

```json
{"response_id", "created_at", "query", "parsed_query", "conditions",
 "retrieved": [{"source_id","section","text"}], "response_text",
 "citations", "rating", "rating_comment", "trace_id"}
```

`conditions` is joined from `user_goal` at export time. `user_id` is not
exported.

## Observability

- `coaching` span attributes: `needs_guidance`, `retrieved_count`,
  `citation_count`, `response_id`.
- Feedback route logs a `logfire.info` with `response_id`, `rating`, and the
  stored `trace_id` so a downvote can be opened in Logfire.

## Error handling

| failure | behaviour |
|---|---|
| Embedding call fails during retrieval | warn, no chunks, answer without citations |
| DB write of `coaching_response` fails | error logged, reply still returned, no `response_id` |
| Feedback on unknown or foreign id | 404 |
| Ingest file with missing frontmatter key | CLI exits non-zero naming the file, nothing written |
| Model emits `[7]` with no chunk 7 | left in text, warning logged, not stored as citation |

## Testing

Unit (pytest, no network):

- `chunking`: heading split, long-section split with overlap, section path,
  stable hash; frontmatter validation errors.
- `ingest`: with a fake session and fake embedder, second run performs zero
  inserts and zero embed calls; removed chunk is deleted.
- `retrieval`: condition mapping (`prediabetes` includes `diabetes` tag,
  always includes `general`); error path returns `[]`.
- `coaching`: parse mock returning `needs_guidance=True` triggers retrieval
  and adds the passage block; `False` does not; citation extraction maps
  valid numbers and drops invalid ones.
- `coaching_feedback` route: 401 unauthenticated, 404 foreign id, 200
  overwrite, comment length validation.
- `goals`: conditions round-trip and invalid value rejected.

Integration (existing test Postgres fixture):

- Insert three chunks (two general, one diabetes), retrieve as a user with no
  conditions and confirm the diabetes chunk is excluded; retrieve as
  `diabetes` and confirm it is eligible.

Frontend: component test for `FeedbackButtons` state transitions with a
mocked mutation.

Eval gate: unchanged. Coaching answer scoring is a later pass that consumes
the exported JSONL.

## Rollout

1. Migration and models.
2. Chunking, ingest CLI, seed three guideline files, run ingest against dev.
3. Retrieval module plus coaching pipeline changes behind the
   `needs_guidance` flag.
4. `coaching_response` persistence and `response_id` in the API.
5. Feedback route, frontend buttons, settings conditions.
6. Export CLI.

Each step is independently mergeable. Steps 1 and 2 ship no user-visible
change.
