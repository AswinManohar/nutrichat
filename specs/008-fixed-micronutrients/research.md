# Research: Fixed Micronutrient Set with Estimated Fallback

**Feature**: 008-fixed-micronutrients | **Date**: 2026-10-03 | **Spec**: [spec.md](./spec.md)

Evidence comes from the bundled USDA catalogue
(`src/backend/data/usda_fdc.sqlite3`, 13,694 foods), the FDC 2026-04-30 CSV
release, and the dev database (`meal_log`, 285 meals and 773 items, queried
read-only on 2026-10-02 and 2026-10-03).

---

## R1. Where the nutrient catalogue lives

- **Decision**: Use a new file, `src/backend/config/nutrients.yaml`, validated
  by a Pydantic model in `backend.config` and loaded once, the same way
  `get_tunables()` is loaded. It is served read-only at
  `GET /meta/nutrients` (see [contracts/nutrients-catalogue.md](./contracts/nutrients-catalogue.md)).
  It **replaces** the `nutrient_checkup.micronutrients` and
  `nutrient_checkup.rda` blocks in `tunables.yaml`. The Check-up keeps only a
  list of which catalogue keys it shows.
- **Rationale**: FR-015 and FR-018 call for exactly one definition of each
  nutrient. YAML matches how the project already configures itself, and an
  endpoint lets web, Android and the future charts read the same list with
  nothing hard-coded (SC-009).
- **Alternatives considered**: A DB table needs a migration for every catalogue
  edit, and the data is static. Hard-coding the list in each client breaks
  FR-015 and creates three copies. Keeping it inside `tunables.yaml` would put
  about 48 large entries into a file meant for tuning knobs.

## R2. Nutrient keys

- **Decision**: Keys are lowercase snake_case **with no unit suffix**, for
  example `sodium`, `vitamin_b12` or `added_sugars`. The unit lives in the
  catalogue.
- **Rationale**: FR-016 says keys must never be renamed. A unit in the key
  (`sodium_mg`) would force a rename if the canonical unit ever changed. The
  existing macro column names (`fiber_g`) are left alone.
- **Alternatives considered**: USDA names as keys (for example `"Iron, Fe"`)
  are what the app uses today. They are unstable across FDC releases (the
  sugars spelling issue) and awkward in JSON paths.

## R3. Storage shape

- **Decision (revised 2026-10-03)**: Store micros **per logged item**, inside
  the existing `meal_log.entities[]` JSON, in compact form
  `{key: [amount, "u"|"e"]}` with known values only (data-model §2). Meal, day
  and period summaries are **computed when read** (`resolve.summarise`).
  There is no new column and no migration.
- **Rationale**: The per-item values already exist at log time, so keeping
  them costs a few KB per meal. It keeps per-item sources, enables food-level
  "top contributors" (spec 004), and matches how saved meals store
  ingredients. FR-018 still holds because the items are the only copy.
- **Alternatives considered**: A meal-level `meal_log.micros` summary was
  built first and replaced: it threw away per-item detail. A summary column
  next to the items would store the data twice. 48 typed columns were
  rejected by the user.

## R4. Nutrients already stored as macro columns

- **Decision**: **Fiber** stays only in `meal_log.fiber_g`. Its catalogue entry
  points at that column (`column: fiber_g`), and `micros` never holds `fiber`.
  **Total sugars** and **saturated fat** live only in `micros`. Their
  per-item `sugar_g` and `sat_fat_g` remain in-memory fields on the result
  model (the junk-food flag uses them), but they are no longer stored in
  `entities`.
- **Rationale**: FR-018 forbids storing anything twice. Fiber already has a
  column that the Check-up and goals read.
- **Alternatives considered**: Also copying fiber into `micros` would create
  the duplicate the user explicitly ruled out.

## R5. Salt

- **Decision**: Salt is **never stored**. The catalogue marks it as
  `derived: {from: sodium, factor: 0.0025}` (mg of sodium to g of salt). Every
  reader, including the daily-totals query, computes it.
- **Rationale**: FR-001c says salt equals sodium × 2.5, so storing it would be
  a copy.

## R6. Filling gaps in USDA matches (the main design choice)

Most USDA foods lack at least one tracked nutrient. Added sugars is missing
for 100% of foods, trans fat for 69%, B5 for 53% and manganese for 49%. A
runtime AI call per matched item would add latency and cost to every log
(SC-003 allows at most 10% slower logging).

- **Decision**: **Pre-compute gap estimates at build time** inside the bundled
  SQLite file. A new table, `food_micro_estimate(fdc_id, key, per_100g)`, is
  filled by a one-off batch script. The script calls Gemini 2.5 Flash-Lite
  through the batch API, sending the food description plus the nutrients
  USDA *does* report as context. Each estimate is checked against the R8
  plausibility ranges, and rejected values are left out, which makes them
  "unknown". At runtime a USDA-matched item reads its USDA values first, then
  the pre-computed estimates, with **zero extra AI calls**.
- **Cost**: about 13,694 foods × ~700 tokens ≈ 10M tokens, a few dollars at
  Flash-Lite batch pricing. This is a one-off, and it is re-run only when the
  USDA release changes. **Running it needs the user's go-ahead** (see the
  memory note "ask before big downloads/runs").
- **Rationale**: It costs no latency, behaves the same on every log, can be
  reviewed offline, and can be benchmarked for SC-004 before release. Gap
  estimates depend only on the food (per 100 g), so they belong next to the
  food data.
- **Alternatives considered**:
  - A runtime AI call per matched item with gaps: this hits almost every log
    (added sugars), adds about 1 s and a cost per log, and fails SC-003.
  - A background (Celery) gap fill after logging: the meal summary would
    change after the fact, the meal would be briefly incomplete, and there
    would be extra moving parts.
  - Leaving gaps "unknown": added sugars would never have a value, which fails
    SC-001.
  - The FDC API rollback path (`use_local_db=false`) has no pre-computed
    table, so gaps there stay "unknown". That is acceptable because it is only
    an emergency fallback.

## R7. Foods with no USDA match (whole-food estimate)

- **Decision (revised during implementation, 2026-10-03)**: The card's macro
  estimate call is **unchanged**. Micronutrients come from a **separate
  call** (`_micro_agent`, prompt `micro_estimate_system.md`) that is
  **scheduled in the background** when the card's estimate is made, and its
  result is merged into the same estimate cache row (`food_source`). At log
  time, `resolve_micros` awaits that background task if it is still running
  (capped at 10 s), or runs the call itself if this process never scheduled
  one. The output is a flat list of `{key, per_100g}` entries. Keys are
  validated against the catalogue server-side, and unknown or USDA-only keys
  are dropped.
- **Why the original single-call design was dropped** (measured live):
  1. Gemini rejected the schema with one optional nullable field per
     nutrient (about 40 fields) with "too much branching for serving". This
     would have made every unmatched-food estimate fail.
  2. With a flat list in the same call, the card got about 40% slower
     (median 0.91 s → 1.28 s, 8 foods), and the model filled only about 5 of
     36 micros.
- **Measured after the change**: the card estimate's median is 0.76 s
  (unchanged from before). The background micro call has a median of 3.6 s
  and returns 36 of 36 micros for every test food. Log time waits only if the
  user confirms within about 3.6 s of the card appearing.
- **FR-009 reading**: the micro estimate runs in parallel with the user
  reviewing the card, not after it, so it adds no latency on the card path.

## R8. Plausibility ranges (FR-007)

- **Decision**: Each catalogue entry has `max_per_100g`. For nutrients USDA
  reports for at least 30% of foods, the cap is 1.5 × the largest
  per-100 g value USDA reports (changed during implementation: a 99.9th
  percentile cut rejected real extremes such as cod liver oil's vitamin D;
  gram caps are clamped to 100 g per 100 g), computed once by the build script and
  written into the catalogue. For sparse or USDA-less nutrients (added sugars,
  chloride, chromium, iodine, molybdenum, biotin, fluoride), the cap is set by
  hand from published food-composition maxima. There is also one cross-field
  rule: added sugars must be ≤ total sugars. Any value over its cap is
  dropped, which makes it unknown.
- **Rationale**: The caps are driven by data where data exists, and they are
  reproducible.

## R9. Server-side derivation at log time (FR-019 "Log again")

- **Decision**: A new module, `backend/nutrients/resolve.py`, provides
  `resolve_micros(fdc_id, food_name, qty_g)`. It looks up per-100 g values
  from the local SQLite (USDA plus pre-computed estimates) when
  `fdc_id > 0`, or from the estimate cache by name when `fdc_id == -1`. It
  then scales them and applies the USDA-only rule. `log_meal` calls it for
  **every** item and **ignores any micronutrients sent by the client**. That
  fixes Android "Log again" (its items carry no micros after the change),
  covers old saved meals that hold only raw `nutrients`, and matches the
  existing "never trust client macros" rule.
- **Rationale**: There is one code path to compute the summary, and the client
  payload no longer needs micronutrients at all.
- **Alternative rejected**: Trusting the micros the card sends back means
  client-supplied data ends up in the source of truth, and it would still
  break "Log again".

## R10. Mapping USDA names and units

| Key | USDA source name(s) | Note |
|---|---|---|
| total_sugars | Total Sugars; Sugars, Total | both spellings (83.6% + 1.4%) |
| vitamin_a | Vitamin A, RAE | µg RAE |
| folate | Folate, DFE (fallback Folate, total) | µg DFE |
| vitamin_e | Vitamin E (alpha-tocopherol) | mg |
| vitamin_k | Vitamin K (phylloquinone) | µg; MK-4 (4.9%) ignored |
| choline | Choline, total | mg |
| fluoride | Fluoride, F | µg |
| alcohol | Alcohol, ethyl | g |
| (all µg) | USDA unit `ug` | stored as canonical `mcg` (label only; same value) |

The full alias table lives in the catalogue (`usda_names`).

## R11. Reading per-day totals (FR-017, SC-008)

- **Decision**: One query unpacks `micros` with `jsonb_each` and groups by
  nutrition day (`NUTRITION_DATE_SQL`). Fiber comes from its column and salt
  is computed. It is exposed as `get_daily_micros(user_id, date_from, date_to,
  keys)` and at `GET /nutrients/daily` (see [contracts/daily-totals.md](./contracts/daily-totals.md)).
  The existing per-nutrient loop in `history.get_micronutrients_for_range`
  (one query per nutrient) is replaced by this single pass.
- **Rationale**: The dev database showed about 45 ms for a full year of the
  heaviest user on the *current* per-item layout. Meal-level summaries need
  less work, so SC-008 (under 1 s for 90 days and 48 nutrients) has plenty of
  headroom. The existing `user_id` index is enough, so no new index is added.

## R12. What is no longer stored

- **Decision**: Stored copies of `entities` (meal_log) drop `nutrients`,
  `sugar_g` and `sat_fat_g`. Saved-meal `ingredients` replace raw USDA-named
  `nutrients` with per-ingredient `micros` (catalogue keys, with amount and
  source). Saved-meal micro **totals are computed when read** (FR-014a).
- **Rationale**: FR-018. Raw nutrients can always be looked up again from the
  catalogue by `fdc_id`.
- **Compatibility**: Existing saved meals that have raw `nutrients` and no
  `micros` are resolved through R9 when logged. No migration of saved meals
  is needed, which is consistent with "no backfill" since this is a dev
  environment.

## R13. Integration feed (FR-019)

- **Decision**: `MealOut` in `api/integrations.py` gains `micros`, in the same
  shape as [contracts/meal-micros.md](./contracts/meal-micros.md). Its items
  lose `nutrients` automatically (R12). `docs/integration-api.md` gets a
  changelog entry. **Open question for the user**: does life-os read
  per-item `nutrients`? If it does, the feed change has to be coordinated
  with it before release.

## R14. Coaching nutrient names

- **Decision**: `query_parse_system.md` switches from "EXACT USDA names" to
  catalogue keys. The parser resolves through the catalogue aliases, so a
  USDA name the model still emits keeps working. `_MACRO_ALIASES` is
  unchanged.

## R15. Observability (FR-011)

- **Decision**: The `log_meal` Logfire span gains `micros.usda`,
  `micros.estimated`, `micros.unknown` and `micros.rejected` counts. The build
  script logs the rejection rate for each nutrient.

## R16. USDA zeros

Settled in Clarifications. FDC derivation codes show that zeros are real
(59% of SR Legacy zeros are "assumed zero" and 86% of Foundation zeros were
measured in a lab), so a zero is never treated as a gap.
