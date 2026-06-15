# Pregnancy Features — Requirements

> Status: **draft / not yet implemented**. This is a requirements & spec
> document, not an implementation plan. Mirrors the style of
> [`architecture.md`](./architecture.md) and references real tables, columns,
> and modules in `src/backend`.

---

## 1. Purpose & scope

NutriChat already tracks meals, macros, and a small set of micronutrients
against per-user goals (`user_goal`), and flags "junk" meals via
`agent/tools/meals.py`. Pregnancy features extend this with:

- A **pregnancy profile** capturing pregnancy status and trimester.
- **Adjusted nutrition targets** (kcal, protein, fiber, and new micronutrient
  goals) that scale by trimester.
- **Foods-to-avoid flagging** for pregnancy-risky items (high-mercury fish,
  raw/undercooked foods, unpasteurized dairy, deli meats, excess caffeine,
  high-dose vitamin A/liver, alcohol), surfaced via `meal_log.flags`.
- **Coaching adaptations**: pregnancy-aware tone, trimester-appropriate meal
  plans, and warnings when a logged or suggested food is flagged.
- **Onboarding/Settings UX** to capture pregnancy status, due date (or LMP),
  and explicit consent to a medical disclaimer.

### 1.1 NOT medical advice — safety framing (read this first)

> **This is the single most important constraint in this spec.** NutriChat is
> a logging and coaching tool, not a clinical service. Pregnancy nutrition has
> real safety stakes (listeriosis, mercury exposure, vitamin A toxicity,
> alcohol, gestational diabetes management). Every pregnancy-related surface
> MUST:
>
> 1. Display a persistent, unambiguous disclaimer: *"NutriChat is not a
>    medical service. Always follow the guidance of your OB/GYN, midwife, or
>    registered dietitian — especially for any condition (e.g. gestational
>    diabetes, food allergies) or if advice here conflicts with theirs."*
> 2. Never diagnose, prescribe calorie/weight targets for medical reasons, or
>    contradict a clinician's instructions.
> 3. Treat foods-to-avoid flags as *informational reminders*, not a
>    medical-grade safety system — false negatives (missed risky foods) are
>    expected and the copy must say so ("this list isn't exhaustive — when in
>    doubt, ask your provider").
> 4. Require explicit user opt-in/consent before enabling pregnancy mode (see
>    §6), and make it trivially easy to turn off.
> 5. For gestational diabetes specifically: NutriChat must NOT attempt to
>    manage blood-sugar targets. It may surface that the user has indicated
>    GD (so coaching avoids contradicting a low-glycemic diet plan) but must
>    explicitly say meal-timing/carb targets should come from their care team.

### 1.2 What we will build (this spec)

- Pregnancy profile data model (new table + `user_goal` additions).
- Trimester-aware adjusted goals (existing macro goals + new micronutrient
  goal columns).
- Pregnancy-risk food flagging extending the existing junk-flag pattern.
- Coaching prompt/tunables additions for pregnancy-aware responses.
- Onboarding and Settings UX for capturing/editing pregnancy status.
- Integration-API and Telegram touchpoints.
- Phased rollout (v1 vs later) and open questions.

### 1.3 What we will NOT build (this spec / v1)

- Clinical decision support (e.g. GD carb-counting protocols, insulin
  dosing).
- Automated detection of pregnancy from conversation (user must explicitly
  set status — no inference from messages).
- Symptom tracking (nausea, contractions, kick counts) — out of scope for a
  nutrition app.
- Postpartum/lactation tracking (deferred to "later", §8).
- A full USDA-derived micronutrient ledger for every nutrient (deferred,
  §8) — v1 tracks targets for a fixed list of pregnancy-relevant
  micronutrients only (folate, iron, calcium, iodine, choline, omega-3/DHA,
  vitamin D), reusing the existing `entities` JSONB on `meal_log` for actuals
  where USDA data already provides them.
- Per-trimester week-by-week content/tips library (deferred).

---

## 2. Pregnancy profile data model

### 2.1 New table: `pregnancy_profile`

A new table, **not** new columns crammed into `user_goal`, because pregnancy
status is optional, time-bound, and has its own lifecycle (one user may have
multiple pregnancies over time — though only one "active" row at a time).
Follows the conventions in `src/backend/db/models.py` (UUID PK pattern,
`server_default=func.now()`, `onupdate=func.now()`).

```python
class PregnancyProfile(Base):
    """Pregnancy status and derived trimester info for a user.

    Written by the onboarding/settings APIs. Read by build_context() and
    coaching.fetch_data() to adjust goals and coaching tone. At most one
    ACTIVE row per user — enforced at the application layer (see §2.3).
    """

    __tablename__ = "pregnancy_profile"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("user_goal.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="not_pregnant"
    )
    # "not_pregnant" | "pregnant" | "postpartum" (postpartum reserved for
    # later phase — see §8 — but the enum value is reserved now so the
    # column doesn't need a migration later).

    # Derive trimester from EITHER due_date OR lmp_date (last menstrual
    # period). At least one must be set when status == "pregnant".
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    lmp_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    pre_pregnancy_weight_kg: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )

    # Free-form flags relevant to nutrition coaching, e.g.
    # {"gestational_diabetes": true, "multiples": false,
    #  "high_risk": false}. Vegetarian/vegan/allergy info is NOT duplicated
    # here — it already lives in user_goal.dietary_prefs.
    conditions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # User consent to the "not medical advice" disclaimer — required before
    # pregnancy mode activates (see §1.1, §6).
    disclaimer_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_pregnancy_profile_user_id", "user_id"),
        # Partial unique index restricting to one row where status='pregnant'
        # per user — created via raw DDL in the Alembic migration, same
        # pattern as the IVFFlat index note on meal_log.
    )
```

### 2.2 Trimester derivation (application logic, not stored)

Trimester is **derived at read time**, never stored, so it stays correct as
time passes without a cron job:

- Gestational age (weeks) = `(today - lmp_date).days / 7` if `lmp_date` set,
  else derived from `due_date` (`lmp_date ≈ due_date - 280 days`).
- Trimester 1: weeks 0–13. Trimester 2: weeks 14–27. Trimester 3: weeks 28+.
- If gestational age > ~42 weeks or < 0, treat as stale data and prompt the
  user to update `due_date` (handled in Settings, §6).

### 2.3 `user_goal` additions

No new columns on `user_goal` itself — `dietary_prefs` (JSONB) already
covers vegetarian/vegan/allergies and is reused as-is. `kcal_goal`,
`protein_goal`, `fiber_goal` remain the *base* (non-pregnant) targets; §3
covers how pregnancy adjustments layer on top without overwriting these.

### 2.4 New table: `pregnancy_nutrient_goal` (micronutrient targets)

```python
class PregnancyNutrientGoal(Base):
    """Per-trimester micronutrient targets, seeded from a reference table.

    Static reference data (not user-specific) — one row per
    (trimester, nutrient). Read by coaching.fetch_data() when
    pregnancy_profile.status == "pregnant" to compare against logged
    micronutrient totals (meal_log.entities, via
    get_micronutrients_for_range — see §3.2).
    """

    __tablename__ = "pregnancy_nutrient_goal"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    trimester: Mapped[int] = mapped_column(Integer, nullable=False)  # 1, 2, 3
    nutrient: Mapped[str] = mapped_column(String(50), nullable=False)
    # Matches the USDA nutrient identifiers already used in
    # meal_log.entities / get_micronutrients_for_range, e.g.
    # "Folate, DFE", "Iron, Fe", "Calcium, Ca", "Iodine, I", "Choline,
    # total", "Vitamin D (D2 + D3)". For omega-3/DHA, see §3.3 (USDA
    # coverage caveat).
    daily_target: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(10), nullable=False)  # mg, mcg, g

    __table_args__ = (
        UniqueConstraint(
            "trimester", "nutrient", name="uq_pregnancy_nutrient_goal"
        ),
    )
```

This table is **seed data**, not user data — populated once via the Alembic
migration's `data` upgrade step (or a small seed script), sourced from
established prenatal nutrition guidance (e.g. ACOG / NIH ODS reference
intakes). It is intentionally separate from `user_goal` so the reference
values can be updated without touching per-user rows.

### 2.5 Alembic migration note

A new migration under `src/backend/db/migrations/versions/` (schema applied
to Supabase Postgres per the existing pattern) must:

1. Create `pregnancy_profile` with FK to `user_goal.user_id` (CASCADE
   delete, matching `MealLog`/`UserMemory`/etc.).
2. Create the partial unique index enforcing at most one
   `status='pregnant'` row per user (raw DDL — same pattern noted for the
   IVFFlat index on `meal_log`).
3. Create `pregnancy_nutrient_goal` and seed it with reference rows for
   trimesters 1–3 (folate, iron, calcium, iodine, choline, omega-3/DHA,
   vitamin D — plus elevated kcal/protein deltas, see §3.1).
4. Enable RLS on `pregnancy_profile` matching `user_goal`'s existing policy
   (owner-only read/write via Supabase Auth UUID); `pregnancy_nutrient_goal`
   is reference data — read-only for all authenticated users, service-role
   writes only (matches `integration_token`/`telegram_link` posture for
   service-managed tables).

---

## 3. Adjusted nutrition goals

### 3.1 Macro adjustments (kcal / protein / fiber)

`UserGoal.kcal_goal`, `protein_goal`, `fiber_goal` stay as the user's
*base* goals (set at onboarding via TDEE calc in `OnboardingPage.tsx`).
When `pregnancy_profile.status == "pregnant"`, **effective goals** are
computed as base + trimester delta, applied wherever goals are currently
read (`coaching.fetch_data()` `include_goals` branch, `api/goals.py`
`GET /goals`, integration API `/v1/integrations/goals`):

| Trimester | kcal delta | Protein delta | Fiber |
|---|---|---|---|
| 1 (weeks 0–13) | +0 kcal/day | +0 g/day (still ~+1g/kg bodyweight overall, but trimester-1 increment is negligible) | unchanged |
| 2 (weeks 14–27) | +340 kcal/day | +25 g/day | unchanged (still target ~25–28g) |
| 3 (weeks 28+) | +450 kcal/day | +25 g/day | unchanged |

These deltas are stored as **constants in `config/tunables.yaml`** (new
`pregnancy` section, alongside `junk`/`summaries`), not hardcoded, so they
can be tuned without a migration:

```yaml
pregnancy:
  kcal_delta_by_trimester: {1: 0, 2: 340, 3: 450}
  protein_delta_g_by_trimester: {1: 0, 2: 25, 3: 25}
```

**Where this needs to extend:**
- `coaching.fetch_data()` — when `parsed.include_goals` and the user has an
  active pregnancy profile, fetch `pregnancy_profile` alongside `UserGoal`,
  compute trimester, and return an `effective_goals` block (base goals +
  deltas) in addition to (or instead of) the raw `goals` block, so
  `generate_response()` compares against the *adjusted* targets.
- `api/goals.py` `GET /goals` — optionally add an `effective_kcal_goal` /
  `effective_protein_goal` to `GoalResponse` for the frontend dashboard
  (MacroRing components), computed server-side from `user_goal` +
  `pregnancy_profile`. Base `kcal_goal`/`protein_goal` in `user_goal` are
  **never overwritten** — pregnancy is additive and reversible.

### 3.2 New micronutrient targets

`pregnancy_nutrient_goal` (§2.4) supplies per-trimester daily targets for:

| Nutrient (USDA name) | Why it matters in pregnancy |
|---|---|
| Folate, DFE | Neural tube defect prevention — critical trimester 1 |
| Iron, Fe | Increased blood volume, anemia prevention |
| Calcium, Ca | Fetal skeletal development |
| Iodine, I | Fetal brain/thyroid development |
| Choline, total | Fetal brain development |
| Omega-3/DHA | Fetal brain/eye development (see §3.3 USDA caveat) |
| Vitamin D (D2 + D3) | Calcium absorption, immune function |

`coaching.fetch_data()` already supports arbitrary micronutrient queries via
`get_micronutrients_for_range()` against `meal_log.entities` (JSONB). The
extension: when the user has an active pregnancy profile and asks a
micronutrient question (or asks "am I getting enough X"), join the fetched
totals against `pregnancy_nutrient_goal` for the user's current trimester
(instead of, or in addition to, the existing `dietary_prefs`/macro-only
`include_goals` path).

### 3.3 USDA coverage caveat (flag for v1, resolve before shipping)

Not all USDA FoodData Central entries carry "Choline, total" or
omega-3/DHA-specific fields consistently — coverage is sparser than for
macros, iron, or vitamin D. **v1 must verify actual coverage** in
`food_source.nutrients` for commonly-logged foods before promising tracking
for choline/omega-3; if coverage is too sparse, those two nutrients should
ship as "target shown, but tracking may be incomplete" rather than silently
reporting 0 (which the existing coaching prompt already phrases naturally —
see `coaching_response_system` micronutrient-zero rule — but pregnancy
copy should add "USDA data for this nutrient is often missing, so this total
may understate your actual intake").

---

## 4. Foods-to-avoid flagging

### 4.1 Extending `meal_log.flags`

`meal_log.flags` is JSONB, currently `{"has_junk": bool, "junk_items":
[...]}` written by `_junk_flags()` in `agent/tools/meals.py`. Add a parallel
key, **only populated when the logging user has an active pregnancy
profile**:

```json
{
  "has_junk": false,
  "junk_items": [],
  "pregnancy_risk": {
    "has_risk": true,
    "items": [
      {"food_name": "Tuna, bigeye, raw", "reason": "high_mercury_fish"}
    ]
  }
}
```

This mirrors the existing `_is_junk` / `_junk_flags` pattern: a new
`_pregnancy_risk_flags(usda_results, is_pregnant)` helper that:

1. Returns `{}` (key omitted entirely) if `is_pregnant` is false — keeps
   `meal_log.flags` unchanged for the vast majority of users, no schema
   migration needed for existing rows.
2. Otherwise checks each resolved `USDAResult.food_name` against a
   **reference list** of risk categories (new `pregnancy.risky_foods`
   section in `tunables.yaml`, same spirit as `junk` thresholds):

```yaml
pregnancy:
  risky_food_categories:
    high_mercury_fish:
      match_terms: ["shark", "swordfish", "king mackerel", "tilefish",
                     "bigeye tuna", "marlin"]
      reason: "High-mercury fish — limit during pregnancy"
    raw_undercooked:
      match_terms: ["raw", "sushi", "tartare", "carpaccio", "soft-boiled",
                     "runny yolk", "rare"]
      reason: "Raw or undercooked — listeriosis/salmonella risk"
    unpasteurized_dairy:
      match_terms: ["unpasteurized", "raw milk", "queso fresco",
                     "soft cheese"]
      reason: "Unpasteurized dairy or soft cheese — listeriosis risk"
    deli_meat:
      match_terms: ["deli", "lunch meat", "cold cut", "prosciutto", "salami"]
      reason: "Deli/cured meat — heat before eating to reduce listeria risk"
    high_caffeine:
      match_terms: ["coffee", "espresso", "energy drink", "matcha"]
      reason: "Caffeine — keep total under ~200mg/day"
    vitamin_a_liver:
      match_terms: ["liver", "pâté", "liverwurst"]
      reason: "High preformed vitamin A — limit frequency"
    alcohol:
      match_terms: ["beer", "wine", "cocktail", "liquor", "spirits"]
      reason: "Alcohol — no safe amount established in pregnancy"
```

3. Detection is **substring match on `food_name`** (same Jaccard-adjacent,
   no-LLM approach as `classify_intent`), case-insensitive — cheap,
   deterministic, runs at log time alongside `_junk_flags`. This is
   intentionally a heuristic, not exhaustive (per §1.1 — copy must say so).
   Caffeine is special-cased: rather than a binary flag per item, accumulate
   an estimated daily caffeine total (USDA "Caffeine" nutrient field where
   present) and flag when the **daily total** crosses the threshold — this
   requires a small extension beyond the per-item pattern (see open
   questions, §9).

### 4.2 Surfacing in coaching

`coaching.fetch_data()` micronutrient/food paths already read
`meal_log.entities`; extend `get_food_breakdown_for_range()` (or add a
sibling) to also surface `flags.pregnancy_risk` items for the requested
period, alongside the existing `flagged_junk_foods` block — so
`generate_response()` can answer "did I eat anything I shouldn't have this
week?" type questions, and the confirmation-card flow
(`format_confirmation_card()`) can show an inline `⚠️ pregnancy` marker next
to a risky item at log time (before the user even confirms), giving the
user a chance to correct/remove it — same UX as the existing low-confidence
`⚠` marker.

---

## 5. Coaching agent adaptations

### 5.1 `coaching_response_system` (tunables.yaml) additions

The existing prompt already has a `<capabilities>`, `<examples>`, and
`<rules>` structure. Pregnancy mode adds:

- **Context injection**: when `pregnancy_profile.status == "pregnant"`,
  `fetch_data()` includes a `pregnancy` block in the data passed to
  `generate_response()`:
  ```json
  {"pregnancy": {"trimester": 2, "weeks": 18,
    "conditions": {"gestational_diabetes": false},
    "effective_goals": {"kcal_goal": 2540, "protein_goal": 151},
    "micronutrient_targets": {"Iron, Fe": 27, "Folate, DFE": 600}}}
  ```
- **New rule** (appended to `<rules>`): *"If `data.pregnancy` is present,
  factor trimester and any flagged conditions into tone and target
  comparisons — use the `effective_goals` and `micronutrient_targets` from
  `data.pregnancy` instead of `data.goals` for macro/micronutrient
  comparisons. Never use the word 'diagnose' or suggest a medical
  intervention; for gestational-diabetes-flagged users, do not propose
  specific carb-timing — defer to their care team for carb/meal-timing
  protocols, but food *suggestions* and *risk flags* are still fine."*
- **Meal-plan / recipe-card rule extension**: when generating the existing
  recipe-card meal plan (§ in current prompt), additionally (a) bias food
  choices toward closing the iron/folate/protein gaps highlighted in
  `micronutrient_targets`, and (b) never include an item present in
  `data.pregnancy_risk_items` for that period.
- **Disclaimer reminder**: a short, non-repetitive disclaimer should NOT be
  appended to every single message (that would be noisy and erode trust per
  `coaching_hard_constraints`'s "keep responses under 4 sentences"). Instead,
  the disclaimer is shown persistently in the UI (chat header banner, §6),
  and the LLM-side rule only triggers a *contextual* disclaimer sentence for
  clinical-adjacent questions (gestational diabetes, supplements, medication)
  — reusing the existing "Refusals" rule pattern.

### 5.2 Example pregnancy Q&A pairs (for the prompt's `<examples>` block)

```
<example>
<query>Am I getting enough iron?</query>
<data>{"micronutrients": {"Iron, Fe": 12.4}, "pregnancy": {"trimester": 2,
  "micronutrient_targets": {"Iron, Fe": 27}}}</data>
<ideal_answer>You've logged about 12.4mg of iron, which is roughly half of
the 27mg/day typically recommended in your second trimester — iron-rich
foods like lean red meat, lentils, or fortified cereal (paired with
vitamin C) can help close that gap. Your prenatal vitamin may also
contribute iron not captured here.</ideal_answer>
</example>

<example>
<query>I just had a tuna sandwich for lunch, is that okay?</query>
<data>{"pregnancy_risk_items": [{"food_name": "Tuna salad", "reason":
  "high_mercury_fish"}], "pregnancy": {"trimester": 3}}</data>
<ideal_answer>Tuna is fine in moderation during pregnancy, but it's worth
keeping an eye on — lighter tuna (skipjack/canned light) is lower in mercury
than albacore or bigeye, and most guidance suggests limiting tuna to a
couple of servings a week. If you're unsure how much is safe for you, your
OB or midwife can give specific guidance.</ideal_answer>
</example>

<example>
<query>Give me a meal plan for today, I'm in my third trimester.</query>
<data>{"today_totals": {"kcal": 1400, "protein_g": 70, "fiber_g": 14,
  "n_meals": 2}, "pregnancy": {"trimester": 3, "effective_goals":
  {"kcal_goal": 2650, "protein_goal": 151, "fiber_goal": 28},
  "micronutrient_targets": {"Iron, Fe": 27, "Calcium, Ca": 1000}}}</data>
<ideal_answer>
**🥗 Your plan to hit today's goals**

_Remaining today: 81g protein · 14g fiber · 1250 kcal_

**🍽️ Dinner**
- Grilled salmon, 150g — ~33g protein, ~280 kcal (also a great DHA source)
- Cooked lentils, 1 cup — ~18g protein, ~16g fiber, ~230 kcal
- Steamed broccoli, 1 cup — ~3g protein, ~3g fiber, ~55 kcal

**🥜 Snack**
- Greek yogurt with almonds — ~20g protein, ~250 kcal (calcium boost)

**Daily total: ~74g protein · ~17g fiber · ~815 kcal**
</ideal_answer>
</example>

<example>
<query>I was just diagnosed with gestational diabetes, what should I eat?</query>
<data>{"pregnancy": {"trimester": 2, "conditions": {"gestational_diabetes":
  true}}}</data>
<ideal_answer>Congrats on getting that flagged early — gestational diabetes
really needs a personalized meal-timing and carb plan from your OB or a
registered dietitian, since targets vary a lot person to person. I can still
help you log meals and keep an eye on protein and iron, but please follow
your care team's specific carb guidance over anything general I'd
suggest.</ideal_answer>
</example>
```

---

## 6. Onboarding / Settings UX

### 6.1 OnboardingPage (`frontend/src/pages/OnboardingPage.tsx`)

Add an optional **Step 0 (or appended to Step 1)**: "Are you currently
pregnant?" — toggle, defaulting to off/not asked (never assume). If yes:

- Show the disclaimer banner (§1.1 text) with a required checkbox: "I
  understand NutriChat is not a substitute for medical advice and will
  consult my OB/midwife/dietitian for personalized guidance." — maps to
  `pregnancy_profile.disclaimer_accepted_at`.
- Capture **due date** (date picker) OR **first day of last period (LMP)** —
  either is sufficient (per §2.2). Show derived trimester immediately as
  feedback ("You're currently in trimester 2, week 18").
- Optional: pre-pregnancy weight (kg) — used as a TDEE baseline reference,
  not surfaced elsewhere in v1.
- Optional: conditions checkboxes — "Gestational diabetes", "Carrying
  multiples" (maps to `pregnancy_profile.conditions` JSONB).
- On submit, `POST /pregnancy-profile` (new endpoint, mirrors
  `POST /goals` in `api/goals.py`) creates the `pregnancy_profile` row
  alongside the existing `POST /goals` call. Base `kcal_goal`/`protein_goal`
  from the TDEE calc (`calculateTDEE`) are still computed the same way —
  pregnancy deltas are applied at *read* time (§3.1), not baked into the
  stored base goal.

### 6.2 SettingsPage (`frontend/src/pages/SettingsPage.tsx`)

A new "Pregnancy" card (alongside the existing Goals, Preferences, Telegram
cards), following the same `Card`/`CardHeader`/`CardContent` pattern:

- Toggle pregnancy status on/off at any time (off → `status =
  "not_pregnant"`, effective goals revert to base immediately).
- Edit due date / LMP, conditions.
- Persistent disclaimer text (always visible when pregnancy mode is on, not
  just at consent time) — small `ShieldAlert`-icon banner (icon already
  imported in `SettingsPage.tsx` for the bypass-auth warning, same visual
  language).
- `PUT /pregnancy-profile` mirrors `PUT /goals`.
- Display the *effective* goals (base + trimester delta) read-only here so
  users understand why their dashboard numbers changed.

---

## 7. Integration touchpoints

### 7.1 Meal logging (`agent/tools/meals.py`)

- `_insert_meal_log()` needs the caller's pregnancy status to compute
  `_pregnancy_risk_flags()`. `log_meal()` already receives `user_id` — the
  orchestrator/graph layer fetches `pregnancy_profile` once per turn (cached
  alongside the existing `build_context()` Postgres reads, not a second
  round trip if avoidable) and passes `is_pregnant: bool` through to
  `log_meal()`.

### 7.2 Daily / weekly summaries (`workers/tasks.py`)

- `DailySummary` / `WeeklySummary` are not modified in v1 (no new columns) —
  but `aggregate_daily_summary` should additionally roll up
  `flags.pregnancy_risk.has_risk` counts into `weekly_summary.weak_spots`
  (already an `ARRAY(String)`, e.g. append `"pregnancy_risk_foods"` as a
  weak-spot label) using the existing `weak_spot_ratio`/`missed_meal_min_days`
  tunables pattern — gated on the user having an active pregnancy profile at
  aggregation time.

### 7.3 `/v1/integrations/*` (lifeOS feeds)

`docs/integration-api.md` documents `GET /v1/integrations/goals` (via
`IntegrationGoals`) and `/meals`, `/daily-summary`, `/weekly-summary`.
**v1 decision**: expose pregnancy status and effective goals through
`/v1/integrations/goals` as additive optional fields:

```json
{
  "kcal_goal": 2200, "protein_goal": 126, "fiber_goal": 30,
  "pregnancy": {
    "status": "pregnant", "trimester": 2,
    "effective_kcal_goal": 2540, "effective_protein_goal": 151
  }
}
```

`pregnancy` is `null`/omitted for non-pregnant users — fully backward
compatible with existing consumers. `meal_log` rows already carry `flags`
in `entities`/`flags` JSONB exposed via `/meals` — `pregnancy_risk` flows
through automatically since `/meals` already serializes the full `flags`
column (verify field is included in `IntegrationMeal`-equivalent response
model when implementing).

### 7.4 Telegram coaching (`telegram/`)

No new commands required for v1 — pregnancy status is set via the web
Settings page only (consent/disclaimer UX is easier to do well on web).
`handle_message()` already routes Telegram messages through the same
`CoachingAgent`/`orchestrator`, so pregnancy-aware responses and risk-flag
warnings on the confirmation card (`format_confirmation_card()`) work
automatically once the backend changes land — Telegram is a pure pass-through
client here, no special-casing needed.

---

## 8. Phased scope

### v1 (must-have)

- `pregnancy_profile` table + migration (§2.1, §2.5), RLS owner-only.
- `pregnancy_nutrient_goal` reference table + seed data (§2.4).
- Onboarding step + Settings card for pregnancy status, due date/LMP,
  conditions, and **mandatory disclaimer consent** (§6).
- Trimester derivation + adjusted kcal/protein goals surfaced in
  `coaching.fetch_data()` and `GET /goals` (§3.1).
- Micronutrient targets (folate, iron, calcium, iodine, vitamin D — choline
  and omega-3/DHA contingent on the USDA coverage check in §3.3) compared
  against logged totals in coaching responses.
- `pregnancy_risk` flag extension to `meal_log.flags`, with the reference
  list in §4.1 (excluding the caffeine daily-total special case — ship as a
  per-item flag only in v1, see §9).
- Coaching prompt updates: pregnancy context block, trimester-aware tone,
  risk-aware meal plans, gestational-diabetes deferral (§5).
- Confirmation-card inline warning for flagged items (§4.2).
- Persistent disclaimer banner wherever pregnancy mode is active.

### Later (post-v1)

- Caffeine running-daily-total tracking (requires summing across meals
  intra-day — a small new Redis/Postgres aggregate, similar to
  `increment_today`).
- Choline / omega-3/DHA tracking once USDA coverage is verified — or
  supplement with a curated food-level lookup table if FDC coverage is too
  sparse.
- Week-by-week pregnancy tips/content library (would need new content
  storage — out of scope for the nutrition-tracking core).
- Postpartum/lactation mode — `pregnancy_profile.status = "postpartum"` is
  reserved in the enum (§2.1) but targets/flags for lactation are not
  defined in this spec.
- `/v1/integrations` exposing `pregnancy_risk` summaries as a first-class
  field (v1 relies on it flowing through existing `flags`/`entities`
  passthrough).
- Telegram-specific pregnancy commands (e.g. `/pregnancy status`).

### Risks

- **False sense of safety**: users may over-trust the `pregnancy_risk` flag
  as exhaustive. Mitigated by persistent "not exhaustive, ask your provider"
  copy (§1.1) and by *never* claiming a food is "safe" — only flagging known
  risk categories.
- **Substring-match false positives/negatives**: e.g. "tuna salad sandwich"
  vs. "tuna casserole, canned light tuna" — canned light tuna is lower-risk
  but would still match `"tuna"`-adjacent terms naively. Match terms in §4.1
  need careful curation per food to avoid alarming users unnecessarily over
  low-risk items (canned light tuna, cooked deli meat that's been
  reheated, pasteurized soft cheeses).
- **Stale due dates**: a user who doesn't update their due date post-birth
  will keep getting pregnancy-targeted coaching indefinitely. v1 should
  prompt re-confirmation if gestational age exceeds ~42 weeks (§2.2).
- **Scope creep into clinical territory**: gestational diabetes is the
  highest-risk area for the coaching prompt to overstep — needs careful
  prompt-testing (eval set additions) before launch.

---

## 9. Open questions for product decision

1. Should `pregnancy_profile.conditions` support a free-text "other medical
   notes" field, or stay to a fixed checkbox list (gestational diabetes,
   multiples)? Free text increases PII/sensitivity handling requirements.
2. Caffeine: ship as a per-item flag in v1 (simple, but misses the "200mg/day
   total" framing that matters most), or invest in the daily-total tracker
   now? 
3. Should the `pregnancy_risk` flag distinguish severity (e.g. "alcohol" /
   "raw fish" = high-severity vs. "deli meat reheated is fine" = low/info)
   in the data model now, or treat all flags uniformly in v1 and layer
   severity later?
4. Where should the seed data for `pregnancy_nutrient_goal` come from
   exactly (which guideline/version), and who owns keeping it current as
   guidance changes?
5. Do we want a lightweight eval subset (extension of `eval/test_set_200.jsonl`)
   specifically for pregnancy Q&A before this ships, given the safety
   stakes? (Likely yes — but sizing/ownership is a product call.)
6. Should disabling pregnancy mode in Settings soft-delete
   `pregnancy_profile` (keep history) or hard-delete? Affects whether a user
   re-enabling later has to re-enter due date/LMP.
