# Implementation Plan: Patient Safety Profile and Constraint-Checked Meals

**Branch**: `user_memory` (worktree `~/nutrichat-user-memory`; one PR per phase into
`feat/android-app`, the production line) | **Date**: 2026-11-13 |
**Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/013-patient-safety-profile/spec.md`

## Summary

Turn the dark-launched preference memory (#61) into a patient profile with two
halves that live in one store per fact kind: an append-only **hard profile**
(allergy, diagnosis, medication, physical limitation, nutrient limit, diet
setting, food exclusion) with pending/confirmed/retired states and history, and
the existing **soft profile** (`user_memory`) for tastes and habits. Every meal
or recipe the coach proposes becomes a structured `Recipe`, is totalled from the
bundled USDA SQLite file (no model numbers, no LLM estimate fallback), and is
passed through a deterministic checker driven by clinician-editable YAML tables
before it can be shown; failures regenerate at most three times, then drop. A
regex red-flag screen runs before any model call and returns fixed responses
with a stored escalation and a webhook notice. Hard facts stated in chat are
saved as pending, read back, and bind only after a yes. A backend-only review
queue gives the team approve/reject/edit actions under a protected admin route.

Fastino GLiDE is an approved processor (FR-040, revised 2026-11-13). It keeps
routing, scores inferred hard facts (deterministic three-band thresholds decide
accept, ask or drop), and is the semantic layer of a Pydantic AI output
validator that guards every free-text coaching reply. A synthetic, labelled
inference set sets the thresholds.

## Technical Context

**Language/Version**: Python 3.13 (backend); Kotlin 2 / Jetpack Compose (Android, Phase 5 screen only)

**Primary Dependencies**: FastAPI, SQLAlchemy 2 async, Pydantic AI (structured recipe output, curator), LangGraph (meal card, unchanged), Celery, httpx (webhook), PyYAML (clinical tables). No new dependency.

**Storage**: Postgres 16 (Supabase): new tables `profile_entry`, `recommendation`, `check_failure`, `red_flag_escalation`, `review_item`; `user_memory` keeps soft facts. Bundled `src/backend/data/usda_fdc.sqlite3` for nutrient totals. Redis unchanged (coaching history only).

**Testing**: pytest (unit + DB tests on throwaway Postgres :5411), new offline checker eval (`eval/eval_safety_profile.py --offline`) in `scripts/prod-checks.sh`, live multi-session eval via `eval/gate.py --only safety_profile`.

**Target Platform**: Railway (web + worker), Android app (Pixel 9 / emulator for UI verification).

**Project Type**: mobile app + API.

**Performance Goals**: red-flag screen < 50 ms p99 (measured target < 1 ms, compiled regex); ordinary turns no slower than today (see Latency budget); recipe turns 90% < 12 s with up to 3 generations.

**Constraints**: GDPR approved processors only (FR-040); fail closed on profile load, red-flag list, food database; hard profile rendered in full, never truncated; Gemini monthly spend cap.

**Scale/Scope**: current user base (hundreds), hard profile bounded by `safety.hard_profile_max_entries` (40 live entries); eval set of 24 synthetic patients.

### Latency and cost budget (Constitution IV)

Per fresh text message, p50, measured values to be confirmed by research R1 before Phase 0 merges.

| Turn type | Today | After | Change |
|---|---|---|---|
| Any message: red-flag screen | none | 1 in-process regex pass (< 1 ms) | +< 1 ms |
| Routing | GLiDE (1 HTTPS call, ~250-360 ms), Gemini on low certainty | unchanged | 0 |
| Reply guardrail (coaching prose) | none | lexical + local USDA resolution every turn (< 25 ms); GLiDE judgment only when a food phrase is found and the patient has a food constraint (~250-450 ms); a violation costs one model rewrite | +< 25 ms typical; measure share and p95 of the GLiDE layer (R10) |
| Coaching, no meal suggestion | parse + response = 2 model calls | parse + response + concurrent hard-fact extraction = 3 calls, extraction overlapped with parse | latency ~0; tokens +~900 in / +~150 out per turn (extraction moved from Celery to the reply path, so net model calls per turn unchanged) |
| Coaching, meal suggestion | parse + response (free text) = 2 | parse + 1-3 structured recipe generations + local USDA lookups (SQLite, parallel, ~5-20 ms) + check (< 5 ms) + profile/recommendation writes (2 queries) | +1 to +2 model calls only when a check fails; budget 90% < 12 s |
| Meal logging | unchanged graph | unchanged; hard-fact extraction stays in Celery (as today) | 0 |
| Prompt tokens | profile block ≤ 350 tokens (flagged users) | hard block ≤ ~600 tokens for every user + soft block ≤ 350 tokens | +~250-600 tokens on coaching turns |

Hard-fact scoring by GLiDE runs in the background for logging turns and concurrently with `parse_query` on coaching turns, so it adds no sequential round trip.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | How the plan complies |
|---|---|---|
| I. Live product | Pass | All DB tests on throwaway DB; new user tables get RLS owner policies in their creating migration; nutrient totals from USDA only, unresolved = unknown (stricter than "flag as estimate"); copy plain, no emojis. Phase branches with migrations never point at prod DB. |
| II. Single source of truth | Pass with one justified copy | `user_goal.conditions` and `dietary_prefs` move into `profile_entry` and the columns are dropped one release later (expand/contract); goals API derives them on read. "Eaten" meals stay in `meal_log` (not copied into history). Recipe totals are computed on read from `recommendation.recipe` + USDA except the stored check snapshot, which is a deliberate immutable audit snapshot (Complexity Tracking). Clinical tables and red flags live once, in YAML. |
| III. Confirm before write | Pass | The principle governs `meal_log`, which is unchanged. For the profile: inferred hard facts bind without a yes only when they tighten a constraint and score in the accept band (owner decision Q4), are labelled "inferred" and mentioned once; uncertain ones are `pending` until a patient yes; a reply while a readback is outstanding is treated as the reply (same rule as the meal card). Retiring a confirmed entry needs a confirmation. Profile writes from the app carry `client_request_id`. No hard entry is ever deleted except on account deletion. |
| IV. Latency and cost | Pass | Table above. Red-flag notification and failure logging run in Celery or after the reply; USDA lookups are local and parallel; soft enrichment degrades gracefully; hard profile failure fails the turn by design (FR-007), which is the required behaviour, not an enrichment. Per-user growth bounded (entry cap, recommendation retention 180 days, escalations kept). |
| V. Measured agent changes | Pass | Routing unchanged; hard-fact thresholds set from the synthetic inference set (R18) with a held-out split; reply-guardrail threshold from its own cases; new `safety_profile` gate category with 24 synthetic patients; curator prompt change gated by `eval_memory_pipeline.py`; spans for screen, check, regenerate, readback. |
| VI. Gated production | Pass | One PR per phase, shipped through `/ship`; migration 019 is additive and applied before code; the column drop (020) ships one release after the code that stops reading them. Webhook URL in Railway variables, not in the repo. |

**Post-design re-check (after Phase 1 artifacts)**: still passes. The design added no datastore, framework or provider; the only copies are the two named in Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/013-patient-safety-profile/
├── plan.md              # This file
├── research.md          # Phase 0 output: decisions R1-R18
├── data-model.md        # Phase 1 output: tables, states, migrations
├── quickstart.md        # Phase 1 output: validation scenarios
├── contracts/
│   ├── profile-api.md       # patient-facing /profile endpoints
│   ├── review-api.md        # /admin/review endpoints
│   ├── clinical-tables.md   # YAML schemas: allergens, interactions, texture, red flags
│   ├── recipe-and-check.md  # Recipe structure, CheckResult, regenerate loop
│   └── webhook.md           # escalation notification payload
└── tasks.md             # /speckit-tasks output (not created here)
```

### Source Code (repository root)

```text
src/backend/
├── safety/                      # NEW package: deterministic, no model calls
│   ├── __init__.py
│   ├── tables.py                # load + validate clinical YAML, content-hash version, mtime reload
│   ├── red_flags.py             # screen(message) -> RedFlagMatch | None; fail-closed state
│   ├── profile.py               # hard profile: read, render block, state transitions, version hash
│   ├── recipe.py                # Recipe / Ingredient models; resolve_totals() via usda_local
│   ├── checker.py               # check(recipe, profile, today_intake) -> CheckResult
│   └── reply_guard.py           # lexical + USDA-resolution layers of the reply guardrail
├── agent/
│   ├── orchestrator.py          # red-flag screen before the GLiDE task; readback replies
│   ├── coaching.py              # suggestion path; output_validator reply guardrail (R10)
│   ├── suggest.py               # NEW: structured recipe generation + regenerate loop
│   ├── context.py               # hard block for every user; soft block; 3-week history
│   ├── memory.py                # soft facts only; restriction kind retired
│   ├── memory_tools.py          # hard facts via chat tools: pending add / pending retirement only
│   ├── memory_curator.py        # hard/soft extraction with evidence spans (Gemini)
│   ├── memory_judge.py          # per-type hard-fact questions; three-band select (R2)
│   └── reply_judge.py           # NEW: GLiDE "does this reply suggest X?" question
├── api/
│   ├── profile.py               # NEW: view, export, confirm/deny, retire, soft edit
│   ├── review.py                # NEW: /admin/review queue (reviewer allowlist)
│   ├── goals.py                 # conditions + diet settings read/written via safety.profile
│   └── account.py               # deletion covers new tables
├── auth/reviewer.py             # NEW: reviewer dependency (Supabase JWT + allowlist)
├── config/
│   ├── tunables.yaml            # safety: section
│   ├── prompts/                 # recipe_generation_system.md, profile_extraction_system.md, ...
│   └── clinical/                # NEW: allergen_groups.yaml, drug_food_interactions.yaml,
│                                #      texture_rules.yaml, physical_rules.yaml,
│                                #      condition_limits.yaml, red_flags.yaml
├── db/models.py · db/migrations/versions/2026111x_019_patient_safety_profile.py
│                               · 2026112x_020_drop_goal_condition_columns.py (later release)
└── workers/tasks.py             # notify_escalation (retrying), purge_old_recommendations

android/app/src/main/java/app/mealsy/android/ui/
└── profile/                     # NEW (Phase 5): "What Mealsy knows about me" + history
android/core/data/…/api/         # MealsyApi: /profile endpoints, DTOs

tests/
├── safety/                      # unit: tables, red_flags, checker, recipe totals, profile states
├── test_profile_api.py · test_review_api.py · test_migration_019.py
└── test_orchestrator_safety.py  # screen-before-model, readback reply handling, fail-closed

eval/
├── cases/safety_profile/        # 24 synthetic patients, multi-session scripts, expected profiles
├── cases/red_flags.jsonl        # phrases, marked paraphrases, ordinary messages
├── eval_safety_profile.py       # --offline (checker on fixture recipes) | live
├── eval_red_flags.py            # listed phrases, marked paraphrases, false-positive rate
├── eval_hard_fact_inference.py  # P/R per type and band, calibration, threshold sweep (R18)
├── gen_hard_fact_cases.py       # drafts synthetic cases from seeds for human review
├── cases/hard_fact_inference.jsonl · cases/reply_guard.jsonl
└── baseline_safety_profile.json
```

**Structure Decision**: Mobile + API, existing layout. All deterministic safety
logic goes in a new `backend/safety/` package with no imports from `agent/`, so
it can be unit-tested and eval'd offline and cannot call a model by accident.
The web frontend is untouched except where `goals` API shape changes would break
its tests (the response shape is kept, so none are expected).

## Delivery phases (one PR each)

Every PR ships its backend and its Android counterpart together, so the app
never lags the API (owner instruction 2026-11-13). Android work reuses the
existing chat (`ui/chat`), Settings (`ui/settings`) and `MealsyApi` /
`ChatRepository` code paths; new DTO fields are optional so released app
versions keep working.

| PR | Spec phase | Backend | Android | Gate before merge |
|---|---|---|---|---|
| 0 | prerequisite | Fastino DPA, privacy notice names Fastino; synthetic inference set generated and reviewed (R18) | privacy-policy link text names Fastino | owner sign-off |
| N | navigation (before PR 1) | none | **Separate Android PR (owner, 2026-11-13).** Bottom bar becomes Home, Journey, +, Profile: Trends renamed Journey; My meals leaves the bar and opens from an option on Home; chat leaves the bar and opens only from the + button; Settings becomes the **Profile** tab (`ui/profile/ProfileScreen`, mockup 2): name and email, Eating (Goals and targets, Food preferences), App (Reminders, Account and privacy), Sign out. Existing Settings content moves into these rows; nothing is dropped. No Explore tab and no Units row (issue #88) | AppNav tests and goldens updated; on-device check light + dark |
| 1 | Phase 1 | migration 019, `safety/profile.py`, backfill, hard block for every user, fail-closed profile load, goals API on profile, `POST /profile/entries` + retire, eval skeleton | Profile tab gains the **Care profile** card with coloured count chips per type (tapping it opens Care profile; the card is added by PR N below). **Care profile** screen (`ui/profile/CareProfileScreen`, mockup 1): header with last-updated date; "N of M limits on track today" banner; one expandable row per type (Allergies, Diagnoses, Medications, Physical limitations, Nutrient limits) with a count badge; nutrient limits expand to rows with the limit text ("Up to 1,500 mg a day", "50-60 g a day") and a today-so-far bar with a limit marker; add, edit and retire per entry (FR-020a). Settings conditions and diet chips keep working through `/goals`. Chat shows the retry message on a profile-load failure | migration test, backfill dry-run counts on a prod snapshot copy, restrictions gate; on-device check light + dark |
| 2 | Phase 2 | clinical tables, Recipe + totals, checker, suggestion loop, reply guardrail, failure log, recommendation record, offline eval in prod-checks | recipe reply rendered as a card (ingredients, steps, time, the constraint sentence) from the optional `recipe` field, plain text fallback; accept / not for me buttons call the feedback endpoint (`recommendation_id`) | offline checker eval: 0 violations; reply_guard cases: 0 missed; live safety_profile gate; on-device check |
| 3 | Phase 3 | red-flag screen, escalations, webhook task | fixed responses shown as a distinct safety message style (no feedback buttons); a waiting meal card stays intact | red_flags eval; screen p99 < 50 ms; on-device check |
| 4 | Phase 4 | typed candidates + evidence, GLiDE scoring, three-band decision, pending entries, readback + reply handling, pending retirement | readback rendered with Yes / No chips from the optional `readback` field (taps send the reply); "noted" mentions for accepted inferred facts link to the profile entry | inference eval on held-out split meets SC-004; SC-002; on-device check |
| 5 | Phase 5 | soft prefs dates + new kinds, 3-week history, rejection reasons, rest of `/profile` API, export | Care profile gains: "inferred" and "awaiting confirmation" labels with confirm / correct actions, entry history, a Preferences section (soft facts with dates, edit, delete), meal history and export | SC-010 on device (light + dark), SC-003 |
| 6 | Phase 6 | review queue + admin API | none (backend-only queue by decision Q1) | review API tests |
| 7 | contract step | migration 020 drops `user_goal.conditions`, `dietary_prefs` | none | released one version after PR 1 |

**Clinician placeholder (owner, 2026-11-13).** No clinician feature is
built. `GET /profile` returns `care_team: []` (always empty until a clinician
role exists), and both screens render the "Shared with …" line only when that
list is non-empty, so the mockup's line appears without further app work once
the role ships. In the backend, `source='clinician'` and the review queue
(Phase 6) are the only other placeholders.

**Code size.** Keep each module small and single-purpose: `safety/` functions
are pure and table-driven (adding an allergen or a drug is a YAML edit, not
code); one renderer turns a `CheckResult` into the reply sentence; Android
adds one card composable per new reply type and one profile screen, all styled
with the `:core:ui` tokens. No new abstraction until a second caller needs it.

## Complexity Tracking

| Item | Why needed | Simpler alternative rejected because |
|---|---|---|
| `recommendation.check_snapshot` stores the profile entry ids, table versions and computed totals at check time | FR-038 / SC-009: a shown recommendation must be traceable to the exact profile version and table content it passed, after both have changed | Recomputing on read gives today's answer, not the one the patient saw; tables and USDA data change. Immutable audit snapshot, named per Principle II. |
| Hard-fact extraction moves from Celery onto the coaching reply path (concurrent) | FR-020 same-session readback and US4-6 "ask before any meal is suggested" need the result before the reply is sent | Celery-only extraction lands after the reply, so a recipe in the same turn would ignore a just-stated allergy without asking. Net model calls per turn are unchanged (the Celery curator call is removed for coaching turns). |
| New `backend/safety/` package | The checker must be provably model-free and testable offline | Putting it in `agent/tools/` invites imports of model clients and mixes it with LLM tools. |
| `user_goal.conditions` / `dietary_prefs` kept for one release after the backfill | Constitution VI: migrations must stay compatible with code already running | Dropping in 019 breaks the running release during the deploy window. |
