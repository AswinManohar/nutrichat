# Data Model: Correct a Wrong Food Match

## FoodSearchResult (API response item; not persisted)

Source: the local USDA reference DB (research R1).

| Field | Type | Rules |
|---|---|---|
| `fdc_id` | int | USDA FoodData Central id. Required. |
| `name` | str | FDC description, e.g. "Bread, white, toasted" |
| `data_type` | enum `foundation` \| `sr_legacy` \| `survey_fndds` | Generic foods only (no branded) |
| `kcal_per_100g` | float ≥ 0 | |
| `protein_g_per_100g` | float ≥ 0 | |
| `kcal` | float ≥ 0 | Scaled to the request's `qty_g` (preview only) |
| `protein_g` | float ≥ 0 | Scaled to `qty_g` (preview only) |

## CandidateDetail (added to each confirm-card item; not persisted)

This is the same shape as FoodSearchResult without the scaled fields. The client scales values for preview (R5).

| Field | Type | Rules |
|---|---|---|
| `fdc_id` | int | |
| `name` | str | Equals the matching entry in the existing `candidates: list[str]`, same order |
| `data_type` | enum | as above |
| `kcal_per_100g`, `protein_g_per_100g` | float ≥ 0 | |

`candidates: list[str]` is **unchanged** for web and older-client compatibility. `candidate_details` MAY be empty (for example on estimated items, or when the item came from the live FDC path without per-candidate data).

## Card item (existing), additions only

| Field | Type | Notes |
|---|---|---|
| `candidate_details` | list[CandidateDetail] | New, optional, default `[]` |
| `input_phrase` | str \| null | New, optional: the user's original words for this food (R9). Only added if not already derivable. |
| `correction` | Correction \| null | **Client → server only**, on `log-items` items that were swapped |

### Correction (on a logged item)

| Field | Type | Rules |
|---|---|---|
| `original_phrase` | str (1–200) | The user's words for the item |
| `from_fdc_id` | int \| null | Null if the previous match was an estimate |
| `from_name` | str (1–300) | The previous match's display name |
| `to_fdc_id` | int | Must equal the logged item's `fdc_id` (server validates; mismatch → 422) |
| `method` | enum `suggestion` \| `search` | How the user picked it |
| `query` | str \| null (≤ 200) | The search text, when `method = search` |

## FoodCorrection (persisted, new table `food_correction`)

| Column | Type | Constraints |
|---|---|---|
| `id` | uuid | PK |
| `user_id` | uuid | Not null, indexed. Deleted with the account |
| `meal_log_id` | uuid | FK → `meal_log.id`, `ON DELETE CASCADE` (the correction goes when the meal is deleted) |
| `original_phrase` | text | Not null |
| `from_fdc_id` | int | Nullable |
| `from_name` | text | Not null |
| `to_fdc_id` | int | Not null |
| `to_name` | text | Not null (the logged item's food name) |
| `method` | text | Check constraint: `suggestion` or `search` |
| `query` | text | Nullable |
| `created_at` | timestamptz | Default `now()` |

- Written only inside a successful `POST /meals/log-items`, in the same transaction as the meal rows (no orphan corrections). Idempotent: a replayed `client_request_id` writes nothing new.
- Read by: nothing in this feature (FR-012). It's used for analysis and by the future "remember my corrections" feature.
- Migration: revision `015_food_correction`, `down_revision = "013"` (research R6).

## State: confirm-card item on Android (existing `CardEditor` flow, extended)

```
Matched ──(open picker)──> Picking
Picking ──(select suggestion/result)──> Swapping(fdc_id)   [GET /foods/{fdc_id}]
Swapping ──ok──> Swapped(prev = old item)    → toast "Swapped to X" + Undo
Swapping ──error──> Matched                  → inline error in the sheet, card unchanged
Swapped ──(Undo)──> Matched(prev)
Picking ──(None of these)──> Removed (existing, with Undo)
Picking ──(Describe it differently)──> existing chat correction path
Any ──(Confirm & log)──> Logged              → log-items sends item + correction?; pending resolved (R4)
```

`Swapped` keeps `qty_g`/`target_qty_g` and the meal type (FR-004). Only one swap is pending per item; a later swap replaces the earlier one, with the correction's `from_*` still pointing at the **originally matched** food.
