# Data Model: Patient Safety Profile

All new tables reference `user_goal.user_id` with `ON DELETE CASCADE`, have an
owner RLS policy (`auth.uid() = user_id`) in the migration that creates them, and
are deleted with the account (FR-040b). The backend connects as table owner.

Migration **019** (`2026111x_019_patient_safety_profile.py`, revises
`018_user_memory_profile`; 019 is unused on every local and remote branch as of
2026-11-13) is additive only. Migration **020** drops the superseded
`user_goal` columns one release later.

## profile_entry (hard profile)

One row per hard fact version. Rows are never updated except for the state
columns listed under "Mutable"; values are never rewritten (FR-003).

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | `gen_random_uuid()` |
| user_id | uuid FK → user_goal | not null |
| entry_type | text | `allergy`, `diagnosis`, `medication`, `physical_limitation`, `nutrient_limit`, `diet_setting`, `food_exclusion` (R4) |
| value | jsonb | shape by type, validated by Pydantic `EntryValue` (below) |
| label | text null | only for free-text values (medication as stated, food exclusion, custom allergy, free-text diagnosis), ≤ 200 chars; typed values derive their label on read (Principle II) |
| source | text | `patient`, `clinician`, `inferred` |
| state | text | `pending`, `confirmed`, `retired` |
| created_at | timestamptz | date added |
| created_by | text | `patient`, `curator`, `backfill`, `reviewer:<uuid>` |
| evidence | text null | the patient's words the entry came from (curator entries) |
| replaces_id | uuid null FK → profile_entry | the entry this one supersedes |
| confirmed_at · confirmed_by | timestamptz null · text null | **Mutable** once: pending → confirmed |
| retired_at · retired_by · retired_reason | timestamptz null · text null · text null | **Mutable** once: → retired |
| retire_requested_at | timestamptz null | **Mutable**: pending retirement of a confirmed entry (FR-024) |
| readback_asked_at | timestamptz null | **Mutable**: when the coach last read it back |
| conversation_id | text null | where the readback was asked |
| client_request_id | text null | idempotency for app writes; unique per user when set |
| inference_probability | real null | GLiDE score for curator entries |
| mentioned_at | timestamptz null | **Mutable** once: when the coach told the patient about an entry accepted by inference (FR-020, mention once) |
| acknowledged_at | timestamptz null | **Mutable** once: the patient confirmed an inferred entry from the profile screen (source stays `inferred`) |

**Constraints**

- CHECK on `entry_type`, `source`, `state`.
- CHECK `state <> 'confirmed' OR confirmed_at IS NOT NULL`;
  `state <> 'retired' OR retired_at IS NOT NULL`.
- CHECK `source <> 'clinician' OR created_by LIKE 'reviewer:%'` (FR-031 at the
  DB level; only the review router sets `reviewer:` actors).
- Trigger `profile_entry_immutable`: rejects UPDATE of `entry_type`, `value`,
  `label`, `source`, `created_at`, `created_by`, `evidence`, `replaces_id`, and
  rejects any transition out of `retired`. DELETE allowed only by cascade
  (account deletion).
- Unique partial index `(user_id, client_request_id) WHERE client_request_id IS NOT NULL`.

**Indexes**: `ix_profile_entry_live (user_id) WHERE state <> 'retired'`
(per-turn read); `ix_profile_entry_review (state, created_at) WHERE state = 'pending'`.

**Value shapes** (`EntryValue`, `extra="forbid"`)

| Type | Fields |
|---|---|
| allergy | `allergen_group` (key in `allergen_groups.yaml`) or `custom_terms: list[str]`; `severity: str \| None` |
| diagnosis | `condition` (key in `condition_limits.yaml`, or free text) |
| medication | `name` (as stated), `matched_drug: str \| None` (key in interactions table) |
| physical_limitation | `kind`: `chewing`, `swallowing`, `grip`, `standing_time`; `max_texture: str \| None`; `max_active_minutes: int \| None` |
| nutrient_limit | `nutrient`: `sodium`, `potassium`, `phosphorus`, `protein`, `fluid`, `carbohydrate`; `amount: float > 0` (the ceiling); `min_amount: float \| None` (lower end of a target range such as protein 50-60 g a day, shown in the app, never enforced by the checker); `unit`: `mg`, `g`, `ml`; `period`: `per_meal`, `per_day` |
| diet_setting | `setting` (the chip keys in `memory.DIET_CHIPS`) |
| food_exclusion | `terms: list[str]` (1-10 words or phrases) |

**State transitions**

```text
             patient yes / reviewer approve
  pending ───────────────────────────────────▶ confirmed
     │                                             │
     │ patient no / correction / reviewer reject   │ retirement confirmed by patient,
     ▼                                             │ reviewer edit (new entry replaces), 
  retired ◀────────────────────────────────────────┘ or reviewer retire
```

- Edit = retire old (`retired_reason='replaced'`) + insert new with
  `replaces_id`, in one transaction.
- Inference accept band: inserted directly as `confirmed`, source
  `inferred`, `confirmed_by='inference'`, only for entries that add a
  constraint (research R2). A correction from the patient retires it and adds
  a `patient` entry with `replaces_id`.
- Only `confirmed` entries bind (FR-004). `pending` entries are rendered as
  "awaiting confirmation" and not passed to the checker.

**Derived, never stored**

- *Hard profile* = live confirmed entries for a user, ordered by type then
  `confirmed_at`.
- *Profile version* = SHA-256 of `id:confirmed_at` of those entries, sorted (R5).
- *Diet settings / declared conditions* for the goals API = confirmed
  `diet_setting` / `diagnosis` entries.

**Backfill in 019 (data step, idempotent)**

1. `user_goal.conditions[]` → `diagnosis`, confirmed, source `patient`,
   created_by `backfill`, created/confirmed at `user_goal.updated_at`.
2. `user_goal.dietary_prefs` keys that are true and in `DIET_CHIPS` →
   `diet_setting`. Other keys are reported by the migration log and left in
   place for review (none expected; verify with a count on a prod copy first).
3. `user_memory` rows with `category='restriction'` and `deleted_at IS NULL` →
   `allergy` when the text matches an allergen group term, else
   `food_exclusion` with the fact text as the single term set; source
   `patient`; tombstoned restriction rows stay in `user_memory` as tombstones.
4. The `user_memory` restriction rows are **not** deleted in 019 and the
   check constraint is unchanged, so the release running during the deploy
   keeps working (Principle VI). New code ignores restriction rows. Migration
   020 deletes them and drops `restriction` from `ck_user_memory_category`.
   The one-release overlap is a transitional copy (plan Complexity Tracking).

Rollback: downgrade re-creates restriction rows from `food_exclusion` /
`allergy` entries with `created_by='backfill'`, then drops the new tables.

## user_memory (soft profile, changed)

- `category` CHECK becomes `('dislike', 'like', 'habit', 'context', 'cuisine',
  'budget', 'cooking_time', 'preference')`.
- `source` CHECK adds nothing; `stated` is the patient, the curator writes
  `inferred_from_chat`.
- `created_at timestamptz not null default now()` is added so a preference
  shows the date it was learned (`updated_at` changes on edit).
- The `embedding` column and ivfflat index are dropped in 020 (R14 removes the
  last reader).

## recommendation

What was shown to the patient (FR-038), its check, and the patient's reaction.

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| user_id | uuid FK | |
| conversation_id | text null | |
| coaching_response_id | uuid null FK → coaching_response | the reply that carried it |
| recipe | jsonb | the checked `Recipe` (contracts/recipe-and-check.md) |
| check_snapshot | jsonb | `CheckResult` incl. profile version, entry ids, table versions, computed totals. Immutable audit snapshot (plan Complexity Tracking). |
| attempts | smallint | 1-3 |
| status | text | `shown`, `accepted` (planned), `rejected` |
| rejection_reason | text null | ≤ 500 chars |
| created_at · status_at | timestamptz | |

Indexes `(user_id, created_at desc)`. "Eaten" is not stored here; it is
`meal_log` (Principle II). Rows are kept for the life of the account, like
`meal_log`, so every shown recommendation stays traceable (SC-009); they are
deleted only with the account (Principle III).

## check_failure

Every failed attempt (FR-012), including dropped requests and reply-scan hits.

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| user_id | uuid FK | |
| recommendation_id | uuid null FK | set when a later attempt passed |
| attempt | smallint | |
| recipe | jsonb | the failing recipe |
| failures | jsonb | list of `{rule, entry_id, detail, compared: {value, limit, unit}}` |
| profile_version | text | |
| outcome | text | `regenerated`, `dropped`, `reply_replaced` |
| created_at | timestamptz | |

## red_flag_escalation

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| user_id | uuid FK | |
| conversation_id | text null | |
| message | text | the patient's message (reviewer-only read) |
| rule_id · rule_label | text | from `red_flags.yaml` |
| rules_version | text | content hash |
| notify_status | text | `pending`, `sent`, `failed`, `no_recipient` |
| notify_attempts | smallint | |
| notified_at | timestamptz null | |
| created_at | timestamptz | |

Review decisions for escalations live on `review_item`.

## review_item

The queue (FR-029). One row per item needing a reviewer.

| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| user_id | uuid FK | the patient |
| kind | text | `pending_entry`, `rule_conflict`, `escalation`, `plan_sample`, `unknown_medication` |
| subject_id | uuid | `profile_entry.id`, `red_flag_escalation.id` or `recommendation.id` |
| detail | jsonb | for conflicts: the two entries and the stricter value applied |
| decision | text null | `approved`, `rejected`, `edited`, `handled` |
| decided_by · decided_at · comment | text · timestamptz · text, null | |
| created_at | timestamptz | |

Unique `(kind, subject_id)`; index `(decision, created_at desc) WHERE decision IS NULL`.
The queue content is derived from its subjects; only the decision is stored here.

## user_goal (changed in 020)

`conditions` and `dietary_prefs` are dropped after PR 1 has run in production
for one release. Until then PR 1's code neither reads nor writes them (goals API
reads and writes through `safety.profile`), so the columns are dead weight, not
a second copy that can drift.

## Duplication review (Principle II)

| Fact | Before | After |
|---|---|---|
| Declared conditions | `user_goal.conditions` | `profile_entry` (diagnosis) only |
| Diet settings | `user_goal.dietary_prefs` | `profile_entry` (diet_setting) only |
| Hard restrictions | `user_memory` restriction rows | `profile_entry` (allergy / food_exclusion) only |
| Meals eaten | `meal_log` | `meal_log` (not copied into history) |
| Recipe totals | n/a | computed on check; kept only inside the audit snapshot |
| Clinical tables, red flags | n/a | YAML files, versioned by content hash |
