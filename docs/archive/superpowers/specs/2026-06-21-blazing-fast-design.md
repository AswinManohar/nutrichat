# Design — "Blazing Fast" NutriChat (behavior-preserving latency work)

**Date:** 2026-06-21
**Branch:** `feat/coaching-telegram-estimation-deploy`
**Status:** Approved design — implementation plan to follow.

## Goal

Make the site and agent responses feel blazing fast — reduce both real
server-side latency and perceived front-end latency.

## Hard constraint — outputs the same

Every change in this spec MUST be behavior-preserving. Identical:

- Confirmation card content (items, flags, candidates, totals, footer)
- Logged numbers (`meal_log` rows, Redis daily totals)
- Reply text (extraction, correction, friendly log reply, coaching answers)
- Intent routing (log_meal vs coaching) and the confirm/correct/cancel branch
- Prompts, models, tunables

No streaming, no model swaps, no prompt restructuring. This is pure
latency/throughput work. The development lifecycle (SDLC) is unchanged: same
branch discipline, same eval-gated verification.

## Findings (current hot path)

A fresh text meal-log request runs:
`router → saved_lookup (DB) → extract (LLM) → auto_decompose (0–N LLM) →
usda_batch (HTTP + 0–N LLM estimate) → present`, then on resume
`intent_router → log (DB + Redis + LLM reply)`.

Latency sources, in impact order:

1. **Blocking LLM calls inside async nodes.** `extract_entities`,
   `apply_correction`, `classify_food_image` (`agent/tools/meals.py`) and
   `decompose_to_ingredients` (`agent/tools/decompose.py`) use synchronous
   `.invoke()`. They are awaited-into from `async` graph nodes but never yield
   the event loop, so the loop is frozen for the full model round-trip — every
   concurrent request serializes behind it.
2. **Graph recompiled per message.** `handle_message` calls
   `build_graph(checkpointer)` on every turn (`agent/orchestrator.py:113`).
3. **USDA cache lookup can't use an index.** `_cache_lookup` filters with
   `ILIKE '%name%'` (`agent/tools/usda.py:131`). The leading wildcard forces a
   sequential scan of `food_source`, which slows as the cache grows.
4. **Macro rings wait on the confirm-reply LLM.** On Confirm, `log_meal`
   awaits `_generate_log_reply` (`agent/tools/meals.py:491`) before the HTTP
   response returns; the dashboard can't update until that extra round-trip
   finishes — even though the exact totals are already on the confirmation card.

Already good (leave alone): coaching + USDA-estimate paths already use async
`pydantic-ai` `.run()`; the front-end already shows a `TypingIndicator` while
`isLoading`; DB engine is pooled and cached.

## Plan

### Phase 1 — Backend throughput (biggest lever)

1. **Async-ify the blocking LLM calls.** Convert the four functions above to
   `async def` using `.ainvoke()` and `await` them at their call sites
   (`extract_node`, `apply_correction_node`, `classify_node`, `decompose_node`,
   `auto_decompose_node`). Same model + prompt + input ⇒ identical output;
   removes the event-loop stall. `decompose_to_ingredients` is also called from
   any recipe-import path — update those call sites too.
2. **Compile the graph once.** Build it in the FastAPI `lifespan` startup
   alongside the checkpointer, store on `app.state.graph`, and have
   `handle_message` read it. (If a per-call signature is cleaner, memoize on the
   checkpointer identity instead — either way, compile once.)

### Phase 2 — USDA cache index

3. **Make the cache lookup index-able without changing match semantics.** Add an
   Alembic migration creating the `pg_trgm` extension (if absent) and a GIN
   trigram index on `food_source.food_name`
   (`USING gin (food_name gin_trgm_ops)`). The existing `ILIKE '%name%'` query
   is left untouched, so the *same* row is selected; Postgres can now use the
   trigram index for that pattern. The LLM-estimate lookup
   (`_estimate_cache_lookup`, exact match on normalized name) already benefits
   from a btree index — add one if missing.

### Phase 3 — Front-end perceived speed

4. **Optimistic macro-ring update on Confirm.** The confirmation card already
   carries the exact per-item and total macros. When the user confirms, update
   the `['dashboard','today']` query data optimistically from those card totals
   so the rings move immediately; the server response then reconciles to the
   authoritative value (identical). Front-end only — no output change, no new
   endpoint. Roll back the optimistic delta if the request errors.

### Phase 4 — Secondary (optional, do only if cheap)

5. Hoist the per-call `GoogleGenerativeAIEmbeddings` construction in
   `embed_text` (`agent/llm.py`) to module scope — background/history path.
6. Collapse the per-entity USDA cache lookups into a single round-trip **only**
   if per-entity match selection and ordering are provably preserved; otherwise
   skip.

## Explicitly out of scope (would risk outputs)

- The intent-classifier LLM hop and its routing.
- Changing or deferring the friendly confirm-reply *text* (it is an output;
  speeding it up needs streaming, which the chosen scope excludes — Phase 4
  optimistic update covers the perceived win instead).
- Model swaps, prompt restructuring, edge caching.

## Verification

The repo's eval harness (`eval/run_eval.py`) measures USDA resolution
accuracy (Recall@1) and false-fallback rate over `test_set_200.jsonl`. It does
not cover extraction, and the `--mock`/`--dataset` flags in CLAUDE.md are not
implemented — verification is defined against what actually exists:

- **Phase 1:** A small parity script runs `extract_entities` /
  `apply_correction` / `decompose_to_ingredients` over a fixed input list
  before and after, asserting identical structured output. Plus a concurrency
  micro-benchmark (N simultaneous `/meals/log` calls) showing the event loop no
  longer serializes.
- **Phase 2:** `python eval/run_eval.py` — identical accuracy and
  false-fallback numbers before/after. `EXPLAIN (ANALYZE)` on the cache query
  shows a bitmap/index scan instead of a seq scan, with the same row returned.
- **Phase 3:** Manual — rings jump on Confirm and settle to the same final
  value the server returns; an induced request error rolls the rings back.

## Risks

- Async conversion touching many call sites: mitigated by the parity script and
  by keeping function bodies otherwise identical.
- Trigram index: `pg_trgm` must be creatable on the managed Postgres (Supabase
  session-pooler) — confirm the extension is available before the migration.
