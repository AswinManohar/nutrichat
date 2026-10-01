# Research: Edit Saved Meals

**Feature**: [spec.md](spec.md) · **Plan**: [plan.md](plan.md) · **Date**: 2026-10-01

This is the current state of the code these decisions are based on, as of
2026-10-01 on `feat/android-app`:

- `src/backend/api/my_meals.py` has `GET /my-meals`, `GET /my-meals/{id}`,
  `POST /my-meals` (save), `POST /my-meals/{id}/log` (quick-log or Customize)
  and `DELETE`. There is no update route.
- `UserMeal` (`src/backend/db/models.py`) stores `ingredients` as JSONB in the
  same shape as `meal_log.entities`, plus macro totals. It already has an
  `updated_at` column with `onupdate=func.now()`. Its `embedding` column is
  never written (only `meal_log.embedding` is).
- Chat recall: `saved_lookup_node` → `find_saved_meal` (contiguous-phrase match
  on `name_normalized`) → `saved_meal_to_results` loads the stored items as
  they are. The graph sets `from_saved`, but the chat response never tells
  clients which saved meal filled the card.
- Saving from the web card sends the unedited `items`
  (`ConfirmationCard.tsx:207-213`). Android sends the edited, portion-scaled
  items (`Dtos.kt:672 toSavedIngredientDto`).
- Food lookup without the LLM already exists from spec 003:
  `GET /foods/search` and `GET /foods/{fdc_id}?qty_g=` return a card item
  (`USDAResult`). Android has a picker (`FoodPickerViewModel`,
  `CandidatePickerSheetContent`). Web has none; web swaps go through chat.
- "Logged today" on My Meals compares `meal_log.label == user_meal.name`. That
  stops matching after a rename. It also never matches chat-path logs of a
  saved meal, because those get `label = _meal_label(entities)`.

---

## R1: How the update is sent

**Decision**: Add `PUT /my-meals/{id}`. It replaces the whole meal and takes
`name`, `ingredients[]` and `expected_updated_at`. Each ingredient is a full
card item (the same `IngredientIn` shape `POST /my-meals` accepts) with an
optional `target_qty_g`. The server rebuilds every ingredient with the
existing `_scaled_result(item, target_qty_g or qty_g, portion=1)`, recomputes
the totals itself, and stores the result.

**Rationale**:
- The trust model is the same as `POST /my-meals` and `POST /meals/log-items`:
  the server never accepts client totals, only each item's own base values plus
  a gram target.
- Scaling reuses the one function that already keeps unknown nutrients unknown
  (`_scaled_macro`, FR-004 and the "unknown nutrients" edge case).
- Every editor needs only this one route. The My Meals edit screen (US1), the
  update offer after a log (US3), and add/swap (US4, where the client inserts
  an item returned by `POST /my-meals/resolve-ingredient`, R7) all send "the final list of card
  items".

**Alternatives considered**:
- *Index-based patch* (`{index, qty_g}` like `LogMyMealRequest`). Rejected:
  it can't express swapped or added foods. Chat cards (US3) also lose stored
  indices once Android's `CardEditor.removeItem` rewrites the list.
- *Separate routes* (rename, set qty, add, remove). Rejected: more surface, and
  a multi-step edit is no longer atomic (FR-005).
- *Server-side food lookup inside PUT* (send `fdc_id` and grams only).
  Rejected: it duplicates `GET /foods/{fdc_id}`, and estimate items have no
  `fdc_id`.

## R2: Two devices editing the same meal (FR-016)

**Decision**: Optimistic concurrency on the existing `updated_at` column, so no
migration is needed. `GET /my-meals/{id}`, `POST` and `PUT` responses add
`updated_at`. `PUT` locks the row (`SELECT … FOR UPDATE`), then compares it to
`expected_updated_at`. On a mismatch it returns `409 {"detail": "meal_changed",
"current": MyMealDetail}`. A deleted meal or another user's meal returns `404`
(FR-017).

**Rationale**: The timestamp is already maintained on every update. Postgres
keeps microsecond precision, which survives the ISO-8601 round trip.

**Alternatives considered**: An integer `version` column. That is cleaner, but
it needs migration 018 for no practical gain at this write rate. Plain
last-write-wins breaks FR-016.

## R3: Renames and name clashes (FR-007, FR-008)

**Decision**: `PUT` recomputes `name_normalized` with `normalize_meal_name`. It
rejects names that are empty after normalizing (`422`). It checks for a clash
with the user's other live meals, excluding this one, and returns `409
{"detail": "name_taken"}`. It also catches `IntegrityError` from the partial
unique index as a fallback. Because chat recall reads `name_normalized` live,
the new name works and the old one stops matching with no further change.

**Note**: The existing `POST /my-meals` 409 sends a free-text detail. Clients
must now tell `name_taken` and `meal_changed` apart, so `POST` switches to
`detail: "name_taken"` as well. The web check (`status === 409`) is unaffected.
Android's check only looks at the status code, so it is unaffected too.

## R4: Saving from chat keeps edits on every client (FR-010, SC-003)

**Decision**: Scale on the server for both clients. `SaveMealRequest` gains an
optional `portion` (default 1), and each `IngredientIn` gains an optional
`target_qty_g`. The server stores
`_scaled_result(item, target_qty_g or qty_g, portion)`. Web sends `finalItems`
(visible rows with `target_qty_g`) and `portion`. Android keeps sending
already-scaled items with no target and portion 1, which is a no-op on the
server.

**Rationale**: One scaling implementation gives parity by construction, and the
server already handles unknown nutrients correctly. It is backward compatible:
old clients that send neither field get today's behavior.

**Follow-up (not blocking)**: Android's client-side `toSavedIngredientDto`
multiplies a nullable macro directly. Add a unit test that a null/unknown fibre
stays null. If it doesn't, Android should switch to sending `target_qty_g` and
`portion`.

**Alternative considered**: Port Android's scaling to TypeScript. Rejected:
that makes two implementations that have to be kept identical.

## R5: Telling clients a card came from a saved meal (US3, FR-011, FR-012)

**Decision**:
- Graph state gains `saved_meal_id`, set by `saved_lookup_node` on a hit and
  cleared on a miss.
- The chat response and `GET /meals/pending` add `saved_meal: {id, name,
  updated_at} | null`. This is additive, so Android ignores it until updated.
- The client keeps a snapshot of the items as they were when the card loaded.
  After a successful log it compares the final items with that snapshot,
  ignoring portion and meal type (FR-012). If any row was removed, added,
  swapped (different `fdc_id`/`food_name`) or changed by 1 g or more, it shows
  an "Update ‘<name>’ in My Meals?" action. Accepting sends `PUT` with the
  final items at 1× (portion excluded) and the snapshot's `updated_at`.
- My Meals Customize (`POST /my-meals/{id}/log`) shows the same offer
  client-side. The client already has the stored detail to compare against.

**Rationale**: The client already owns the card's edit state, so the offer is a
client decision followed by one `PUT`. The server stays stateless about
offers.

**Portion is excluded in the update** (unlike R4's save-new): a portion change
means "I ate more this time", not "the recipe is different". This follows
FR-012.

**Alternative considered**: A server-side `POST /my-meals/{id}/replace-from-log`
that copies a `meal_log`. Rejected: `meal_log` doesn't store the portion, so it
can't be taken back out, and the stored values would no longer match what the
user saw.

## R6: "Logged today" and labels after a rename

**Decision**: Every log that comes from a saved meal writes
`flags.saved_meal_id` and uses `label = meal.name`. That covers
`POST /my-meals/{id}/log`, the chat path when `from_saved`, and
`POST /meals/log-items` with a new optional `saved_meal_id`. `list_meals`
marks a meal as logged today when `flags->>'saved_meal_id' = id OR label =
name`. The label check is kept for logs written before this change.

**Rationale**: `meal_log.flags` is JSONB that already exists, so there is no
migration. Old logs keep their stored label (FR-009 / SC-004: past logs are
never changed).

## R7: Adding and swapping ingredients (US4, FR-013, FR-014, FR-014a/b)

*Revised 2026-10-01 after `/speckit-clarify`. The earlier decision (a
database-search picker only, no LLM) is superseded.*

**Decision**: Add a new stateless route, `POST /my-meals/resolve-ingredient`.
It turns free text into **one** card item. It runs the same steps as chat
logging, but with different context and a single-food output:

```
consume_llm_credit ─► replacement LLM (structured) ─► validate exactly 1 food
   (FR-014b)            ReplacementResult             (FR-014a)
                                                          │
                      apply grams rule ◄──────────────────┘
                            │
                      usda_lookup_batch([entity])  ─► USDAResult (+ estimate fallback)
```

The route **does not change the saved meal**. It returns an item that the
editor puts into its local state. The change is only stored when the user
presses Save, through the R1 `PUT` (FR-005 is unchanged).

**Rationale**:
- Everything after the LLM call reuses existing code: `usda_lookup_batch`
  → `_fetch_one`, the local DB, the confidence floor and
  `estimate_nutrition_llm`. Nutrition is therefore found the same way as in
  chat logging, including the estimate fallback (FR-015).
- Keeping the route stateless means a single save can include many add/swap
  calls, Cancel throws them all away, and the R2 concurrency check stays in
  one place.

**Alternatives considered**:
- *Reuse `_correction_llm`* (it rewrites the whole `ExtractionResult` over
  every ingredient). Rejected in clarify Q1/Q4: other rows could change, it
  sends too much context, and there is no single-food guarantee.
- *Reuse `extract_entities` on the raw text.* Rejected: it has no "replacing
  X" context, so "brown" fails, and it allows several foods and composite
  flags.
- *Have the route also write to the saved meal.* Rejected: an edit would
  happen in several network calls, which breaks Save/Cancel.
- *Database-search picker* (the previous R7). Replaced by clarify Q1 and Q3.

## R8: Structured output schema

**Decision**: A new Pydantic schema in `agent/tools/replace_ingredient.py`:

```python
class ReplacementFood(BaseModel):
    food_name: str        # USDA-style, specific: "rice brown long-grain cooked"
    qty_g: float          # gt=0; grams for the stated amount, else typical portion
    unit: str             # original unit as said: "cup", "tbsp", "slice", "g", "serving"
    amount_stated: bool   # True only if the user's text gives an amount
    model_config = ConfigDict(extra="forbid")

class ReplacementResult(BaseModel):
    foods: list[ReplacementFood]   # the model reports what it saw; the server enforces len == 1
```

**Why a list when only one food is allowed?** If the schema forced a single
object, the model would squeeze "rice and dal" into one made-up food. With a
list it can report two foods, or none for "asdf", and the server turns
`len != 1` into the rephrase error (FR-014a). This is easy to test and
doesn't depend on the prompt being followed.

**Grams rule, enforced by the server** (the model's output is not trusted):

| Mode | `amount_stated` | Grams used |
|---|---|---|
| swap | true | `qty_g` from the model |
| swap | false | the replaced row's `qty_g` (FR-014). The model's grams are ignored |
| add | true | `qty_g` from the model |
| add | false | `qty_g` from the model, its typical portion (FR-013) |

`unit` is stored on the entity, the same way `FoodEntity.unit` is. When the
server keeps the old grams in a swap without a stated amount, it also keeps
the old unit.

**Context the model gets** (clarify Q4), as one human message:

```
mode: swap | add
meal: "Chicken biryani"
replacing: {"food_name": "rice white cooked", "qty_g": 150, "unit": "cup"}   # swap only
user_text: "brown"
```

It never sees the other ingredients.

**Prompt**: a new `config/prompts/replace_ingredient_system.md` with a matching
`PromptsConfig.replace_ingredient_system` field. The loader fails at import if
the file is missing. The prompt covers:
- the naming style, copied from `extraction_system.md` so names suit the USDA
  ranker;
- resolving relative phrases against `replacing`;
- `amount_stated` true only for an explicit amount or count;
- a typical portion when no amount is given;
- an empty `foods` list for text that isn't a food;
- one entry per food when several are named;
- never decomposing a dish.

**Model**: `make_llm()` (Gemini 2.5 Flash, thinking off), the same tier as
extraction, using `.with_structured_output(ReplacementResult)` and called
through `ainvoke` (async; CLAUDE.md says no blocking calls). There is no new
model or dependency.

## R9: Credits, failures and latency

- **Credit** (FR-014b): call `consume_llm_credit(user_id)` once before the LLM,
  as `orchestrator.py` does. If it returns False, respond `402 {"detail":
  {"code": "quota_exhausted", "message": _UPGRADE_MSG}}` and make no LLM call.
  `_UPGRADE_MSG` moves to `backend.quota` so chat and this route share the
  text, and quota stays in one place for when subscriptions change.
- **0 or 2+ foods, or schema validation failure** (FR-014a): respond `422
  {"detail": {"code": "rephrase", "message": "Describe one food, e.g. 'brown
  rice' or '1 tbsp ghee'."}}`. The credit is **not** refunded, matching chat,
  where a failed extraction still costs the credit. That keeps quota logic
  out of this feature (FR-014b).
- **LLM error or timeout** (`asyncio.wait_for`, 10 s cap): respond `503
  {"detail": {"code": "resolve_unavailable"}}`. The client keeps the row and
  shows Retry (FR-018).
- **Abuse guard**: `user_rate_limiter("resolve_ingredient", limit=20,
  window_s=60)`, the same pattern as `foods_search`.
- **Latency target**: p95 ≤ 3 s from end to end. That's one Flash call with
  thinking off (about 1 s) plus a local DB lookup (milliseconds), or about
  1 s more on an estimate fallback. It's tracked with a Logfire span
  `resolve_ingredient` recording mode, `n_foods`, `amount_stated`, `source`,
  `estimated` and `latency_ms`.

## R10: Offline eval (SC-007)

**Decision**: Add a new case file `eval/cases/ingredient_replace.jsonl` with
at least 40 cases, and a new `gate.py` category `ingredient_replace`. The case
mix:

| Group | Count | Example |
|---|---|---|
| Swap, full name, no amount | ≥10 | replacing white rice 150 g, "brown rice" → brown rice, 150 g |
| Swap, relative phrase | ≥8 | "brown", "whole wheat version", "skim" (for milk) |
| Swap, stated amount | ≥6 | "1 cup brown rice" → about 195 g |
| Add, stated amount | ≥8 | "1 tbsp ghee" → about 13 g |
| Add, no amount (typical portion) | ≥4 | "a banana" / "ghee" |
| Not in the database (estimate path) | ≥4 | regional dishes and brands |
| Must reject (0 or 2+ foods) | ≥4 | "rice and dal", "asdf" |

A case is `{mode, meal, replacing?, text, expect_name_any: [...],
expect_qty_g, expect_reject?, expect_fdc_ids?}`.
- **Pass (gating)** when exactly one food comes back, the model's `food_name`
  contains one of `expect_name_any` (normalized), and the final grams after the
  server's grams rule are within ±25% of `expect_qty_g`. A reject case passes
  when the route would return `rephrase`.
- **Nutrition match (non-gating)**: the resolved `fdc_id` is in
  `expect_fdc_ids`. Reported only.
- **Gate**: `gate.py --only ingredient_replace --runs 5`. It passes when the
  **absolute** mean is ≥ 90%. The category's absolute floor is checked in
  addition to the existing baseline tolerance. The first passing run is saved
  as `eval/baseline_ingredient_replace.json` for future regression checks.
- The scorer calls the **service function** (`resolve_ingredient(...)` with
  credit consumption injected as a no-op), not HTTP, so evals never spend
  credits.

**Result (T055, 2026-10-01)**: `gate.py --only ingredient_replace --runs 5`
scored a mean of 94.6% (noise band 0.0 pp) on the 56 cases, above the 90% floor.
Saved as `eval/baseline_ingredient_replace.json`. The first run, before the prompt
gained household-measure conversions, scored 86.4%. The non-gating
`ingredient_replace_fdc_match` is n/a: no case lists `expect_fdc_ids`. Three
cases fail every run on expectation issues, not model errors: `swap-full-01` and
`swap-amt-01` expect the substring "brown rice", but the model uses USDA word order
("rice brown cooked"); `add-typ-04` expects 20 g for "a slice of cheese", but the
model returns 28 g (cheddar).

## R11: Client UI structure

**Decision**:
- **Web**
  - New `components/my-meals/my-meal-editor.tsx`: name field, ingredient rows
    with gram inputs, remove, live totals, Save/Cancel.
  - Reuse `MyMealCustomizer`'s row and total math by extracting a shared
    `lib/meal-math.ts`.
  - New hook `useUpdateMeal` in `api/hooks.ts`.
  - `ingredient-input.tsx` for US4: a free-text box with mode swap/add,
    calling `useResolveIngredient`, showing an inline spinner and errors.
  - Each component stays under the ~120-line guideline in CLAUDE.md.
- **Android**
  - New `ui/mymeals/EditMealScreen.kt`, a full-screen route from
    `MyMealsScreen`, rather than another bottom sheet. Renaming needs the
    keyboard, and the 200%-font-scale lessons from #53 apply.
  - A pure `EditMealState`, modeled on `CustomizeSheetState`, in the domain
    module so it can be unit tested.
  - `MyMealsRepository.update(...)` + `MealsyApi.updateMyMeal`.
  - US4: `IngredientInputSheet.kt` (free text, swap or add) +
    `MyMealsRepository.resolveIngredient(...)`.
- **Both**: a 409 `meal_changed` reloads the editor from `current` and shows
  "This meal changed on another device. Showing the latest version." A failed
  save keeps the edits and shows Retry (FR-018, matching #52/#55).
  Resolve errors are shown inline in the ingredient input, and the row
  doesn't change:
  - `422 rephrase` shows the server's message;
  - `402 quota_exhausted` shows the upgrade message;
  - `503` shows Retry.

## R12: Out of scope (confirmed)

- The Telegram bot. It recalls saved meals but has no place to manage them.
- Edit history and undo.
- Changing chat recall matching.
- Backfilling `flags.saved_meal_id` on existing logs.

## Open items for the user (not blockers)

1. ~~Confirm R7's narrowing~~. Resolved by clarify: add/swap uses the LLM
   call (R7–R10).
2. Confirm R5's rule: the "Update saved meal" offer saves amounts at 1×
   (portion ignored), while "Save as meal" from a new card applies the portion
   (R4).
