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

## 2. Item Micronutrient Value: the only stored copy

In memory, `USDAResult.micros: dict[str, MicroValue]` holds
`amount: float | None` and `source: "usda" | "estimated" | "unknown"`.

**Stored** on every logged item (`meal_log.entities[].micros`) and every
saved-meal ingredient (`user_meal.ingredients[].micros`) in compact form:

```
"micros": { "<key>": [amount, "u" | "e"], ... }   # u = USDA, e = estimated
```

- Only **known** values are stored, and an absent key means unknown (never 0).
- A USDA value, **including 0**, wins. Otherwise the pre-computed or
  background estimate is used, unless the key is `usda_only`. Otherwise the
  value is unknown.
- `amount = per_100g × qty_g / 100`, derived server-side at log or save time
  from `fdc_id` or the estimate cache (research R9). Client values are ignored.
- Fiber (column `fiber_g`) and salt (derived) are never in `micros`.

## 3. Micronutrient Summary: computed, never stored

For a meal, day or period: `{key: {"total", "est", "known"}}`.
`total` is the sum of the known item amounts, `est` is the estimated part
(0 ≤ est ≤ total), and `known` is the number of items with a value. Keys with
no known value are omitted. It is computed by `resolve.summarise()` from item
micros, whenever it is read.

## 4. Existing tables that change

| Table.column | Change |
|---|---|
| `meal_log.entities[]` | Stored items **drop** `nutrients`, `sugar_g` and `sat_fat_g`, and **gain** compact `micros` (§2). No new column, so no migration |
| `user_meal.ingredients[]` | `nutrients` (USDA-named) is replaced by compact `micros` (§2). Totals are computed when read and never stored |
| `food_source` (estimate cache) | Rows with `source_db='LLM_ESTIMATE'` gain per-100 g `micros` inside their existing `nutrients` JSONB. No schema change |
| `nutrient_checkup.nutrients` | Unchanged shape. It is a nightly, rebuildable cache, now fed from item micros |
| `usda_fdc.sqlite3` (bundled) | **New** table `food_micro_estimate(fdc_id INTEGER, key TEXT, per_100g REAL, PRIMARY KEY(fdc_id, key))`. `PRAGMA user_version` becomes 3 |
| `tunables.yaml` | `nutrient_checkup.micronutrients`, `.rda` and top-level `upper_limits` are **removed**. They are replaced by `nutrient_checkup.keys: [...]` and the catalogue's `daily_value` and `upper_limit` |

No backfill (FR-012). Existing items have no `micros`, so everything is
unknown for them.

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
            entities[].micros = compact(item)   (summaries computed on read)
```
