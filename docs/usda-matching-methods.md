# Matching food names to USDA rows: what we tried and what we learned

A user types "chicken" or "cup of rice" and the app must pick one row out of
13,694 in the bundled USDA FoodData Central (FDC) SQLite database. Get it
wrong silently and the user logs "Chicken, meatless" or "Candies, REESE'S
Peanut Butter Cups" at full confidence. This document walks through every
method we measured in September 2026, why each one behaved as it did, and
why the boring one won. It is written to be read start to finish.

Code: `src/backend/agent/tools/usda_local.py` (retrieval + ranking) and
`usda_match.py` (scoring primitives). Eval: `eval/cases/food_identity.jsonl`
(22 cases, used by `eval/gate.py`) and `eval/cases/food_identity_expanded.jsonl`
(176 cases, build notes in `EXPANDED_NOTES.md`).

## 1. The problem has two halves

Every method below is some combination of two separable steps:

1. **Retrieval** — from 13,694 rows, produce a short candidate pool
   (we use 25).
2. **Selection** — from the pool, pick one.

Keeping these apart is the single most useful idea in this document. When a
query fails, ask first: *was the right row ever in the pool?* If not, no
amount of cleverer scoring can help. If it was, retrieval is fine and the
problem is selection.

We measured the **pool ceiling** — the fraction of queries whose correct row
appears anywhere in the 25 candidates — at **97.7%** on the 176-case set
(99.4% after the answer key was repaired). Retrieval is essentially solved.
Every remaining error is a selection error, and that fact explains most of
the results below.

## 2. The measuring instrument, and how it misled us twice

**Metric:** recall@1 — did the top-ranked row land in the case's acceptance
list (a set of FDC ids and/or description substrings)?

The instrument had to be fixed three times before the comparison meant
anything. Each fix changed a conclusion.

| problem | effect | fix |
|---|---|---|
| Only 14–22 cases | one case = 4.5–7pp; adjacent RRF `k` values swung 13.6pp; sweeps were non-monotonic | build a 176-case set (0.57pp per case) |
| Raw substring matching | `"chicken breast"` did not match `"Chicken, breast, boneless, skinless, raw"` because of the comma; any method returning FDC's comma-inverted canonical form was penalised | punctuation-normalised substring (`gate._matches`); token-set containment was tried and rejected because it drops word order and accepts "Apple pie filling, raw" for "apple, raw" |
| Acceptance lists too narrow | `sourdough bread` → "Bread, sour dough" scored as a miss (FDC spells it as two words) | hand-adjudicated 237 rejected answers; 107 added |

**Lesson:** on 22 cases, hybrid fusion *beat* the lexical ranker (81.8% vs
77.3%). On 176 cases the same comparison reversed by 8pp. Neither number was
a lie; the small set simply could not resolve a difference that size. When
two methods differ by a few cases, you do not have a result — you have a
coin flip. Fix the instrument before tuning against it.

**A subtler lesson:** when we widened the acceptance lists, the candidate
answers we adjudicated included the LLM reranker's own picks. The reranker
then scored 98.9% against lists partly written from its answers. That number
is circular and was discarded. Any time a method helps write the answer key,
it cannot be scored on that key.

## 3. Method by method

All figures are recall@1 on the 176-case set unless stated. "Pre-repair"
means the acceptance lists as first generated; "repaired" means after
adjudication. Both are given where they differ because the gap is itself
informative.

### 3.1 BM25 alone — 61.4%

SQLite FTS5's built-in ranking over the description column. This is what
`_fts_candidates` uses to build the pool.

**Why it is bad at selection:** BM25 rewards a term being a large fraction of
a short document. For the query `rice`, "Rice crackers" (2 tokens) outscores
"Rice, white, long-grain, regular, enriched, cooked" (6 tokens). The signal
BM25 has — term frequency and document length — is the wrong signal for
"which of these rows is the plain food".

We also tried field-weighted BM25 (separate head/tail columns, head weighted
10×, Porter stemming). It changed nothing: for a bare noun, *every* candidate
matches in the head, so weighting the head cannot discriminate.

**Keep it for:** retrieval. It is a fine way to get 25 candidates.

### 3.2 Dense embeddings alone — 63.6% → 72.7% → 88.1%

Embed all 13,694 descriptions once with `gemini-embedding-001` (768 dims,
~$0.02, 8.5 minutes, rate-limited at 3,000 texts/min), embed the query at
request time, rank by cosine similarity. Brute-force matrix–vector product:
3 ms per query, no index needed at this scale.

The three numbers are the same method scored against the three versions of
the instrument. **Every time the answer key got fairer, embeddings looked
better**, ending tied with the lexical ranker. Embeddings tend to return
FDC's canonical comma-inverted rows, which the broken substring matcher
punished. Our repeated early conclusion that "embeddings don't help" was
mostly measuring our own answer key.

**Where they genuinely win:** morphology. `toast` → "Bread, potato, toasted".
The lexical tokenizer cannot relate `toast` to `toasted`, so every bread row
scores 0.0 lexically and "Shrimp toast" wins. Embeddings dissolve that.

**Where they genuinely lose:** near-duplicate discrimination. Every cheese
is roughly equidistant from "cheese", so cosine cannot prefer "Cheese, NFS"
over "Cheese, cheddar". And topical drift: `berries` → "Pie, berry",
`rice` → "Rice pilaf" / "Wine, rice". Cosine similarity measures *aboutness*,
and food logging needs *identity*.

**Dimension sweep:** 768/512/256/128 dims all scored within one case of each
other. 128-dim int8 vectors would be 1.8 MB. Storage is not the obstacle.

**The real cost:** the query must be embedded at request time — one API call
on the hot path of every meal log, reintroducing the network dependency the
SQLite cutover removed. A local ONNX model (~90 MB) would avoid that.

### 3.3 Hybrid fusion (RRF, weighted) — always worse than its best component

Reciprocal rank fusion, `score = Σ 1/(k + rank_i)` across rankers, and
weighted linear blends `α·lexical + (1−α)·vector`.

| fusion | 22 cases | 176 cases |
|---|---|---|
| BM25 ⊕ vector, RRF k=5 | 77.3% | 73.3% |
| lexical `_rank_key` ⊕ vector, RRF k=5 | 81.8% | 77.8% |

Fusion did exactly what the literature promises in one respect: BM25 (61%)
and vectors (73%) fused to 73–77%, beating both. But fusing vectors into the
*custom* ranker (88%) dragged it down by 8–10pp.

**Why:** RRF weights rankers equally. Fusing a weaker ranker into a stronger
one at equal weight is a regression by construction. Fusion helps when the
components have *complementary* strengths of *similar* quality. Here one
component already encoded domain structure the other could not learn.

This was the one finding that never reversed across all four versions of the
instrument. If you take one architectural conclusion from this document:
**fusion is not free; it averages, and averaging a good ranker with a
mediocre one gives you a mediocre-plus ranker.**

### 3.4 The lexical `_rank_key` ranker — 85.8% pre-repair, 88.1% repaired (shipped)

A six-level cascading sort. Python compares tuples left to right, so each
component is consulted only when everything before it tied:

```
(confidence, head_purity, description_coverage, generic_rank, -bm25_rank, -fdc_id)
```

| level | question it asks | example, query "white rice" |
|---|---|---|
| `_confidence` | what fraction of the *query's* words appear in the description? | 1.0 for "Rice, white, cooked", "Rice flour, white", "Beans and white rice" alike |
| `_head_purity` | does the query name this entry's *primary* food (text before the first comma)? | "Rice, white" head {rice} → 1.0; "Rice flour, white" head {rice, flour} → 0.5 |
| `_description_coverage` | what fraction of the *description's* words did the query explain? | prefers "Rice, white, cooked" over "Rice, white, long-grain, regular, enriched, cooked" |
| `_generic_rank` | are all modifiers FDC's "unspecified" markers (`NFS`, `raw`, `NS as to …`)? | "Cheese, NFS" beats "Cheese, fontina" |
| `-bm25_rank` | FTS relevance | rarely reached |
| `-fdc_id` | arbitrary but deterministic | should never decide anything important |

**Why it beats generic IR:** levels 2 and 4 encode how FDC *names* things —
the `HeadNoun, modifier, modifier` grammar and the NFS / "NS as to"
conventions for the unspecified form. Neither BM25 nor an embedding model
knows that "Cheese, NFS" is the canonical answer for "cheese". Structured
knowledge of the corpus beat better statistics over it.

**Its known weaknesses:**

- `_confidence` is degenerate for one-word queries: it can only be 1.0 or
  0.0. Every description containing the word ties, and the app's fallback
  gate (`match_confidence_floor: 0.6`) never fires. This is why
  `chicken` → "Chicken, meatless" ships at confidence 1.0.
- `_singularize` is crude: `toast`/`toasted`, `saute`/`sauteed` do not
  match, so preparation queries drop their qualifier (`sauteed spinach` →
  raw spinach).
- Quantity phrases leak into matching: `cup of rice` → "Candies, REESE'S
  Peanut Butter Cups". Arguably an extraction bug, not a ranking bug.

**The September fix** (59.1% → 77.3% on the 22-case set) had two parts, and
notably neither changed the scoring above:

1. `_head_match_supplement` — a *retrieval* fix. For a bare noun, bm25 never
   put "Rice, white, …, cooked" in the pool at all. Always add rows whose
   head noun equals the query, shortest first. No scoring change can fix a
   candidate that was never a candidate.
2. `_generic_rank` — a *selection* fix, inserted as the fourth tie-break so
   it only separates rows the first three already tied.

Diagnosing which half was broken *per query* (four were pool truncation,
three were arbitrary tie-break, one was morphology) is what made the fix
small.

### 3.5 LLM reranker — 84.1% always-on, ~88.6% gated

Show `gemini-3.1-flash-lite` the query and the 25 candidates, ask it to
output the number of the best one. Two configurations:

| strategy | recall@1 (pre-repair) | LLM calls / 176 |
|---|---|---|
| lexical ranker alone | 85.8% | 0 |
| **always call the LLM** | **84.1%** — worse than not calling it | 176 |
| **call only when `_confidence < 1.0`** | **88.6%** | 22 |

**Always-on was net negative.** It changed the answer on 111 of 176 queries,
helping 14 and hurting 17. Given a correct answer and 24 plausible
alternatives, the model keeps finding reasons to "improve" it. This is a
general property of LLM rerankers over already-good rankings: they add
variance everywhere, and variance on a correct answer can only hurt.

**Gating worked because of where the errors live.** The confidence
distribution of the lexical ranker's answers:

```
correct (n=151):  conf 0.5 → 7    0.7 → 3    1.0 → 141
wrong   (n=25):   conf 0.5 → 12              1.0 → 13
```

Queries with confidence below 1.0 are 12.5% of traffic but hold half the
failures — a 4× enrichment. Spend the LLM call there and it is net positive;
spend it everywhere and it is net negative. The general principle: **an
expensive judge should be invoked by an uncertainty signal, not by default.**

**Three reasons it was not shipped:**

1. *The gain is unproven.* The gate threshold was chosen after looking at
   the same 176 cases it was scored on, and the "repaired" 98.9% was
   circular (§2). The honest estimate from hand-grouping its wins was
   ~11 real improvements, i.e. roughly +6pp — plausible, not demonstrated.
2. *The gate is blind to the worst failures.* 13 of the 25 misses are wrong
   **at confidence 1.0** — the "Chicken, meatless" class. Those never
   trigger the gate. The reranker's ceiling was therefore about half the
   remaining error.
3. *It is a second serial LLM call on the hot path.* Extraction is already a
   Gemini call; the confirmation card cannot render until the slowest
   entity resolves. ~150 ms on one lookup in eight, plus a network
   dependency and non-deterministic eval scores, for an unproven gain.

Cost in dollars was never the objection; it is fractions of a cent. Latency,
reliability, and evaluability were.

**What reading its "mistakes" taught us:** several of the reranker's
supposed regressions were it reaching for FDC's *other* generic marker —
`lamb` → "Lamb, NS as to cut", `corn` → "Corn, NS as to form" — which
`_generic_rank` did not recognise. That is now in the code, though it turns
out to be unreachable in practice: the marker's own words (`ns`, `as`,
`cut`) inflate the row's token count and it loses at `_description_coverage`
one level before `_generic_rank` is consulted. The function's docstring
documents this measured caveat rather than implying it does something. A
reranker is a useful *diagnostic* even when it is not a useful component.

### 3.6 TypeSafe `Choice` — analysed, not measured

A typed-judgment model that returns a selected option plus a probability
distribution over all options. Pointwise use (one judgment per candidate)
is a poor fit — it never sees the alternatives, and our whole difficulty is
discriminating near-identical rows. Listwise `Choice` (all 25 in one call)
is the right shape.

Its interesting property is not the pick but the **distribution**: a flat
distribution over "Cheese, NFS" / "Cheese, fontina" / … is exactly the
"this query is ambiguous" signal that `_confidence` structurally cannot
produce for one-word queries. If it were adopted, it would more plausibly
replace the *confidence gate* than the ranker. Unmeasured; requires the 26
adjudicated rows from §2 to be settled first so it is not scored against a
key written from a competitor's answers.

## 4. Summary table

| method | recall@1, 176 cases | per-lookup cost | latency | offline | deterministic |
|---|---|---|---|---|---|
| BM25 alone | 61.4% | 0 | ~4 ms | yes | yes |
| embeddings alone | 88.1% (repaired) | 1 embed call | ~50–200 ms | no | yes |
| BM25 ⊕ vector RRF | 73.3% | 1 embed call | ~50–200 ms | no | yes |
| lexical ⊕ vector RRF | 77.8% | 1 embed call | ~50–200 ms | no | yes |
| **lexical `_rank_key`** | **88.1%** | **0** | **~4 ms** | **yes** | **yes** |
| LLM rerank, always-on | 84.1% (pre-repair) | 1 LLM call | +150 ms | no | no |
| LLM rerank, gated | ~88.6% (pre-repair, fitted) | 0.125 LLM calls | +150 ms × ⅛ | degrades | no |
| pool ceiling | 97.7–99.4% | — | — | — | — |

Decision (2026-09-24): ship `_rank_key`. Same accuracy as the best
alternative, at zero marginal cost and no new failure modes.

## 5. What we would do next, in order of value per effort

1. **Demote "meatless" when the query names a meat.** One deterministic
   rule; directly targets the confidence-1.0 misses that no gate can reach.
2. **Strip quantity words before lookup** (`cup of`, `slice of`, `bowl of`).
   Six of eighteen quantity-phrase cases fail; this belongs in extraction.
3. **Better stemming in `_tokenize`** so `toast`↔`toasted`,
   `saute`↔`sauteed`. Fixes the preparation category (24/33) and the
   morphology class embeddings currently win on. Must be re-measured — it
   changes the input to all three top-level scores.
4. Only then revisit an LLM or `Choice`-based judge, with a holdout split
   and a user-adjudicated answer key.

## 6. Transferable lessons

- **Separate retrieval from selection, and measure the pool ceiling first.**
  It tells you which half to work on and bounds every method's possible gain.
- **A ranker that knows the corpus's naming grammar beats generic IR.**
  FDC's `Head, modifier` structure and NFS convention were worth more than
  768 dimensions of semantics.
- **Fusion averages.** It helps only when components are of similar quality
  with complementary errors.
- **LLM judges must be gated by uncertainty.** Always-on reranking of an
  already-good ranking was net negative.
- **Coverage-style confidence is degenerate on short queries.** A one-word
  query cannot produce a low score, so the fallback it is supposed to
  trigger never fires. Confidence needs an *ambiguity* signal (how many
  candidates tied, whether the winner is generic), not just a coverage ratio.
- **The eval is the bottleneck, not the ideas.** Three separate improvements
  were blocked by a 22-case set and narrow acceptance lists. Two conclusions
  reversed when the instrument was fixed. Never let a method under test help
  write the answer key it is scored on.
