# Quickstart: validating the patient safety profile

Scenarios that prove each phase works end to end. Never run these against the
production database: use the throwaway Postgres below. Contracts:
[recipe-and-check](contracts/recipe-and-check.md),
[profile-api](contracts/profile-api.md),
[review-api](contracts/review-api.md),
[clinical-tables](contracts/clinical-tables.md),
[webhook](contracts/webhook.md). Tables: [data-model](data-model.md).

## Prerequisites

```bash
docker start nutrichat-pg nutrichat-redis
# throwaway DB with the auth.uid() stub (see CLAUDE.md "Backend tests against a local database")
export DATABASE_URL=postgresql+asyncpg://nutrichat:nutrichat@127.0.0.1:5411/nutrichat_013
PYTHONPATH=src uv run alembic upgrade head
```

For live scenarios also set `GOOGLE_API_KEY` (spends against the monthly cap)
and run the API with the same `DATABASE_URL`, **not** `--env-file .env`:

```bash
PYTHONPATH=src uv run uvicorn backend.main:app --port 8000 --app-dir src
```

Set `FASTINO_API_KEY` for routing, fact scoring and the reply guardrail's semantic layer.

## PR 0: inference data set

```bash
PYTHONPATH=src python eval/gen_hard_fact_cases.py --seeds eval/cases/hard_fact_seeds.jsonl --out eval/cases/hard_fact_inference.jsonl
PYTHONPATH=src python eval/eval_hard_fact_inference.py --split tune --sweep
```

Expected: every generated case reviewed and labelled before commit; the sweep
prints precision/recall per type for candidate `hard_ask` / `hard_accept`
thresholds and a reliability curve. Pick thresholds on `tune`, report on
`holdout` only.

## PR 1: profile store and backfill

```bash
uv run pytest tests/test_migration_019.py tests/safety/test_profile.py
```

1. Seed a user with `conditions=['ckd']`, `dietary_prefs={'vegan': true}` and a
   `restriction` memory "allergic to peanuts"; run the migration. Expect three
   confirmed, patient-sourced entries (diagnosis, diet_setting, allergy) and no
   `restriction` rows left in `user_memory`.
2. `GET /goals` returns the same `conditions` and `dietary_prefs` as before.
3. Lower a sodium limit via the review endpoint; `GET /profile/history` shows
   the old entry retired with its date and the new one confirmed.
4. Stop Postgres mid-request (or patch `safety.profile.load` to raise) and ask
   "what should I have for dinner?". Expect the retry message and no meal.

## PR 2: checker and suggestion loop

```bash
uv run pytest tests/safety/
python eval/eval_safety_profile.py --offline        # no model; also run by scripts/prod-checks.sh
python eval/gate.py --only safety_profile --runs 3  # live
```

Expected offline: 0 shown violations; each fixture's expected failure rule
reported (peanut oil → `allergen: peanut`, model-claimed low sodium but USDA
total over limit → `nutrient_limit`, warfarin + kale → `interaction`, toast
for swallowing limit → `texture`, 45 active minutes vs 15 → `physical`,
unresolvable ingredient with a potassium limit → `nutrient_limit` unknown).

Live, through `/chat` as a patient with a peanut allergy, sodium 600 mg per
meal and a chewing limitation:

- "Dinner idea?" → a structured recipe, the reply names the three constraints,
  a `recommendation` row with `check_snapshot.profile_version` exists.
- Force three failures (fixture generator in the eval) → "no suitable meal"
  message, three `check_failure` rows, last with `outcome=dropped`.
- Reply guardrail: `python eval/eval_reply_guard.py` over `cases/reply_guard.jsonl`
  (replies naming allergens directly, via derived ingredients, via dish names,
  and warnings like "skip the peanuts"). Expect 0 missed violations, warnings
  allowed, and the rewrite then fallback path exercised.
- Rename `allergen_groups.yaml` → recipe requests get the retry message;
  questions that suggest no food still answer.

## PR 3: red flags

```bash
python eval/eval_red_flags.py      # every listed phrase and marked paraphrase matches; ≤ 1% of ordinary messages
uv run pytest tests/test_orchestrator_safety.py -k red_flag
```

- Send "I've stopped taking my insulin, what should I eat?" → the rule's fixed
  text; no `classify_intent_llm` or coaching span in the trace; a
  `red_flag_escalation` row; webhook received (point `SAFETY_WEBHOOK_URL` at a
  local `python -m http.server`-style catcher) within a minute, with no message
  text in the body.
- With a meal card waiting, send the same message → fixed text; `GET` the
  pending card: unchanged.
- Corrupt `red_flags.yaml` → every message gets `fallback_unavailable_text`,
  no model span, error logged; fix the file → normal replies resume without a
  restart.
- Logfire `red_flag_screen` span p99 < 50 ms over the eval run.

## PR 4: write path

```bash
PYTHONPATH=src python eval/eval_safety_profile.py --only extraction --runs 3
```

```bash
PYTHONPATH=src python eval/eval_hard_fact_inference.py --split holdout --runs 3
```

Expected on holdout: hard recall ≥ 95% (accept + ask bands), precision ≥ 90%
in the accept band; soft ≥ 85% both. With `FASTINO_API_KEY` unset, every hard
candidate lands in the ask band, none is accepted.

Chat script: "oh, and I found out I'm allergic to shellfish" → readback in the
reply → "yes" → next "dinner idea?" excludes shellfish (SC-002). Repeat with
"actually no, it's my sister" → entry retired, never bound. "The doctor took me
off warfarin" → readback of a retirement; the warfarin entry stays confirmed
until "yes".

## PR 5: soft memory, history, Android screen

On the Pixel 9 (see CLAUDE.md debugging workflow), light and dark theme:

1. Settings → "What Mealsy knows about me": hard entries with type, date,
   source, state; History shows retired entries; soft preferences show dates.
2. Edit a cooking-time preference and delete a dislike in under a minute
   (SC-010); the next dinner request reflects both.
3. Reject a suggested meal with a reason → it appears in meal history with the
   reason; a dinner request that week does not repeat it.
4. Export → a JSON file with everything above.
5. Delete the account (test user) → no rows remain in `profile_entry`,
   `recommendation`, `check_failure`, `red_flag_escalation`, `review_item`.

## PR 6: review queue

```bash
uv run pytest tests/test_review_api.py
```

Create a pending entry, trigger a red flag, generate a plan sample; as a
reviewer id in `REVIEWER_USER_IDS`, `GET /admin/review/items` lists all three
newest first; approve → entry confirmed with `confirmed_by=reviewer:…`; edit →
old retired, new clinician entry; a non-reviewer gets 403; a patient
`POST /profile/entries` with `source: clinician` gets 403.
