---
description: "Task list for spec 013, patient safety profile and constraint-checked meals"
---

# Tasks: Patient Safety Profile and Constraint-Checked Meals

**Input**: `specs/013-patient-safety-profile/` (plan.md, spec.md, research.md,
data-model.md, contracts/, quickstart.md)

**Branch**: `user_memory` (worktree `~/nutrichat-user-memory`). One PR per
phase into `feat/android-app`. Commit after each task, push the branch.

**Tests**: included. CLAUDE.md requires a test for every new behaviour and
every bug fix. DB tests run against a throwaway Postgres on :5411
(quickstart.md, Prerequisites), never the production `DATABASE_URL`.

**Rules for every task**: `from __future__ import annotations`, type hints,
Google docstrings, Pydantic models with `extra="forbid"` at boundaries,
tunables in `src/backend/config/tunables.yaml`, prompts in
`src/backend/config/prompts/`, no new dependency, Ruff on touched files only.
Android: `MealsyColors` / `MealsyType` / `MealsyShapes` tokens, requests only
through `MealsyApi`, new DTO fields optional, on-device check in light and dark
theme. Keep modules small; no abstraction without a second caller.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an open task)
- **[Story]**: US1-US6 from spec.md

## Path conventions

- Backend: `src/backend/…`, tests in `tests/…`, evals in `eval/…`
- Android app: `android/app/src/main/java/app/mealsy/android/…`
- Android data layer: `android/core/data/src/main/kotlin/app/mealsy/data/…`
- Strings: `android/app/src/main/res/values/strings.xml`

---

## Phase 1: Setup (PR 0, no production code)

**Purpose**: owner prerequisites, the clinical data skeleton and the
synthetic inference set that later phases are measured against.

- [ ] T001 Record the Fastino data processing agreement status and the privacy-notice wording naming Fastino as a processor in `specs/013-patient-safety-profile/research.md` R1 (owner supplies the facts; PR 1 must not merge until both are done)
- [ ] T002 [P] Create `src/backend/config/clinical/` with the six YAML files from `contracts/clinical-tables.md` (`allergen_groups.yaml`, `drug_food_interactions.yaml`, `texture_rules.yaml`, `physical_rules.yaml`, `condition_limits.yaml`, `red_flags.yaml`), each with the `version`, `reviewed_by`, `reviewed_on` header, the example content from the contract, and `reviewed_by: "PENDING DIETITIAN REVIEW"` where values are placeholders
- [ ] T003 [P] Write `eval/cases/hard_fact_seeds.jsonl`: at least 10 hand-written seed messages per hard type (allergy, diagnosis, medication, physical_limitation, nutrient_limit) per stratum (clear first person, hedged, third person, past state, hypothetical, question, negation, correction, buried in a meal log), each `{message, expected: [{type, value}] | [], stratum}`
- [ ] T004 Write `eval/gen_hard_fact_cases.py`: reads seeds, asks Gemini (`FLASH_LITE_MODEL`) for 5 paraphrases per seed keeping the label, writes `eval/cases/hard_fact_inference.draft.jsonl` with a deterministic 80/20 `split` field (`tune` / `holdout`, hash of the seed id); never overwrites the reviewed file
- [ ] T005 Generate the draft, review every item by hand, and commit the reviewed set as `eval/cases/hard_fact_inference.jsonl` (target about 600 messages) plus `eval/cases/hard_fact_scripts.jsonl` (40 multi-turn scripts with expected profiles after each session)
- [ ] T006 [P] Write `eval/cases/reply_guard.jsonl`: coaching replies with a patient's confirmed entries and the expected verdict, covering direct allergen names, derived ingredients ("peanut oil", "whey"), dish names ("satay", "pesto"), warnings that must pass ("skip the peanuts"), food exclusions, diet settings and medication `avoid_terms`
- [ ] T007 [P] Write `eval/cases/red_flags.jsonl`: every phrase per rule in `red_flags.yaml`, the paraphrases the dietitians mark as expected matches, and at least 300 ordinary messages drawn from `eval/cases/intent_routing.jsonl` and `eval/test_set_200.jsonl` as negatives

**Checkpoint**: owner sign-off on T001; datasets committed.

---

## Phase 2: Navigation shell (PR N, Android only, separate PR before PR 1)

**Purpose**: owner decision 2026-11-13. Bottom bar becomes Home, Journey, +,
Profile. No Explore tab, no Units row (issue #88).

- [ ] T008 Rename the Trends tab to Journey: label `nav_journey` ("Journey") in `strings.xml`, `ROUTE_TRENDS` kept as the route value to avoid breaking deep links, `bottomNavItems` call and KDoc in `android/app/src/main/java/app/mealsy/android/ui/AppNav.kt`
- [ ] T009 Remove My meals and Chat from the bottom bar in `ui/AppNav.kt` (`MealsyBottomBar`, `bottomNavItems`, `tabRoute()`); chat stays reachable only through the FAB quick-log route; update `tabRoute()` so `ROUTE_CHAT_PATTERN` and `ROUTE_MY_MEALS` no longer map to a tab
- [ ] T010 Add a "My meals" option to Home that navigates to `ROUTE_MY_MEALS` in `android/app/src/main/java/app/mealsy/android/ui/home/` (place it with the existing Home sections, `MealsyType`/`MealsyShapes` tokens, string `home_my_meals`)
- [ ] T011 Create `android/app/src/main/java/app/mealsy/android/ui/profile/ProfileScreen.kt` and `ProfileViewModel.kt` per mockup 2: header (initials avatar, name, email), Eating section (Goals and targets row showing the kcal goal, Food preferences row showing the active diet setting), App section (Reminders row with the count on, Account and privacy row), Sign out button; reuse the state and actions of `ui/settings/SettingsViewModel.kt`
- [ ] T012 Move the remaining Settings content into sub-screens opened from the Profile rows (Goals and targets, Food preferences, Reminders, Account and privacy) by extracting the existing sections of `ui/settings/SettingsScreen.kt`; delete what becomes unused so nothing is duplicated
- [ ] T013 Register `ROUTE_PROFILE` as a tab in `ui/AppNav.kt` (`bottomNavItems`, `tabRoute()`), replace navigations to `ROUTE_SETTINGS` with it, and remove `ROUTE_SETTINGS`
- [ ] T014 Update `android/app/src/test/java/app/mealsy/android/ui/AppNavViewModelTest.kt` and `AppShellGoldenTest.kt` goldens for the new bar; add a golden for ProfileScreen in light and dark
- [ ] T015 On the Pixel 9: install, check Home → My meals, + → chat, Journey, Profile rows in light and dark theme; note results in the PR

**Checkpoint**: PR N merged. The Profile tab exists, and the US1 Care profile card plugs into it.

---

## Phase 3: Foundational (blocking prerequisites, part of PR 1)

**Purpose**: schema, tunables and the deterministic `safety` package skeleton that every story uses.

- [ ] T016 Add a `safety:` section to `src/backend/config/tunables.yaml` and its Pydantic model in `src/backend/config/__init__.py`: `hard_profile_max_entries: 40`, `max_recipe_attempts: 3`, `recommendation_retention_days: 180`, `reply_guard_min_probability`, `reply_guard_fallback_text`, `profile_unavailable_text`, `no_suitable_meal_text`, `food_db_unavailable_text`, `clinical_dir: "config/clinical"`, each with a comment saying where it is used
- [ ] T017 Write migration `src/backend/db/migrations/versions/2026111x_019_patient_safety_profile.py` (revision `019_patient_safety_profile`, down_revision `018_user_memory_profile`) creating `profile_entry`, `recommendation`, `check_failure`, `red_flag_escalation`, `review_item` exactly as in `data-model.md`: FKs to `user_goal.user_id` `ON DELETE CASCADE`, CHECKs on `entry_type` (`allergy`, `diagnosis`, `medication`, `physical_limitation`, `nutrient_limit`, `diet_setting`, `food_exclusion`), `source` (`patient`, `clinician`, `inferred`), `state` (`pending`, `confirmed`, `retired`), "`state <> 'confirmed' OR confirmed_at IS NOT NULL`", "`state <> 'retired' OR retired_at IS NOT NULL`", "`source <> 'clinician' OR created_by LIKE 'reviewer:%'`"; trigger `profile_entry_immutable`; indexes `ix_profile_entry_live (user_id) WHERE state <> 'retired'`, `ix_profile_entry_review (state, created_at) WHERE state = 'pending'`, unique `(user_id, client_request_id) WHERE client_request_id IS NOT NULL`, `recommendation (user_id, created_at desc)`, unique `review_item (kind, subject_id)`; owner RLS policy on every new table; add `user_memory.created_at timestamptz not null default now()`
- [ ] T018 In the same migration, the idempotent backfill from `data-model.md` steps 1-4 (conditions → `diagnosis`; true `DIET_CHIPS` keys → `diet_setting`, other keys logged; live `restriction` facts → `allergy` when an allergen term matches else `food_exclusion`, then delete the `user_memory` row; replace `ck_user_memory_category` with `('dislike', 'like', 'habit', 'context', 'cuisine', 'budget', 'cooking_time', 'preference')`), and the downgrade that restores restriction rows from `created_by='backfill'` entries
- [ ] T019 Add ORM classes `ProfileEntry`, `Recommendation`, `CheckFailure`, `RedFlagEscalation`, `ReviewItem` and `UserMemory.created_at` to `src/backend/db/models.py`, mirroring T017 constraints in `__table_args__`
- [ ] T020 [P] Test migration 019 up, backfill and down on the throwaway DB in `tests/test_migration_019.py` (seed conditions, diet chips, an allergy and a non-allergy restriction, a tombstone; assert entries, deleted rows, constraint rejections, immutability trigger, clean downgrade)
- [ ] T021 [P] Create `src/backend/safety/__init__.py` and `src/backend/safety/tables.py`: Pydantic models for each clinical file (`extra="forbid"`), `load_tables() -> ClinicalTables` with SHA-256 content hash per file, mtime-based reload, `TablesUnavailable` exception on missing or invalid files; no import from `backend.agent`
- [ ] T022 [P] Test `safety/tables.py` in `tests/safety/test_tables.py`: valid load, hash changes on edit, reload on mtime change, invalid YAML raises `TablesUnavailable`
- [ ] T023 Add an import-boundary test in `tests/safety/test_boundaries.py` asserting no module under `backend/safety/` imports `backend.agent`, `pydantic_ai`, `google` or `httpx`
- [ ] T024 Add the new tables to account deletion in `src/backend/api/account.py` (explicit deletes like the existing tables, or a comment confirming cascade) and extend `tests/test_account_delete.py` to assert no rows remain in the five tables (FR-040b)

**Checkpoint**: migration and safety skeleton in place; user stories can start.

---

## Phase 4: User Story 1 - Confirmed profile shapes every meal, every session (P1) MVP

**Goal**: one typed hard profile per patient, with history, present in full on every coaching and recipe turn; patients edit it from the Care profile screen.

**Independent test**: create one entry of each type, start a new session, ask for a meal: every confirmed entry is in the prompt and named in the reply; pending ones are not applied; a load failure gives the retry message (quickstart PR 1).

### Tests for US1

- [ ] T025 [P] [US1] Unit tests for state transitions, version hash and rendering in `tests/safety/test_profile.py` (pending does not bind, edit = retire + new with `replaces_id`, retired is final, version changes on confirm/retire, block too long raises)
- [ ] T026 [P] [US1] API tests for `/profile`, `/profile/history`, `/profile/limits/today`, `POST /profile/entries`, confirm, deny, retire in `tests/test_profile_api.py` per `contracts/profile-api.md` (409/422/403 cases, `client_request_id` idempotency, `source: clinician` rejected, `care_team` is `[]`)
- [ ] T027 [P] [US1] Extend `tests/test_goals_api.py`: `GET/PUT /goals` keep `conditions` and `dietary_prefs` shapes, reading and writing through profile entries
- [ ] T028 [P] [US1] Extend `tests/test_context.py` and `tests/test_coaching.py`: hard block present for every user (not only profile-flag users), pending entries rendered as awaiting confirmation, coaching turn fails with `profile_unavailable_text` when the profile cannot load (FR-007)

### Implementation for US1

- [ ] T029 [US1] Implement `src/backend/safety/profile.py`: `EntryValue` models per type from `data-model.md` (nutrient_limit: "`amount: float > 0` (the ceiling); `min_amount: float | None`"; `unit` in `mg`, `g`, `ml`; `period` in `per_meal`, `per_day`; food_exclusion "`terms: list[str]` (1-10 words or phrases)"; label "≤ 200 chars"), `load_hard_profile(user_id)`, `version_of(entries)`, `add_entry`, `confirm`, `deny`, `request_retirement`, `retire`, `replace` (one transaction), `render_block(entries) -> str` raising `ProfileTooLarge` above `safety.hard_profile_max_entries`
- [ ] T030 [US1] Implement today's limit progress in `src/backend/safety/limits.py`: `limits_today(user_id)` derived from `meal_log` with nutrition-day boundaries (`core/nutrition_day.py`), per-day sums, per-meal maximum, `unknown_items` count; nothing stored
- [ ] T031 [US1] Create `src/backend/api/profile.py` with `GET /profile` (incl. `care_team: []` placeholder), `GET /profile/history`, `GET /profile/limits/today`, `POST /profile/entries`, `POST /profile/entries/{id}/confirm|deny|retire` per `contracts/profile-api.md`; register the router in `src/backend/main.py`
- [ ] T032 [US1] Route `GET/PUT /goals` conditions and diet settings through `safety.profile` in `src/backend/api/goals.py` (diffs become confirmed patient entries or retirements; response derived from the profile)
- [ ] T033 [US1] Render the hard block for every user in `src/backend/agent/context.py` (`build_context`, `load_restrictions`, `_restriction_blocks`): replace the `user_goal.conditions` / `dietary_prefs` / restriction-fact lines with `safety.profile.render_block`; keep soft facts behind `memory.profile_enabled`
- [ ] T034 [US1] Make the coaching turn fail closed in `src/backend/agent/coaching.py` `_context_prompt`: a hard-profile load failure raises `RestrictionsUnavailableError` and the orchestrator replies `safety.profile_unavailable_text`; `_user_conditions` reads diagnoses from the profile
- [ ] T035 [US1] Remove the `restriction` kind from `src/backend/agent/memory.py` (`FactKind`, `_KIND_ORDER`, headings, curator never-loosen rules that only applied to restrictions) and from `src/backend/agent/memory_tools.py`; hard facts from the coach's tools go through `safety.profile` as pending adds or pending retirements (research R10, memory tools)
- [ ] T036 [P] [US1] Add `ProfileDto`, `HardEntryDto`, `LimitProgressDto`, `CareTeamMemberDto` and the `/profile` endpoints to `android/core/data/src/main/kotlin/app/mealsy/data/api/Dtos.kt` and `MealsyApi.kt`, plus `ProfileRepository` in `android/core/data/src/main/kotlin/app/mealsy/data/repo/`; repository tests with a fake API
- [ ] T037 [US1] Add the Care profile card to `ui/profile/ProfileScreen.kt` (mockup 2: title, "Shared with …" line only when `care_team` is non-empty, coloured count chips per type); tap opens `ROUTE_CARE_PROFILE` registered in `ui/AppNav.kt`
- [ ] T038 [US1] Create `ui/profile/CareProfileScreen.kt` and `CareProfileViewModel.kt` per mockup 1: header with last-updated date (and the `care_team` line only when non-empty), "N of M limits on track today" banner, expandable rows per type with count badges, nutrient-limit rows with limit text ("Up to 1,500 mg a day", "50-60 g a day") and a today-so-far bar with a limit marker
- [ ] T039 [US1] Add, edit and retire per entry in `ui/profile/EntryEditorSheet.kt` (type-specific fields from `EntryValue`; retire asks for confirmation before calling the API) (FR-020a)
- [ ] T040 [US1] Show `profile_unavailable_text` as an error message in chat (`ui/chat/ChatViewModel.kt`) when the turn fails for that reason
- [ ] T041 [US1] Goldens for CareProfileScreen (empty, typical, expanded nutrient limits) in light and dark in `android/app/src/test/java/app/mealsy/android/ui/profile/`; on-device check on the Pixel 9
- [ ] T042 [US1] Write `eval/cases/safety_profile/` (24 synthetic patients with entries, multi-session scripts and expected profiles) and the skeleton of `eval/eval_safety_profile.py` reporting recall of earlier-session facts (SC-003); register the `safety_profile` category in `eval/gate.py`
- [ ] T043 [US1] Run `eval/eval_profile_coaching.py --runs 3` (restrictions gate) and the backfill dry-run counts against a copy of production data; record both in the PR (quickstart PR 1)

**Checkpoint**: PR 1. US1 works on its own.

---

## Phase 5: User Story 2 - No meal that breaks a hard constraint reaches the patient (P1)

**Goal**: structured recipes, USDA-computed totals, deterministic checker, regenerate up to 3 times or drop; reply guardrail on prose; every failure logged; recipe card in the app.

**Independent test**: offline eval over fixture recipes × synthetic profiles reports 0 shown violations and the expected failure rules (quickstart PR 2).

### Tests for US2

- [ ] T044 [P] [US2] Tests for `Recipe` validation and totals in `tests/safety/test_recipe.py` (malformed when `qty_g <= 0`; unresolved ingredient makes a limited nutrient `unknown`; fluid `approximate`; totals per serving)
- [ ] T045 [P] [US2] Tests for the checker in `tests/safety/test_checker.py`: one case per acceptance scenario US2-1 to US2-8 (peanut oil, USDA sodium over limit despite model claim, warfarin + vitamin K, MAOI + aged cheese, crunchy for swallowing, active minutes vs standing limit, grip equipment, unknown potassium fails, table edit takes effect), plus diet settings, food exclusions, `exclude_terms` (nutmeg), per-day limit with today's intake, missing-value notes, stricter-rule conflicts
- [ ] T046 [P] [US2] Tests for the reply guard in `tests/safety/test_reply_guard.py` (lexical and USDA layers) and `tests/test_reply_judge.py` (GLiDE layer with a mocked client; GLiDE down falls back to layers 1-2)
- [ ] T047 [P] [US2] Tests for the suggestion loop in `tests/test_suggest.py` with a fake generator: pass on attempt 2, drop after 3 with `no_suitable_meal_text`, `check_failure` rows with `outcome`, `recommendation` row with `check_snapshot`, food DB down gives `food_db_unavailable_text`

### Implementation for US2

- [ ] T048 [US2] Implement `src/backend/safety/recipe.py`: `Ingredient`, `Recipe` (fields and limits exactly as `contracts/recipe-and-check.md`: ingredients "1-20", steps "1-12, each ≤ 200 chars", `intro` "≤ 200 chars", `texture` literal, `active_minutes ≥ 0`, `total_minutes ≥ active_minutes`), `ResolvedIngredient`, `NutrientTotal`, `resolve(recipe)` using `usda_local.lookup` in a thread pool, in parallel, no FDC API and no LLM estimate, below `usda.match_confidence_floor` = unresolved; nutrient keys `Sodium, Na`, `Potassium, K`, `Phosphorus, P`, `Carbohydrate, by difference`, `Water`, `Vitamin K (phylloquinone)`, `protein_g`
- [ ] T049 [US2] Implement `src/backend/safety/checker.py` `check(recipe, resolved, entries, today_intake, tables) -> CheckResult` per contract (allergen and exclusion term matching per research R8, diet settings, interactions, nutrient limits incl. unknown-fails, texture and crunchy terms per R9, physical rules, `applied`, `missing_values` from `condition_limits.yaml`, `conflicts` with stricter rule)
- [ ] T050 [US2] Implement `src/backend/safety/render.py` `constraint_sentence(applied)` and `render_recipe(recipe, result) -> str` (FR-032); the model never writes the constraint sentence
- [ ] T051 [P] [US2] Write prompt `src/backend/config/prompts/recipe_generation_system.md` (structured recipe, grams per ingredient, honour the profile block and prior failure reasons, no medical advice) and add the `PromptsConfig` field
- [ ] T052 [US2] Implement `src/backend/agent/suggest.py`: Pydantic AI agent with `output_type=Recipe`, `suggest_meal(user_id, request, history) -> SuggestionResult` running the loop from the contract, writing `check_failure` and `recommendation` rows, opening `review_item` rows for `rule_conflict` and `unknown_medication`; spans `suggest_meal`, `check_recipe` with attempt and rules
- [ ] T053 [US2] Add `suggests_meal: bool` to `QueryParsed` in `src/backend/agent/coaching.py` and to `src/backend/config/prompts/query_parse_system.md`; `CoachingAgent.handle` calls `suggest_meal` when it is true and returns the rendered recipe plus `recommendation_id`
- [ ] T054 [US2] Implement `src/backend/safety/reply_guard.py` (lexical layer, USDA-resolution layer, `GuardVerdict`) and `src/backend/agent/reply_judge.py` (GLiDE question "does this reply suggest the user eat something containing X?", `reply_guard_min_probability`)
- [ ] T055 [US2] Register `@_response_agent.output_validator` in `src/backend/agent/coaching.py` raising `ModelRetry(verdict.retry_reason)`, set `retries=2`, and replace the reply with `safety.reply_guard_fallback_text` plus a `check_failure` (`outcome='reply_replaced'`) when retries run out
- [ ] T056 [US2] Return `recipe` and `recommendation_id` in the chat response from `src/backend/agent/orchestrator.py` `_handle_coaching` (optional fields)
- [ ] T057 [US2] Add `POST /profile/meals/{recommendation_id}/feedback` to `src/backend/api/profile.py` (status `accepted` | `rejected`, reason "≤ 500 chars") (FR-025)
- [ ] T058 [US2] Add the nightly `purge_old_recommendations` Celery task fanned out per user in `src/backend/workers/tasks.py` (`safety.recommendation_retention_days`)
- [ ] T059 [US2] Implement `eval/eval_safety_profile.py --offline` (fixture recipes × synthetic profiles, no model, must print 0 shown violations and each expected failure rule) and live mode; add the offline run to `scripts/prod-checks.sh`; add `eval/eval_reply_guard.py` over `eval/cases/reply_guard.jsonl`
- [ ] T060 [P] [US2] Android: `RecipeDto` and optional `recipe`, `recommendationId` on the chat response in `Dtos.kt`; feedback endpoint in `MealsyApi.kt`
- [ ] T061 [US2] Android: `ui/chat/RecipeCardView.kt` rendering name, intro, ingredients with grams, steps, time and the constraint sentence, with "Accept" and "Not for me" (optional reason) calling feedback; plain-text fallback when `recipe` is absent; goldens light and dark; on-device check
- [ ] T062 [US2] Run the live `safety_profile` gate and `eval_reply_guard.py`; record violation rate (must be 0), share and p95 latency of the GLiDE layer, recipe-turn p90 (budget < 12 s) in the PR

**Checkpoint**: PR 2. US1 and US2 work together.

---

## Phase 6: User Story 3 - Dangerous messages get a fixed safe reply (P1)

**Goal**: rule-based screen before any model call; fixed response; stored escalation; webhook notice without message text.

**Independent test**: every listed phrase and marked paraphrase gets the fixed response, no model span, a notification; ordinary messages pass (quickstart PR 3).

- [ ] T063 [P] [US3] Tests in `tests/safety/test_red_flags.py` (match anywhere in the message, first rule in file order wins, reload on edit, invalid file fails closed, < 50 ms on 10 kB input) and `tests/test_orchestrator_safety.py` (no GLiDE task, no graph read, no model call on a match; paused meal card unchanged; fail-closed reply when the list is unreadable)
- [ ] T064 [P] [US3] Test `notify_escalation` in `tests/test_notify_escalation.py` (payload has no message text, name or email; retries; `no_recipient` when `SAFETY_WEBHOOK_URL` unset; `failed` after the last retry)
- [ ] T065 [US3] Implement `src/backend/safety/red_flags.py`: compiled rules from `red_flags.yaml`, `screen(message) -> RedFlagMatch | None`, fail-closed state exposing `fallback_unavailable_text`
- [ ] T066 [US3] Call the screen first in `src/backend/agent/orchestrator.py` `handle_message`, before the GLiDE task and the checkpoint read; on a match store `red_flag_escalation`, enqueue `notify_escalation`, return the fixed response with `"kind": "safety"`; span `red_flag_screen` with rule id and duration
- [ ] T067 [US3] Implement `notify_escalation` in `src/backend/workers/tasks.py` per `contracts/webhook.md` (httpx, timeout 5 s, backoff 5 s, 15 s, 45 s, 2 min, 5 min; status on the row; `logfire.error` on `failed` / `no_recipient`); add `SAFETY_WEBHOOK_URL` to `.env.example`
- [ ] T068 [US3] Implement `eval/eval_red_flags.py` (100% of listed and marked phrases, ≤ 1% of ordinary messages, p99 screen time) and run it; record results in the PR
- [ ] T069 [US3] Android: render replies with `kind == "safety"` in a distinct safety message style without feedback buttons in `ui/chat/`; add optional `kind` to the chat DTO; golden light and dark; on-device check with a paused meal card

**Checkpoint**: PR 3. Phases 1-3 shippable without 4-6 (SC-011).

---

## Phase 7: User Story 4 - What the patient says becomes memory the right way (P2)

**Goal**: typed candidates scored by GLiDE, three-band decision in code, readback and reply handling, pending retirements.

**Independent test**: scripted conversations produce accepted, pending and dropped entries as labelled; a confirmed fact binds on the next recipe in the same conversation (quickstart PR 4).

- [ ] T070 [P] [US4] Tests in `tests/test_memory_judge.py` for the three-band rule: accept only when the candidate adds a constraint (new allergy, diagnosis, medication, physical limitation, food exclusion, diet setting, or a stricter nutrient limit for the same nutrient and period); removals, loosening and unscored candidates always ask; low scores dropped
- [ ] T071 [P] [US4] Tests in `tests/test_memory_curator.py`: `evidence` must be a substring of the patient's message or the candidate is discarded (FR-023); facts from the assistant reply or logged meals never produce hard candidates
- [ ] T072 [P] [US4] Tests in `tests/test_orchestrator_safety.py` for readback replies: yes confirms, no retires, anything else retires and re-extracts; a meal card and a readback waiting together go to the one asked last; accepted inferred facts mentioned once (`mentioned_at`)
- [ ] T073 [US4] Rewrite `src/backend/config/prompts/profile_curator_system.md` and `src/backend/agent/memory_curator.py` to emit typed hard candidates (`type`, `value`, `label`, `evidence`) and soft facts, with the evidence substring check
- [ ] T074 [US4] Extend `src/backend/agent/memory_judge.py` with one GLiDE question per hard type plus `no_longer_true`, and `select_hard_ops` implementing the bands with tunables `memory.hard_accept_min_probability` and `memory.hard_ask_min_probability` (placeholders until T078)
- [ ] T075 [US4] Run hard-fact extraction concurrently with `parse_query` on coaching turns in `src/backend/agent/coaching.py`; accepted entries saved confirmed (`source='inferred'`, `confirmed_by='inference'`, `inference_probability`), ask-band entries saved pending with `readback_asked_at`; on a recipe turn with a new pending fact, withhold the recipe and ask first; logging turns keep extraction in Celery (`_enqueue_fact_extraction`)
- [ ] T076 [US4] Handle readback replies in `src/backend/agent/orchestrator.py` before routing (Constitution III) using `agent/tools/meals.py` `classify_intent` keywords; append the templated readback or the one-time "noted" mention to the reply and return the optional `readback` field
- [ ] T077 [US4] Implement `eval/eval_hard_fact_inference.py` (precision and recall per type and band, reliability curve, Brier score, threshold sweep on `tune`, report on `holdout`) and add the script set to `eval/eval_safety_profile.py`
- [ ] T078 [US4] Run the sweep, set `hard_accept_min_probability` and `hard_ask_min_probability` in `tunables.yaml` with the measured numbers in the comment, run on `holdout`, record SC-002 and SC-004 results (accept-band precision ≥ 98%) in the PR
- [ ] T079 [US4] Android: render the optional `readback` with Yes / No chips that send the reply in `ui/chat/ReadbackChips.kt`; the "noted" mention links to the entry in Care profile; goldens light and dark; on-device check

**Checkpoint**: PR 4.

---

## Phase 8: User Story 5 - Tastes, meal history, and viewing what Mealsy knows (P2)

**Goal**: dated soft preferences with new kinds, three-week history, rejection reasons, full view, edit, delete and export.

**Independent test**: seeded preferences and three weeks of meals shape a suggestion without repeats; edits and deletes from the app take effect next request (quickstart PR 5).

- [ ] T080 [P] [US5] Tests in `tests/test_profile_api.py` for `PATCH/DELETE /profile/soft/{id}`, `GET /profile/meals?days=21` ("`days` ≤ 90"), `GET /profile/export`; tombstoned preferences not re-learned
- [ ] T081 [P] [US5] Tests in `tests/test_context.py` for the three-week history block (at most 30 lines, de-duplicated, from `recommendation` and `meal_log` labels) and graceful omission of soft context on failure (FR-027)
- [ ] T082 [US5] Add kinds `cuisine`, `budget`, `cooking_time` to `src/backend/agent/memory.py` and render soft facts with their dates; remove the legacy top-k `_fetch_preferences` path from `src/backend/agent/context.py` and turn soft memory on for every user (`memory.profile_enabled` removed)
- [ ] T083 [US5] Add the history block to `src/backend/agent/context.py` and pass it to `suggest.py` for variety
- [ ] T084 [US5] Add `PATCH/DELETE /profile/soft/{id}`, `GET /profile/meals`, `GET /profile/export` to `src/backend/api/profile.py`; mark `/memory` deprecated in `src/backend/api/memory.py` (removed once the app release with T085 is live)
- [ ] T085 [US5] Android: in `ui/profile/CareProfileScreen.kt` add "inferred" and "awaiting confirmation" labels with confirm / correct actions and an entry history view; add `ui/profile/PreferencesScreen.kt` (soft facts with dates, edit, delete), `ui/profile/MealHistoryScreen.kt`, and export (share sheet with the JSON); Food preferences row on Profile opens PreferencesScreen
- [ ] T086 [US5] Goldens light and dark and an on-device timing check of SC-010 (find, edit, delete a preference in under a minute)

**Checkpoint**: PR 5.

---

## Phase 9: User Story 6 - Reviewers act on the queue (P3, backend only)

**Goal**: protected admin queue with approve, reject, edit, handled; clinician-sourced entries only from here.

**Independent test**: a pending entry, a red flag and a plan sample appear in the queue; decisions update the profile with source clinician (quickstart PR 6).

- [ ] T087 [P] [US6] Tests in `tests/test_review_api.py` for every cell of the decision table in `contracts/review-api.md`, 403 for non-reviewers, 409 on re-decision, newest-first listing and kind filter
- [ ] T088 [US6] Implement `src/backend/auth/reviewer.py` `require_reviewer` (Supabase JWT + `REVIEWER_USER_IDS` env list; add the variable to `.env.example`)
- [ ] T089 [US6] Implement `src/backend/api/review.py` (`GET /admin/review/items`, `GET /admin/review/escalations/{id}`, `POST /admin/review/items/{id}/decision`, `POST /admin/review/patients/{patient_id}/entries`) using `safety.profile` with actor `reviewer:<user id>`; register in `src/backend/main.py`
- [ ] T090 [US6] Create `plan_sample` review items for a configurable share of recommendations (`safety.plan_sample_rate` in tunables) in `src/backend/agent/suggest.py`; extend `src/backend/guidelines/export_feedback.py` to export plan-sample rejections with comments

**Checkpoint**: PR 6.

---

## Phase 10: Polish and cross-cutting

- [ ] T091 Migration `2026112x_020_drop_goal_condition_columns.py` dropping `user_goal.conditions`, `user_goal.dietary_prefs` and `user_memory.embedding` with its ivfflat index, released one version after PR 1 (PR 7); remove the ORM attributes from `src/backend/db/models.py`
- [ ] T092 [P] Update `.claude/CLAUDE.md` (layout: `safety/`, `config/clinical/`, new APIs, env vars `SAFETY_WEBHOOK_URL`, `REVIEWER_USER_IDS`, eval commands) and `docs/architecture.md` (turn flow with screen, guardrail, suggestion loop)
- [ ] T093 [P] Check log hygiene (FR-040c): no name or email in spans, `check_failure`, escalations or webhook payloads; message text only in Logfire spans already allowed and in `red_flag_escalation.message`
- [ ] T094 Run the full quickstart.md end to end on the throwaway DB and the Pixel 9; run `scripts/prod-checks.sh`; fix findings
- [ ] T095 Dietitian review of all `config/clinical/*.yaml` values (replace every `PENDING DIETITIAN REVIEW`) before PR 2 ships to production

---

## Dependencies and execution order

- **Setup (T001-T007)**: no dependencies. T001 blocks shipping PR 1, not coding.
- **Navigation shell (T008-T015)**: independent of the backend; merge before T037.
- **Foundational (T016-T024)**: blocks every story.
- **US1 (T025-T043)**: after Foundational. MVP.
- **US2 (T044-T062)**: after Foundational; uses `safety.profile` from US1 (T029) for the confirmed entries.
- **US3 (T063-T069)**: after Foundational only; can run beside US1/US2.
- **US4 (T070-T079)**: after US1 (entries, readback targets) and T005 (datasets).
- **US5 (T080-T086)**: after US1; T083 uses `suggest.py` from US2.
- **US6 (T087-T090)**: after US1; escalation items need US3, plan samples need US2.
- **Polish**: T091 after PR 1 has been live for one release; the rest last.

Within each story: tests first and failing, then `safety/` models and logic,
then agent wiring, then API, then Android, then the eval run.

## Parallel opportunities

- Setup: T002, T003, T006, T007 together; T004 then T005.
- Foundational: T021-T023 beside T017-T020.
- US1: T025-T028 together; T036 (Android data layer) beside T029-T035.
- US2: T044-T047 together; T051 and T060 beside the backend tasks.
- US3 can run as a whole beside US2 (different files: `safety/red_flags.py`, orchestrator entry, Celery task).
- US4: T070-T072 together.

### Example: US2

```text
Together: T044 test_recipe.py · T045 test_checker.py · T046 test_reply_guard.py · T047 test_suggest.py
Then:     T048 recipe.py → T049 checker.py → T050 render.py
Beside:   T051 recipe prompt · T060 Android DTOs
```

## Implementation strategy

1. **MVP**: Setup, Navigation shell, Foundational, US1 (PR 0, PR N, PR 1).
   The confirmed profile reaches every prompt and patients edit it in the
   app. Validate with quickstart PR 1 and ship.
2. **Safety core**: US2 and US3 (PR 2, PR 3). SC-011: these must ship and
   pass the eval without US4-US6.
3. **Learning**: US4 (PR 4), after the thresholds are measured.
4. **Experience**: US5 (PR 5), then US6 (PR 6), then the contract migration
   (PR 7).

Each PR goes to `feat/android-app` from `user_memory`; production only through `/ship`.
