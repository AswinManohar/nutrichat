# USDA Retrieval Quality & Evaluation — Design Spec

**Date:** 2026-06-16
**Status:** Draft (pending user review)
**Scope:** Make LLM-food → USDA resolution measurable and more accurate. Four
pillars: (1) an eval harness, (2) a semantic relevance-judge / re-rank stage,
(3) split search-query from reasoning-context at extraction, (4) quantity
provenance. Addresses issue #5 (oatmeal→bread, berries→snack bars).

**Reference:** Uber Eats "Cart Assistant" architecture
(https://www.uber.com/us/en/blog/uber-cart-assistant/) — the same NL-food →
catalog problem. Lessons applied: decompose interpretation (LLM) from execution
(deterministic), a context-aware relevance rubric decoupled from quantity, an
eval layer combining deterministic checks + calibrated LLM-as-judge, and
quantity provenance tracking.

---

## 1. Current state (the gap)

Pipeline today (`usda.py`): LLM emits a colloquial `food_name` → it is sent
verbatim as the FDC search `query` → `_parse_fdc_response` takes **`foods[0]`**
(trusts USDA ranking, no re-rank) → `_confidence` = lexical word-coverage of the
query by the description → below `match_confidence_floor` falls back to an LLM
nutrition estimate.

Problems:
- **No evaluation exists.** `eval/` is empty; the `eval_harness.py` /
  `run_eval.py` / `test_set_200.jsonl` named in CLAUDE.md were never built. Every
  threshold/prompt change is unmeasured.
- **`_confidence` measures coverage, not correctness** — "rice" scores 1.0
  against "Rice pudding." It cannot distinguish good from wrong matches, so
  oatmeal→bread passes (#5).
- **No re-ranking** — we accept USDA's top hit even when a better candidate is
  in the result list.

## 2. Pillar 1 — Eval harness (prerequisite; build first)

**Dataset** `eval/test_set_200.jsonl` — one row per query:
```json
{"query": "oatmeal", "acceptable_fdc_ids": [173904, 173905],
 "acceptable_name_substrings": ["oat"], "category": "single_food"}
```
Mix of: single foods, multi-item meals, ambiguous ("salad"), branded vs generic,
preparation-sensitive ("tomatoes for stew"), and anonymized production edge cases.
Start ~50 hand-labeled, grow to 200.

**Runner** `eval/run_eval.py` (mirrors the CLAUDE.md command, which currently
no-ops): two layers, per Uber.
- **Deterministic checks:** top-1 match in `acceptable_fdc_ids` (or name-substring
  fallback), recall@k, MRR, false-fallback rate (USDA match existed but we
  dropped to estimate), schema validity, quantity correctness.
- **LLM-as-judge:** a calibrated judge prompt scores "is the resolved FDC item a
  correct match for the user's food, given context?" on a small rubric (correct /
  acceptable-variant / wrong). Reports agreement with deterministic labels so the
  judge itself stays calibrated.
- `--mock` runs offline against cached fixtures (no live FDC/LLM); live mode hits
  the real pipeline. Emits a metrics summary + per-row trace for regressions.

**Why first:** nothing below can be claimed as an improvement without this. It
also turns the coaching prompt's inline golden Q/A pairs into real regression
checks later.

## 3. Pillar 2 — Relevance-judge / re-rank stage

Stop trusting `foods[0]`. New step between fetch and parse:
- Request top-N (e.g. 5) FDC candidates (already available; `candidates` is
  partially wired for the swap UI).
- **Re-rank** by either (a) embedding cosine (query vs each description, reusing
  the existing Gemini embeddings + the pattern in `context.py`), or (b) a cheap
  LLM judge applying a **context-aware rubric** (direct match / variant /
  substitute / poor), given the food name + meal/preparation context (§4).
  Default: embeddings for cost/latency; LLM judge as an opt-in higher-accuracy
  tier measured against the harness.
- Keep relevance **decoupled** from quantity/units (Uber lesson) for
  debuggability. The chosen candidate then flows into the existing parse → cache
  → result path.
- The floor/fallback to LLM estimate remains, but now fires on the *best*
  candidate's score, not the top hit's.

This is the direct fix for #5; the harness measures whether it actually helps
before/after.

## 4. Pillar 3 — Split search-query from reasoning-context

Extend extraction (`extraction_system` prompt + `FoodEntity`): the LLM emits
- `food_name` — display name (current),
- `usda_query` — a concise, canonical search string for FDC (e.g.
  "oatmeal" → "oats cooked"; "gluten-free pasta" → "pasta"),
- `context` — short intent note used only by the relevance judge
  (e.g. "for lasagna; gluten-free is a strict constraint", "raw, for salad").

`_fetch_usda` searches with `usda_query`; the judge (§3) uses `context`. Mirrors
Uber's `search_terms` vs `item_context` split. Backward compatible: if `usda_query`
is absent, fall back to `food_name`.

## 5. Pillar 4 — Quantity provenance

Add `qty_source` to `FoodEntity`: `explicit_grams` | `unit_converted` |
`estimated`. The extractor sets it (we already special-case explicit grams). Used
to:
- skip second-guessing user-stated grams (already a rule; now structured),
- surface confidence honestly on the confirmation card,
- gate an arithmetic-validation check (especially the recipe importer, where
  ingredient→grams→servings math compounds).

Uber lesson: "12 eggs → one 12-count carton, not 12 cartons" — provenance changes
how downstream stages treat a number.

## 6. Guardrails-as-stages (smaller, opportunistic)

Per Uber, prefer early deterministic rejection over one late gate. Low-risk wins:
schema-validate structured LLM outputs at each node; validate the coaching data
bundle before generation rather than relying solely on the ~200-line
"never invent numbers" block. Tracked here, implemented incrementally — not a
blocker for pillars 1–4.

## 7. Sequencing
1. **Eval harness** (Pillar 1) — measurement first.
2. **Relevance re-rank** (Pillar 2) — measured against #1; fixes #5.
3. **Query/context split** (Pillar 3) — improves both search and judge.
4. **Quantity provenance** (Pillar 4) — independent; pairs with recipe importer.

Each gets its own implementation plan. Pillars 2–4 land only with before/after
eval numbers.

## 8. Testing
- Harness self-test: deterministic metrics on a tiny fixed fixture set;
  LLM-judge mocked in CI (`--mock`), live judge run manually.
- Re-rank: unit-test the ranker (given candidates + scores → correct pick);
  regression via the harness top-1 accuracy delta.
- Extraction: `usda_query`/`context`/`qty_source` populated and backward-compatible
  when absent.

## 9. Out of scope
Replacing FDC; building our own food DB; multi-turn clarification dialogs;
personalized ranking from user history (possible later, once the harness exists).

## 10. File map (indicative)
| File | Change |
|---|---|
| `eval/test_set_200.jsonl` | New — labeled queries |
| `eval/run_eval.py`, `eval/eval_harness.py` | New — deterministic + LLM-judge |
| `src/backend/agent/tools/usda.py` | Top-N fetch + re-rank stage |
| `src/backend/agent/tools/meals.py` | `FoodEntity.usda_query/context/qty_source` |
| `src/backend/config/prompts/extraction_system.md` | Emit new fields (post-refactor) |
| `src/backend/config/prompts/relevance_judge_system.md` | New judge prompt |
| `tests/test_usda_tools.py`, `tests/test_eval_harness.py` | Ranker + harness tests |
