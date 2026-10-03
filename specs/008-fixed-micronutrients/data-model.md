# Data Model: Fixed Micronutrient Set

**Feature**: 008-fixed-micronutrients | **Research**: [research.md](./research.md)

The guiding rule is FR-018: each fact has exactly one stored home. The
"Stored where" column says where that home is.

## 1. Tracked Nutrient (catalogue entry): config, not DB

File: `src/backend/config/nutrients.yaml`, validated by Pydantic (`extra="forbid"`).

| Field | Type | Rule |
|---|---|---|
| key | str | Stable, snake_case, unique, never renamed or reused (FR-016) |
| name | str | Display name, for example "Vitamin B12" |
| unit | `g` \| `mg` \| `mcg` | Canonical unit |
| group | `carbs` \| `fat` \| `other` \| `vitamins` \| `minerals` | Display group (FR-015) |
| order | int | Order within the group |
| direction | `limit` \| `target` \| `none` | For example sodium is a limit, iron a target |
| daily_value | float \| null | FDA DV in `unit`. Null means amounts only (FR-001a) |
| usda_names | list[str] | Aliases mapped onto this key (FR-006). Empty if USDA has none |
| usda_only | bool | True means it is never AI-estimated (FR-004a) |
| max_per_100g | float \| null | Plausibility cap (FR-007, research R8) |
| upper_limit | {value, source, url} \| null | Tolerable Upper Intake Level for Mindful safety alerts. Moved here from `tunables.yaml upper_limits` (FR-018) |
| column | str \| null | Set only for `fiber` (`fiber_g`): the value is read from that meal_log column |
| derived | {from: key, factor: float} \| null | Set only for `salt` (sodium × 0.0025, giving grams) |
| status | `active` \| `retired` | Retired keys stay readable but are no longer computed |

48 entries (spec FR-001). Validation:
- Keys are unique.
- At most one of `column` and `derived` is set.
- An entry with `derived` has no `usda_names` and `usda_only = false`.
- `usda_only = true` applies exactly to arsenic, boron, cobalt, rubidium,
  silicon, sulfur, tin and vanadium.

## 2. Item Micronutrient Value: in memory, and in saved-meal ingredients

On `USDAResult` (`agent/tools/usda.py`), the field `nutrients: dict[str, NutrientValue]`
is **replaced** by `micros: dict[str, MicroValue]`.

```
MicroValue
  amount: float | None     # scaled to the item's qty_g; None when unknown
  source: "usda" | "estimated" | "unknown"
```

- It holds every active, non-derived, non-column key. Fiber is kept on
  `fiber_g`, and salt is never held.
- A USDA value, **including 0**, wins. Otherwise the pre-computed or
  whole-food estimate is used, unless the key is `usda_only`. Otherwise the
  value is unknown.
- Scaling: `amount = per_100g × qty_g / 100`. It is rescaled whenever qty or
  portion changes (FR-013).
- **Stored**: only inside `user_meal.ingredients[].micros` (saved meals). It is
  never stored on `meal_log`.

## 3. Meal Micronutrient Summary: `meal_log.micros` (new column)

```
meal_log.micros JSONB NOT NULL DEFAULT '{}'
  { "<key>": { "total": float, "est": float, "known": int }, ... }
```

| Field | Meaning | Rule |
|---|---|---|
| total | Sum of the known item amounts | ≥ 0 |
| est | The part of `total` that came from estimates | 0 ≤ est ≤ total |
| known | Number of foods with a known value | 1 ≤ known ≤ jsonb_array_length(entities) |

- A key is **absent** when no food has a value, which means "unknown" (spec
  FR-005).
- The number of foods is **not stored**. It comes from `entities`.
- It is written once, by `log_meal`, from the server-resolved items
  (research R9). A logged meal is immutable except for soft delete.
- `added_sugars.total` is at most `total_sugars.total` when both are present.

## 4. Existing tables that change

| Table.column | Change |
|---|---|
| `meal_log.micros` | **New** (migration `20261003_018_meal_micros`) |
| `meal_log.entities[]` | Stored items **drop** `nutrients`, `sugar_g` and `sat_fat_g` (R12). Everything else stays |
| `user_meal.ingredients[]` | `nutrients` (USDA-named) is replaced by `micros` (catalogue keys). Totals are computed when read and never stored |
| `food_source` (estimate cache) | Rows with `source_db='LLM_ESTIMATE'` gain per-100 g `micros` inside their existing `nutrients` JSONB. No schema change |
| `nutrient_checkup.nutrients` | Unchanged shape. It is a nightly, rebuildable cache, now fed from `meal_log.micros` |
| `usda_fdc.sqlite3` (bundled) | **New** table `food_micro_estimate(fdc_id INTEGER, key TEXT, per_100g REAL, PRIMARY KEY(fdc_id, key))`. `PRAGMA user_version` becomes 3 |
| `tunables.yaml` | `nutrient_checkup.micronutrients`, `.rda` and top-level `upper_limits` are **removed**. They are replaced by `nutrient_checkup.keys: [...]` and the catalogue's `daily_value` and `upper_limit` |

No backfill (FR-012). Existing rows get `micros = '{}'`, which means
everything is unknown.

## 5. Daily totals: computed, never stored

```
DailyMicros (response model)
  date: date
  logged: bool            # false means "no data", not 0 (FR-017)
  n_meals: int
  values: { "<key>": { "total": float, "est": float, "known": int, "items": int } }
```

`items` is the total number of foods that day, so completeness is
`known / items`. Fiber comes from the `fiber_g` column. Salt is computed from
sodium. See [contracts/daily-totals.md](./contracts/daily-totals.md).

## 6. Flow and lifecycle

```
user text → extract → usda_lookup_batch
   ├─ USDA match: USDA values + food_micro_estimate (gaps) ─┐
   └─ no match:   one AI call (macros + per-100 g micros) ──┤→ USDAResult.micros (memory)
                                                            ↓
                         confirmation card (macros only; micros not shown, FR-014)
                                                            ↓ confirm / log-items / saved meal
                     log_meal: resolve_micros() per item (server-side, R9)
                                                            ↓
            meal_log.micros = summarise(items)    entities stored without micros
```
