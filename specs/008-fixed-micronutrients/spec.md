# Feature Specification: Fixed Micronutrient Set with Estimated Fallback

**Feature Branch**: `008-fixed-micronutrients`

**Created**: 2026-10-02

**Status**: Draft

**Input**: User description: "define fixed micronutrients which is derived from USDA, when unavailable, falls back to llm determined values."

## Context

Today every logged food item stores whatever nutrients its USDA match reports.
That can be dozens of nutrients, or none at all. An audit of the development database
on 2026-10-02 found the following:

- 65% of logged items (498 of 773) carry no micronutrient data.
- 85 of those 498 items are AI-estimated foods. When no USDA match is found, the
  app estimates only calories and macros.
- Even among items logged since July, about 29% have no micronutrients.
- Matched USDA foods sometimes lack a given nutrient. For example, Vitamin D is
  missing for about 22% of the USDA catalogue.
- The same nutrient can appear under two different names (for example, two
  spellings of total sugars), so some sugar is left out of totals.

The result is that the Nutrient Check-up, coaching answers, and the planned
analytics view (spec 004) undercount micronutrients. Users cannot tell whether a
low number is real or just missing data.

This feature defines one **fixed set of tracked micronutrients**. Every logged
food item carries a value for each of them. The value comes from USDA whenever
USDA has it, and otherwise from an AI estimate, and each value records where it
came from.

## Clarifications

### Session 2026-10-03

- Q: When USDA reports 0 for a tracked nutrient, should we keep it as a real
  USDA value or replace it with an AI estimate? → A: Keep every USDA zero as a
  real value marked "USDA". Only a missing value triggers the fallback. This
  was checked against the FDC derivation codes for the bundled catalogue. 59%
  of SR Legacy zeros are coded "Assumed zero" (not naturally present) and 86%
  of Foundation zeros were measured in a lab. FNDDS zeros are calculated from
  the dish's recipe. USDA marks a missing value by leaving the nutrient out,
  not by reporting 0.
- Q: Should meals logged before this feature be backfilled with the tracked
  micronutrients? → A: No. The app is still in development, so there is no
  backfill. Existing items stay as they are.
- Q: Should the meal confirmation card show the tracked micronutrients? → A:
  No. The card keeps showing only calories and macros. Micronutrients are
  resolved and saved silently with each logged meal.
- Q: Which micronutrients should the fixed set cover? → A: Every nutrient on
  the reference app's list, which is 48 tracked nutrients plus the 4 macros
  (FR-001).
- Q: For nutrients USDA rarely or never reports, should the AI always estimate
  a value, or leave some "unknown"? → A: Estimate essential nutrients that have
  an official daily value. Arsenic, Boron, Cobalt, Rubidium, Silicon, Sulfur,
  Tin and Vanadium are USDA-only and are "unknown" when USDA has no value.
- Q: At what level are tracked micronutrients stored? → A: A logged meal
  stores one meal-level summary per nutrient (total, estimated portion and
  coverage). It has no per-item copy, because a logged meal is never edited
  item by item, only deleted whole. Saved meals (My Meals) keep values per
  ingredient, because users add, remove and resize ingredients and the totals
  are recomputed from them. Per-item values exist only in memory until the
  meal is confirmed.
- Q: Should the data be ready for a future micronutrient visualization
  feature? → A: Yes. Visualization is a separate, later feature. This spec
  must make sure the stored data and the nutrient catalogue can support it
  without rework (FR-015 to FR-017).
- Q: May any micronutrient data be stored twice? → A: No. Every fact has
  exactly one stored home, and anything derivable is computed when read
  (FR-018).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Every logged food has the tracked micronutrients (Priority: P1)

A user logs "a bowl of my mom's rasam with rice". The app finds no USDA match
for rasam, so it estimates the dish. Today that estimate includes calories and
macros but no vitamins or minerals. With this feature, the estimated item also
carries sodium, iron, calcium, vitamin C and the rest of the fixed set. The
user's daily micronutrient totals therefore reflect what they actually ate.

**Why this priority**: This closes the largest gap. AI-estimated foods are the
main source of missing micronutrient data for new logs.

**Independent Test**: Log a meal containing only a food that has no USDA match.
Confirm that the stored meal has a summary for every non-USDA-only nutrient in
the fixed set, and that each summary's estimated portion equals its total.

**Acceptance Scenarios**:

1. **Given** a food with no USDA match, **When** the user logs it, **Then** the
   logged meal has a total for every tracked micronutrient except the
   USDA-only ones, and each total is fully estimated.
2. **Given** a food with a confident USDA match that reports all tracked
   nutrients, **When** the user logs it, **Then** every total comes from USDA,
   with an estimated portion of 0. No AI estimate is requested.
3. **Given** a USDA match that reports every tracked nutrient except Vitamin D,
   **When** the user logs it, **Then** only the Vitamin D total is estimated,
   and every other total comes from USDA.

---

### User Story 2 - Totals use one consistent nutrient list (Priority: P1)

A user asks the coach "how much sodium did I have this week?" or opens the
Nutrient Check-up. The figures are built from the same fixed nutrient list,
under the same names and units, no matter how each food was matched. A food
that reports sugar under a different name still counts toward sugar.

**Why this priority**: Without one canonical list, totals silently drop values
recorded under a different name or unit. Every downstream view depends on this.

**Independent Test**: Seed a day with three items: one whose USDA data uses each
sugar spelling, and one estimated item. Confirm that the day's sugar total
equals the sum of all three.

**Acceptance Scenarios**:

1. **Given** items whose source reports the same nutrient under different names
   or units, **When** daily totals are computed, **Then** every item contributes
   to the single canonical nutrient, in that nutrient's canonical unit.
2. **Given** the fixed set, **When** the Check-up, the coaching answers or the
   analytics view report a tracked nutrient, **Then** they all use the same
   name, unit and value.

---

### User Story 3 - Know how much of a number is estimated (Priority: P2)

The user sees their weekly iron intake and a note such as "40% estimated". They
can then judge how far to trust the number, and the view does not imply false
precision.

**Why this priority**: Estimated values are less reliable than USDA values.
Being open about that preserves trust, but the totals are still useful without
it.

**Independent Test**: Seed a week in which half of the iron comes from estimated
foods. Confirm that the reported estimated share is about 50%.

**Acceptance Scenarios**:

1. **Given** a period whose totals include estimated values, **When** a nutrient
   total is shown, **Then** the share of that total that came from estimates is
   available alongside it.
2. **Given** a single logged meal, **When** its stored data is inspected,
   **Then** each tracked micronutrient records the meal total, how much of it
   was estimated, and how many of the meal's foods had a known value. This is
   not shown on the confirmation card (FR-014).

---

### Edge Cases

- **The estimate fails or times out**: The food is still logged with its
  calories and macros. The tracked micronutrients it lacks are recorded as
  "unknown", not zero, so totals and completeness figures stay honest.
- **The estimate is implausible**: An estimated value is outside a plausible
  range for the food's weight, for example 5 g of iron in 100 g of food. The
  value is rejected and recorded as "unknown". It is never stored as an
  extreme number.
- **USDA reports zero**: A USDA value of 0 is a real value, and it is kept and
  marked "USDA". Only a missing value triggers the fallback. A USDA zero is
  either "assumed zero" (not naturally present, such as fiber in meat), a lab
  measurement, or a recipe calculation. A small share are label-claim zeros,
  which by labelling rules mean "below the rounding threshold". These are also
  kept as 0.
- **Composite dishes**: A dish logged as one item gets one estimate for the
  whole dish, scaled to the logged weight.
- **Edited quantity before confirming**: When the user changes an item's
  weight on the confirmation card, every tracked micronutrient for that item
  rescales proportionally before the meal summary is computed.
- **Saved and reused meals**: A meal reused from the user's saved meals keeps the
  per-ingredient micronutrients and sources it was saved with, scaled to the
  chosen portion. Logging it does not trigger a new estimate.
- **Editing a saved meal**: When the user adds, removes or resizes an ingredient
  in a saved meal, the saved meal's micronutrient totals are recomputed from its
  ingredients. A newly added ingredient is resolved through the same
  USDA-then-estimate rule. Meals already logged from it do not change.
- **Deleting a logged meal**: The meal's whole summary leaves every total. No
  partial adjustment is needed.
- **The fixed set changes later**: Adding a nutrient to the set affects new logs
  immediately. Older meals show it as "unknown". There is no backfill.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST define one fixed set of tracked micronutrients.
  For each nutrient the set gives a canonical display name, a canonical unit,
  and the source names it accepts. Together with the existing macros (calories,
  protein, total carbohydrate and total fat), v1 tracks these 48 nutrients:
  - **Carbohydrate detail**: Fiber (g), Total sugars (g), Added sugars (g)
  - **Fat detail**: Saturated fat (g), Monounsaturated fat (g),
    Polyunsaturated fat (g), Trans fat (g)
  - **Other**: Alcohol (g), Cholesterol (mg), Salt (g), Sodium (mg), Water (g)
  - **Vitamins**: A (mcg RAE), B1 Thiamin (mg), B2 Riboflavin (mg), B3 Niacin
    (mg), B5 Pantothenic acid (mg), B6 (mg), B7 Biotin (mcg), B9/B11 Folate
    (mcg DFE), B12 (mcg), C (mg), D (mcg), E (mg), K (mcg)
  - **Minerals and trace elements**: Arsenic (mcg), Boron (mcg), Calcium (mg),
    Chloride (mg), Choline (mg), Chromium (mcg), Cobalt (mcg), Copper (mg),
    Fluoride (mcg), Iodine (mcg), Iron (mg), Magnesium (mg), Manganese (mg),
    Molybdenum (mcg), Phosphorus (mg), Potassium (mg), Rubidium (mcg),
    Selenium (mcg), Silicon (mg), Sulfur (mg), Tin (mcg), Vanadium (mcg),
    Zinc (mg)

  Fluoride and Fluorine are one nutrient (Fluoride). Biotin is one nutrient
  (Vitamin B7), even when a reference list shows it under both vitamins and
  minerals. This set is a superset of the US Nutrition Facts label.
- **FR-001a**: Each tracked nutrient MUST have a daily reference value, so
  every logged meal and every daily total can show a % Daily Value the way the
  label does. These values are the FDA label daily values where one exists.
  Nutrients without an FDA daily value show amounts only, with no % Daily
  Value. These are Trans fat, Total sugars, Monounsaturated and
  Polyunsaturated fat, Alcohol, Water, Salt, Fluoride, and the trace elements
  Arsenic, Boron, Cobalt, Rubidium, Silicon, Sulfur, Tin and Vanadium. Total sugars keeps
  the Check-up's existing 50 g proxy only where the Check-up already shows it.
- **FR-001b**: Added sugars MUST always carry the source "estimated", because
  the USDA data does not report it. Wherever the app shows added sugars, it
  MUST never be greater than total sugars for the same item.
- **FR-001c**: Salt MUST be calculated from Sodium (salt = sodium × 2.5) and
  never estimated separately. Its source is the same as Sodium's source.
- **FR-002**: While a meal is being resolved, every food item MUST have a
  value for each tracked micronutrient, or be explicitly marked "unknown".
- **FR-003**: When the item's USDA match reports a tracked nutrient, that USDA
  value MUST be used, including a reported value of 0. USDA always takes
  precedence over an estimate.
- **FR-004**: When the item has no USDA match, or its match does not report a
  tracked nutrient, the system MUST fall back to an AI-estimated value for each
  missing tracked nutrient, except the USDA-only nutrients in FR-004a.
- **FR-004a**: Arsenic, Boron, Cobalt, Rubidium, Silicon, Sulfur, Tin and
  Vanadium are USDA-only nutrients. They MUST NOT be AI-estimated. When USDA
  has no value for one of them, it is recorded as "unknown". Every other
  tracked nutrient, including Biotin, Iodine, Chromium, Molybdenum, Chloride,
  Fluoride and Added sugars, uses the AI fallback.
- **FR-005**: Each per-item value (in memory and in saved-meal ingredients)
  MUST carry its source: "USDA", "estimated" or "unknown". Each logged meal
  MUST store, for every tracked nutrient, a meal-level summary. The summary
  holds the total (the sum of known values), the part of that total that was
  estimated, and how many of the meal's foods had a known value out of how
  many foods in total. If no food has a known value, the nutrient is "unknown"
  for that meal, not 0.
- **FR-006**: The system MUST map every accepted source name and unit onto the
  canonical nutrient and unit. For example, each spelling of total sugars counts
  as Total sugars, and micrograms are recorded consistently.
- **FR-007**: The system MUST reject an estimated value that falls outside a
  plausible per-100 g range for that nutrient, and MUST record that nutrient as
  "unknown" instead.
- **FR-008**: A failed or slow estimate MUST NOT block or fail the meal log. The
  meal is logged, and the nutrients that could not be estimated are recorded as
  "unknown".
- **FR-009**: Asking for micronutrient estimates MUST NOT noticeably slow down
  logging. Estimates are gathered together with the existing calorie and macro
  estimate, or in parallel with it, not one after another.
- **FR-010**: The Nutrient Check-up, coaching answers and the analytics view
  (spec 004) MUST read tracked micronutrients from this fixed set. Their
  completeness and estimated-share figures MUST use the meal-level summaries.
- **FR-011**: The system MUST record which source an estimated value came from
  in its usual telemetry. This lets the estimate rate and the rejection rate be
  monitored.
- **FR-012**: There is no backfill. Meals logged before this feature are left
  unchanged, and any tracked micronutrient they lack is treated as "unknown".
- **FR-013**: Values MUST scale with the item's logged weight. Changing the
  weight before confirming, or choosing a portion of a saved meal, MUST rescale
  every tracked micronutrient.
- **FR-014**: The meal confirmation card MUST NOT display tracked
  micronutrients or their sources on any client. It keeps showing only
  calories and macros, as it does today. Tracked micronutrients MUST be
  resolved and saved when the meal is logged, with no user action and no
  notice. They may travel with the card's data, so that confirming, editing
  or saving the meal keeps them intact.
- **FR-014a**: Logged meals MUST store tracked micronutrients only as
  meal-level summaries (FR-005), not per food item. Saved meals MUST store them
  per ingredient only. A saved meal's micronutrient totals MUST be computed
  from its ingredients when read, and never stored next to them.
- **FR-015** *(visualization readiness)*: The nutrient catalogue MUST be
  available to every client from one source. For each tracked nutrient it
  gives a stable key, display name, unit, display group (Carbohydrate detail,
  Fat detail, Other, Vitamins, Minerals), display order, daily reference value
  (if any), and direction (a limit to stay under, a target to reach, or
  neither). Clients MUST NOT hard-code this list.
- **FR-016** *(visualization readiness)*: Nutrient keys MUST be stable. A key
  is never renamed or reused, and nutrients are only ever added or retired,
  so stored history stays readable by future charts.
- **FR-017** *(visualization readiness)*: For any user, any date range up to
  365 days and any subset of tracked nutrients, the system MUST be able to
  produce per-day totals, each with its estimated portion and completeness,
  and per-meal contributions. Days with no logged meals MUST come out as "no
  data", not 0. These totals MUST follow the app's existing nutrition-day
  boundary.
- **FR-018** *(single source of truth)*: No micronutrient data may be stored
  twice:
  - Logged meals keep only the meal-level summary (no per-item values).
  - Saved meals keep only per-ingredient values (no stored totals).
  - Per-day and per-period totals are computed from logged meals when read,
    never stored as a second copy. A cache is allowed only if it is
    disposable and rebuilt from the logged meals.
  - The nutrient catalogue (FR-015) is the only definition of tracked
    nutrients, units and daily values. It replaces the Check-up's separate
    micronutrient list and daily values, rather than sitting next to them.
  - A meal logged from a saved meal stores its own summary. This is a
    deliberate historical snapshot, not a duplicate: editing the saved meal
    later MUST NOT change meals already logged.
- **FR-019** *(backward compatibility)*: Moving logged meals from per-item to
  meal-level micronutrients MUST NOT break any existing feature. The
  dependency audit on 2026-10-03 found these, and each MUST keep working:
  - **Nutrient Check-up (nightly), Mindful panel and coaching** read per-item
    nutrients from logged meals today. They MUST switch to the meal-level
    summaries and the shared catalogue in the same release, never one without
    the other.
  - **"Log again" from a logged meal (Android meal detail)** re-sends the
    logged meal's items to the log endpoint. Today those items carry their
    nutrients. Logging MUST derive each item's tracked micronutrients on the
    server (USDA by food id, otherwise the cached estimate by food name)
    whenever an item arrives without them. A re-logged meal MUST therefore end
    up with the same summary as the original, scaled to the portion.
  - **Third-party integration feed** (read-only meal export for external
    consumers) returns logged-meal items with per-item nutrients. The feed
    MUST expose the meal-level summaries instead, and the change MUST be
    documented in the integration API docs before release.
  - **Meal detail (web and Android)** returns a logged meal's items. Clients
    treat item nutrients as optional, opaque extras, so removing them MUST NOT
    change what either client shows.
  - **Saved meals and the confirmation card** keep per-item values (FR-014a),
    so saving, editing and logging a saved meal keep working unchanged.
  - **The nightly Check-up table** stores its own daily aggregates. It counts
    as a disposable cache under FR-018, because it is rebuilt from logged
    meals.
  - **Seed scripts, the mobile API docs and existing tests** that build or
    assert per-item nutrients on logged meals MUST be updated in the same
    change.

### Key Entities *(include if feature involves data)*

- **Tracked Micronutrient**: One entry in the fixed set. It has a stable key,
  canonical display name, canonical unit, the source names it accepts, a
  plausible per-100 g range, a display group and order, a direction (limit,
  target or neither), whether it is USDA-only, and its daily reference value
  (shared with the Check-up).
- **Item Micronutrient Value**: The amount of one tracked micronutrient in one
  food item. It has an amount in the canonical unit and a source of USDA,
  estimated or unknown. It exists while a meal is being resolved and inside
  saved-meal ingredients. It is not kept on logged meals.
- **Meal Micronutrient Summary**: For one logged meal and one tracked nutrient,
  it holds the total, the estimated portion of that total, and coverage
  (foods with a known value out of all foods). It is the only stored
  micronutrient data on a logged meal.
- **Micronutrient Estimate**: An AI-produced set of per-100 g values for a food,
  covering the tracked micronutrients that USDA could not provide. It may be
  reused for the same food name.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For meals logged after launch, at least 98% of foods contribute
  a known value (USDA or estimated) to every tracked micronutrient, except the
  USDA-only nutrients (FR-004a). Today about 71% of new items carry any
  micronutrients at all.
- **SC-002**: On every client, the confirmation card shows no
  micronutrient rows or source labels, and its layout is unchanged from before
  launch. Yet 100% of meals confirmed through it are saved with the full
  fixed set.
- **SC-003**: The median time to log a meal increases by no more than 10%
  compared with before launch.
- **SC-004**: On a benchmark of at least 50 foods with known USDA values, at
  least 70% of the estimated tracked values fall within ±50% of the USDA value
  when the estimate is forced. This means the fallback is in the right
  ballpark.
- **SC-005**: Total sugars for a seeded day are identical whichever sugar
  spelling each item's source used. There are zero dropped contributions.
- **SC-006**: For the same user and period, the Check-up, coaching and
  analytics all report the same value for every tracked nutrient.
- **SC-007**: For any logged meal, every row of a standard Nutrition Facts
  label (calories through potassium, including % Daily Value where one is
  defined) can be filled from the stored data with no blank rows.
- **SC-008**: Producing per-day totals for all 48 tracked nutrients over 90 days
  for one user returns in under 1 second at the 95th percentile. That is fast
  enough for a future chart screen.
- **SC-009**: A prototype chart can render every nutrient group, in order and
  with daily-value lines, using only the shared catalogue (FR-015) and the
  per-day totals (FR-017). It needs no client-side nutrient list and no change
  to stored data.
- **SC-010**: After the change, every existing automated test suite passes
  (backend, web and Android unit/screenshot tests), updated only where it
  asserted the old per-item shape. A meal logged, then logged again from its
  detail screen, has identical micronutrient totals at portion 1.

## Assumptions

- The v1 fixed set matches the full nutrient list of the reference
  food-tracking app shared on 2026-10-03, which goes beyond the US Nutrition
  Facts label. Other USDA nutrients, such as individual fatty-acid chains or
  amino acids, are not stored on logged or saved meals. They are still
  available from the bundled USDA catalogue by food id (FR-018).
- USDA coverage in the bundled catalogue (13,694 foods) falls into four
  bands. 33 nutrients are reported for at least 70% of foods. Pantothenic
  acid, Manganese and Trans fat are reported for 30–51%. Biotin, Fluoride,
  Iodine, Molybdenum, Boron, Cobalt and Sulfur are reported for under 5%.
  Added sugars, Arsenic, Chloride, Chromium, Rubidium, Silicon, Tin and
  Vanadium are never reported. The last two bands therefore depend almost
  entirely on the fallback. SC-004 accuracy is measured only on the nutrients
  USDA can benchmark.
- Fiber and saturated fat already exist as macro-level values. They join the
  set so that they get the same fallback and source labelling. Their existing
  behaviour does not change.
- For a USDA match, "USDA available" means the food was matched with the
  app's existing confidence rules. Low-confidence matches that the user has not
  confirmed are treated like any other match.
- Estimated values are generic per-100 g amounts for the named food. They are
  not personalised, and they are not adjusted for preparation method beyond
  what the food name says.
- Estimated micronutrient values may be cached and reused by food name, in the
  same way calorie and macro estimates already are.
- The estimated-share figure (User Story 3) is a data capability. Micronutrient
  visualization (charts, the full nutrient list) is a separate, later feature.
  This spec only makes the data and catalogue ready for it (FR-015 to FR-017).
- Because logged meals keep only meal-level summaries, any "top contributors"
  view (spec 004, User Story 3) attributes intake to meals, such as "Tuesday
  lunch", not to individual foods. Spec 004 should be updated to match.
- Pre-existing duplication is out of scope for this feature but noted for
  later cleanup. Logged meals store macro totals as columns and again per
  item. Saved meals store macro totals as columns next to their ingredients.
  This feature must not add to either pattern.
- Medical accuracy is out of scope. Values support general awareness, not
  clinical decisions.
- The app is in development, not in production. Existing logged data,
  including the test-fixture items with fake food ids, is not migrated or
  cleaned up by this feature.
