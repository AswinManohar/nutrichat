# Contract: Changes to existing meal payloads

This lists every existing interface whose shape changes, and the reason
(spec FR-019). Fields that are not listed here keep their current shape.

## 1. Confirmation-card items
Covers `POST /meals/log` (paused card), `GET /meals/pending`, and the chat
response.

| Field | Before | After |
|---|---|---|
| `nutrients` | USDA-named map, per item | **Removed** |
| `micros` | (none) | Not sent. Micronutrients are not part of the card (FR-014), and the server re-derives them at log time (research R9) |
| `sugar_g`, `sat_fat_g` | optional numbers | Unchanged (optional, may be null) |
| everything else | — | Unchanged |

Clients: web `types.ts` keeps `nutrients?` as optional, so nothing breaks,
and the field can be deleted later. Android `ItemDto.extras` treats unknown
keys as opaque. The card layout is unchanged (SC-002).

## 2. `POST /meals/log-items` and `POST /my-meals/{id}/log`

- Request: items may still include `nutrients` or `micros`, and both are
  **ignored**. The server calls `resolve_micros` for each item (fdc_id, or the
  name for estimates, plus the scaled qty). This is what fixes Android "Log
  again".
- Response (`MealLogResult`): unchanged.

## 3. `GET /meals/log/{meal_id}` (meal detail)

| Field | Change |
|---|---|
| `items[]` | Stored items no longer carry `nutrients`, `sugar_g` or `sat_fat_g`; each **gains** compact `micros` `{key: [amount, "u"\|"e"]}` (data-model §2) |
| `micros` | **Added**: the meal summary `{key: {total, est, known}}`, computed from the items (data-model §3) |

Neither client reads the removed fields today. Android round-trips them
opaquely, which is safe because the server ignores them (§2).

## 4. `POST /my-meals`, `PUT /my-meals/{id}`, `GET /my-meals/{id}`

- Stored `ingredients[]` carry compact `micros` (`{key: [amount, "u"|"e"]}`)
  in place of `nutrients`. The server derives them and never trusts the
  client.
- The response adds `micros_totals`, which is **computed when read** from the
  ingredients and never stored (FR-014a).

## 5. `GET /v1/integrations/meals` (third-party feed)

| Field | Change |
|---|---|
| `entities[].nutrients` | **Removed** (raw USDA names). This breaks consumers that read it |
| `entities[].micros` | **Added**: per-item compact micros (catalogue keys) |
| `micros` | **Added**: meal summary computed from the items, same shape as §3 |

This needs a changelog entry in `docs/integration-api.md`. Release is blocked
until the user confirms whether life-os (or any other consumer) reads
`entities[].nutrients`.

## 6. `GET /nutrient-checkup`, `GET /mindful/...`

The response shapes are unchanged. The values now come from item micros
and the catalogue. Nutrient display names may change to catalogue names, for
example "Vitamin B12" in place of "Vitamin B-12".
