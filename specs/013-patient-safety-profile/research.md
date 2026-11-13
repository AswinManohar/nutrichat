# Research: Patient Safety Profile and Constraint-Checked Meals

Decisions taken while planning, each with what was rejected. Items marked
**Owner** change something the spec states and need the owner's yes before the
phase that depends on them merges.

## R1. Routing stays on GLiDE (FR-040 revised 2026-11-13)

- **Decision**: no change to routing. Fastino is now an approved processor,
  so `system_one.judge_message` keeps routing every fresh text message, with
  the Gemini classifier as the low-certainty safety net. The red-flag screen
  runs before the GLiDE task is started.
- **Cost**: none; the logging-turn regression in the first draft of this plan
  is gone.
- **Prerequisite**: a data processing agreement with Fastino and the privacy
  notice update, before PR 1 ships (GLiDE then starts receiving health facts
  as candidates, R2).

## R2. Hard-fact inference: GLiDE scores, code decides

- **Decision**: the Gemini curator drafts typed candidates with the patient's
  exact words as `evidence` (which must be a substring of the patient's
  message, checked in code). GLiDE scores each candidate with a question per
  type (`states_own_allergy`, `takes_medication`, `has_diagnosis`,
  `has_physical_limitation`, `has_nutrient_limit`, plus `no_longer_true` for
  removals). `memory_judge.select_ops` grows into a three-band rule from
  tunables:
  - p ≥ `hard_accept_min_probability` **and** the fact adds a constraint:
    saved confirmed, source `inferred`, `confirmed_by='inference'`, with its
    probability; the coach mentions it once (owner decision Q4, 2026-11-13).
    "Adds a constraint" is decided in code: a new allergy, diagnosis,
    medication, physical limitation, food exclusion or diet setting, or a
    nutrient limit stricter than the current one for the same nutrient and
    period;
  - `hard_ask_min_probability` ≤ p < accept: saved pending, the coach asks;
  - p < ask: dropped.
  Removals and anything that loosens a constraint always ask, whatever the score.
- **Thresholds** are set from the synthetic eval (R17), not by feel.
- **Unjudged** candidates (GLiDE down): hard facts go to the ask band, never
  accepted on the curator's word.

## R3. One memory, two tables

- **Decision**: hard entries go in a new append-only `profile_entry` table;
  soft facts stay in `user_memory`. Each fact lives in exactly one row. The
  `restriction` kind in `user_memory` is migrated out and then disallowed by its
  check constraint.
- **Rationale**: hard entries need immutable rows, states, structured values
  (nutrient, amount, unit, period), replaced-by links and actors; soft facts need
  in-place edit and tombstones. Forcing both into one row shape would leave most
  columns null for one half and complicate the never-overwrite rule.
- **Alternatives rejected**: extend `user_memory` with nullable columns (mixes
  mutable and immutable rows under one write path, making FR-003 a convention
  rather than a constraint).

## R4. Hard entry types beyond FR-001 — Owner

- **Decision**: add two types to the five in FR-001: `diet_setting` (FR-014
  says diet settings are hard constraints and FR-006 says the profile is their
  single source) and `food_exclusion` (a named food or group the patient never
  eats, for example "no pork" or "no beef"). Migrated `restriction` facts that
  match an allergen group become `allergy`; the rest become `food_exclusion`.
- **Rationale**: existing restriction facts must migrate as confirmed hard
  entries (FR-006, US1-4); many are religious or ethical exclusions, not
  allergies, and labelling them allergies would be false.
- **Alternatives rejected**: map every restriction to `allergy` (wrong clinical
  meaning in the dietitian queue); keep them in `user_memory` (then a hard
  constraint lives outside the hard profile and escapes the checker).

## R5. Profile version

- **Decision**: the version is a SHA-256 over the sorted ids of confirmed
  entries plus their confirmation times, computed on read
  (`safety.profile.version_of`). Recommendations store the version and the
  entry ids (audit snapshot).
- **Alternatives rejected**: a counter column on `user_goal` (a second copy of
  what the entries already say, and must be bumped in every write path).

## R6. Structured recipe generation

- **Decision**: a Pydantic AI agent with `output_type=Recipe`
  (`contracts/recipe-and-check.md`), Flash-Lite, thinking off, own prompt
  `recipe_generation_system.md`. The hard profile block, conflict notes and
  previous failure reasons are in its instructions. The patient-facing text is
  rendered from the checked `Recipe` in code; the constraint sentence (FR-032)
  is built from the `CheckResult.applied` list, so it cannot claim a constraint
  that was not checked.
- **Trigger**: `QueryParsed` gains `suggests_meal: bool` ("what should I have
  for dinner", "give me a recipe", plan requests). The general coaching path is
  told not to name specific meals; the reply scan (R10) backs that up.
- **Alternatives rejected**: parse recipes out of free text (unreliable
  quantities, violates FR-008); a LangGraph subgraph (no pause is needed; a loop
  of at most three is plain code).

## R7. Nutrient totals for the checker

- **Decision**: resolve each ingredient with `usda_local.lookup` only, in a
  thread pool, in parallel. No live FDC call and no `estimate_nutrition_llm`
  fallback on this path. A match below `usda.match_confidence_floor`, or a food
  with no value for a limited nutrient, makes that nutrient `unknown`, and an
  unknown contribution fails that limit (FR-010, US2-7). Keys verified in the
  bundled file (FDC release 2026-04-30): `Sodium, Na`, `Potassium, K`,
  `Phosphorus, P`, `Carbohydrate, by difference`, `Water`,
  `Vitamin K (phylloquinone)`, protein in the `protein_g` column.
- **Quantities**: the recipe gives grams per ingredient (FR-008); a missing or
  non-positive quantity makes the recipe malformed.
- **Per-day limits**: today's intake from `meal_log` (ledger, nutrition-day
  boundaries) plus the recipe must stay within the limit. Logged items with an
  unknown value are counted as zero but noted in the check result; only the
  recipe's own unknowns fail the check.
- **Mass balance**: for a resolved food with no protein or carbohydrate value
  (olive oil has no protein key in some FDC rows), the missing macro counts as
  0 when the proximates USDA does give sum to at least
  `safety.mass_balance_min_g` (97 g per 100 g): the food is accounted for
  without it. Otherwise it stays unknown and fails a limit. Minerals and
  vitamin K are never inferred, and every inferred zero is recorded in the
  totals so the snapshot shows it.
- **Alternatives rejected**: live FDC API (flaky, see usda-api-flaky memory;
  adds network I/O); the LLM estimate (FR-010 forbids model numbers).

## R8. Allergen and interaction matching

- **Decision**: word-boundary, case-folded term match of each ingredient's
  name **and** its matched USDA description against the allergen group's
  `terms`, minus its `exclude_terms` (`nutmeg`, `butternut` for tree nuts;
  `cocoa butter` for dairy). Medication interactions match the confirmed
  medication's name against `drugs[].names` (generic and brand), then apply
  either `avoid_terms` or a nutrient ceiling per meal. Unmatched medications
  produce a "no known rule" note for the dietitian queue.
- **Rationale**: derived ingredients (peanut oil, whey, soy lecithin) are
  covered by listing them as terms; the table is reviewable by a dietitian.
- **Alternatives rejected**: embedding similarity (not deterministic, not
  auditable); model-judged allergen check (FR-009 bans model involvement).

## R9. Texture and physical demands

- **Decision**: recipes declare an IDDSI-style texture level (`liquid`,
  `puree`, `minced_moist`, `soft_bite_sized`, `regular`) and `crunchy_or_dry`.
  Limitations map to a maximum allowed level in `texture_rules.yaml`; a keyword
  list (nuts, crackers, raw carrot, toast) forces `crunchy_or_dry` regardless of
  what the model declared. Standing-time limits compare against
  `active_minutes`; grip limits block equipment listed in `physical_rules.yaml`
  (cast-iron pan, stand mixer, mandoline) and steps with demanding actions
  (`knead`, `grate`, `mince by hand`).

## R10. Reply guardrail (Pydantic AI output validator)

- **Decision**: register `@_response_agent.output_validator` on the coaching
  response agent. The validator runs on every free-text reply before it is
  returned and raises `ModelRetry("<reason>")` on a violation, so the model
  rewrites with the reason; `retries` caps it at `models.coaching_retries`
  (3, provisional until production traces), after which the reply is
  replaced with `safety.reply_guard_fallback_text` and a `check_failure` with
  outcome `reply_replaced` is logged. No new dependency: Pydantic AI 1.107
  provides both.
- **Layers, cheapest first** (all against the patient's confirmed entries):
  1. *Lexical* (deterministic, < 1 ms): word-boundary match of allergen-group,
     food-exclusion, diet-setting and interaction `avoid_terms` from the
     clinical tables.
  2. *Food resolution* (deterministic, ~5-20 ms): n-gram food phrases in the
     reply resolved through `usda_local.lookup`; matched USDA descriptions are
     run through layer 1. Catches "satay sauce" when only the description says
     peanut.
  3. *Semantic judgment* (GLiDE, ~250-450 ms, only when layers 1-2 find a
     food phrase but no violation and the patient has at least one allergy,
     exclusion or interaction): one question, "does this reply suggest the
     user eat something containing X?", with probability compared to
     `reply_guard_min_probability`. Also handles negation ("skip the
     peanuts" is not a suggestion), which layer 1 cannot.
- **Why not embedding similarity**: cosine distance between "peanut" and
  "almond" is small, so a threshold either misses derived ingredients or
  blocks unrelated nuts; it also cannot tell a suggestion from a warning. A
  typed GLiDE judgment answers the actual question with a calibrated
  probability, and the decision stays a threshold in code.
- **Recipes** keep the full deterministic checker (contracts/recipe-and-check.md);
  the guardrail is for prose replies only.
- **Cost**: layers 1-2 every coaching turn; layer 3 on a minority of turns.
  Measure the share and p95 on the eval before merge.

- **Memory tools** (`remember`, `forget`, `set_diet`): guarded inside the tool
  functions, not by a wrapper. A call that adds a hard fact creates a
  `pending` entry with a readback; a call that would remove or loosen a hard
  fact (forget an allergy, switch a diet setting off) creates a pending
  retirement instead and tells the model a confirmation is needed (FR-024,
  FR-037). Soft facts keep today's behaviour.
- **Pydantic AI Harness considered and rejected (2026-11-13)**: its
  `OutputGuardrail` / `ToolGuardrail` match this design, but every release
  with guardrails needs `pydantic-ai-slim` 2.x (0.68.0 pins `==2.68.0`), a
  major upgrade from 1.107. The owner chose to stay on 1.107. Everything this
  plan needs (`output_type`, `output_validator`, `ModelRetry`, `retries`,
  `toolsets`, `instructions`) is in 1.107. The guard functions are plain
  async callables, so moving to the harness later changes only how they are
  attached.

## R11. Red-flag screen

- **Decision**: `red_flags.yaml` with compiled case-insensitive regexes per
  rule, loaded at startup and reloaded when the file's mtime changes. Screened
  in `handle_message` before the routing task, the checkpoint read decision and
  any extraction, including while a meal card is paused (the card is left
  untouched). Load failure sets a fail-closed flag: every message gets the
  `service_unavailable` fixed text and no model is called until a load
  succeeds (FR-017).
- **Paraphrases**: the dietitians' marked paraphrases live in
  `eval/cases/red_flags.jsonl`; a rule ships only when it catches all of them.
- **Alternatives rejected**: model-based screening (FR-015 says before any
  model call); Aho-Corasick library (new dependency; regex is fast enough for a
  few hundred rules).

## R12. Notification channel and content — Owner

- **Decision**: Celery task `notify_escalation` POSTs to
  `SAFETY_WEBHOOK_URL` (Slack-compatible JSON) with retries (5 attempts,
  exponential backoff, first attempt within seconds, so the one-minute target
  holds on success). **The payload carries the escalation id, rule label,
  patient id and a link to the admin escalation endpoint, but not the message
  text.**
- **Rationale**: FR-016 asks for the message in the notification, but Slack
  (or any webhook host) is not on approved list A (FR-040). The reviewer reads
  the message through the admin API, which runs on the approved application
  host. If the owner adds the webhook host to the approved list, adding the text
  is a one-line change.
- **Unset URL**: escalation stored, `logfire.error` raised, screen still works
  (spec Decisions, Q3).

## R13. Readback and confirmation in chat

- **Decision**: on coaching turns the extractor runs concurrently with
  `parse_query`; new pending hard entries get `readback_asked_at` and the
  readback sentence is appended to the reply (templated from the entry, not
  model text). On a recipe turn with a new pending hard fact, the recipe is
  withheld and the reply asks for confirmation first. On logging turns
  extraction stays in Celery; the readback is asked at the start of the next
  coaching reply.
- **Reply handling**: a turn arriving while a readback is outstanding is
  first checked as its reply (Constitution III) with the existing
  deterministic `classify_intent` keywords: confirm → `confirmed`; reject →
  `retired` (never bound). A correction ("no, it's prawns not all shellfish")
  is a reject plus a new statement: the entry is retired and the extractor
  runs on the message, whose result is read back again. Any other message
  (an unrelated question) leaves the entry pending, is answered normally,
  and the readback is asked again before the next meal suggestion (US4-6). When both a meal card and a
  readback are waiting, the one asked last (card checkpoint time vs
  `readback_asked_at`) takes the reply and the coach names which one.
- **Alternatives rejected**: a LangGraph interrupt for readbacks (the coaching
  path has no graph; adding one for a yes/no is heavy); Redis-held pending state
  (Postgres is authoritative; the entry already carries its state).

## R14. Soft preferences, history and retrieval — Owner (minor)

- **Decision**: render the whole soft profile (already capped at 40 facts /
  1500 chars) instead of a vector search, and add `cuisine`, `budget`,
  `cooking_time` kinds plus a fact date. Meal feedback is stored on the
  `recommendation` row (status, reason), not as a fact. The three-week history
  is a bounded read: last 21 days of `recommendation` names/status and
  `meal_log` labels, de-duplicated, at most 30 lines.
- **Rationale**: the capped profile is smaller than a retrieval result would
  be, so "relevant" is a superset at zero added latency; it also removes an
  embedding call per turn. The spec assumption names semantic search; this
  satisfies FR-026's intent with less machinery. If the cap is ever raised,
  switch to retrieval then.

## R15. Clinical tables: editing and versioning

- **Decision**: YAML files in `src/backend/config/clinical/`, each with a
  `version` and `reviewed_by` / `reviewed_on` header; Pydantic validation at
  load; content hash stored with every check. The loader re-reads on mtime
  change, so an edited file takes effect on the next check without a code
  change (FR-013). In production an edit ships as a data-only release through
  `/ship`, keeping a reviewable history in git.
- **Alternatives rejected**: DB-backed tables with an admin editor (a UI to
  build and a second review trail); env-mounted volume (edits escape review).

## R16. Reviewer access

- **Decision**: `/admin/review/*` requires a valid Supabase JWT whose user id
  is in `REVIEWER_USER_IDS` (Railway variable). Every decision records that
  user id as the clinician actor. Only this router can write
  `source='clinician'` (FR-031); the check is a DB-level trigger as well as
  application code (see data-model).

## R17. Synthetic data for fact inference

- **Decision**: generate a labelled set (`eval/cases/hard_fact_inference.jsonl`),
  about 600 single messages and 40 multi-turn scripts, with Gemini drafting
  variations from hand-written seeds and every item reviewed before it is
  committed. Strata per type: clear first-person statements, hedged ("I think
  I might be lactose intolerant"), third person ("my sister is allergic"),
  past states, hypotheticals, questions, negations, corrections, and
  statements buried in meal logs. Each item: message, expected candidates
  (type, value) or none.
- **Report**: precision and recall per type and band, calibration (reliability
  curve, Brier score), and a threshold sweep that picks `hard_ask` and
  `hard_accept` to meet SC-004 (hard recall ≥ 95% counting the ask band,
  precision ≥ 90% in the accept band).
- A held-out split (20%) is never used for tuning; thresholds are reported on it.

## R18. Evals in CI

- **Decision**: the offline checker eval (fixture recipes × synthetic
  profiles, no model) runs in `scripts/prod-checks.sh` and must report 0
  violations and the expected rejections. The live multi-session eval
  (generation + extraction + readback) is a `gate.py` category run per phase
  PR, because it needs `GOOGLE_API_KEY` and spends against the cap. Repo CI
  today is only `android.yml`; the production checks are the CI gate.
