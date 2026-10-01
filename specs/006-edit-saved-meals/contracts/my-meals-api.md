# Contract: My Meals API changes

All routes need Supabase auth. Every change except the new `PUT` is
**additive**, so existing clients (the shipped Android build, Telegram) keep
working.

## NEW: `PUT /my-meals/{id}`

Replaces a saved meal's name and ingredients.

```jsonc
// Request
{
  "name": "Biryani",                       // 1..120 chars, non-empty after normalize
  "expected_updated_at": "2026-10-01T09:12:44.123456+00:00",
  "ingredients": [                          // min 1
    {
      "food_name": "Rice, white, cooked",
      "qty_g": 200,                         // base weight the macros below refer to
      "target_qty_g": 150,                  // optional, the edited weight; default = qty_g
      "kcal": 260, "protein_g": 5.4, "carbs_g": 56, "fat_g": 0.6, "fiber_g": null,
      "fdc_id": 168878, "source": "usda_local", "estimated": false,
      "nutrients": { "...": { "amount": 1.2, "unit": "mg" } }
      // other card-item fields are allowed and stored as sent (extra="allow")
    }
  ]
}
```

| Status | Body | When |
|---|---|---|
| 200 | `MyMealDetail` (with the new `updated_at`) | Saved |
| 404 | `{"detail": "Meal not found"}` | The meal is missing, deleted, or belongs to another user |
| 409 | `{"detail": "name_taken"}` | Another live meal of this user has the same normalized name |
| 409 | `{"detail": {"code": "meal_changed", "current": MyMealDetail}}` | `expected_updated_at` ≠ the stored `updated_at` |
| 422 | validation error | Empty name, no ingredients, `qty_g`/`target_qty_g` ≤ 0 |

The server stores `_scaled_result(item, target_qty_g ?? qty_g, portion=1)`
for each ingredient and recomputes the totals. It ignores client totals.

## CHANGED: `POST /my-meals` (save new)

- The request adds an optional `portion` (number > 0, default 1), and each
  ingredient adds an optional `target_qty_g`. Each stored ingredient is
  `_scaled_result(item, target_qty_g ?? qty_g, portion)`.
- A 409 body becomes `{"detail": "name_taken"}`. Status codes are unchanged.
- The response adds `updated_at`.

## CHANGED: `GET /my-meals/{id}` and `GET /my-meals`

- `MyMealDetail` adds `updated_at` (ISO-8601 with microseconds).
- The `logged_today` rule is now "saved_meal_id flag OR label" (data-model.md).

## CHANGED: `POST /my-meals/{id}/log`

There is no request change. The resulting `meal_log` gets
`flags.saved_meal_id` and `label = meal.name`.

## CHANGED: chat response (`POST /meals/log` paused card) and `GET /meals/pending`

```jsonc
{
  "status": "success",
  "paused": true,
  "items": [...],
  "saved_meal": { "id": "…", "name": "Chicken biryani", "updated_at": "…" } // or null
}
```

`saved_meal` is present only when the card was filled from a saved meal. It is
`null` or absent otherwise.

## CHANGED: `POST /meals/log-items`

The request adds an optional `saved_meal_id`. When it belongs to the caller,
the log gets `flags.saved_meal_id` and `label = that meal's name`. An unknown
or foreign id is ignored silently, so the meal still logs normally.

## NEW: `POST /my-meals/resolve-ingredient` (US4)

Turns free text into one card item for the editor. It is **stateless** and
never changes a saved meal; the editor saves through `PUT`. The route is
rate-limited per user (`resolve_ingredient`, 20/min) and **costs 1 usage
credit per call** through the shared quota check.

```jsonc
// Request
{
  "mode": "swap",                        // "swap" | "add"
  "text": "brown",                       // 1..200 chars after trim
  "meal_name": "Chicken biryani",        // 1..120 chars
  "replacing": {                         // required for swap, must be absent for add
    "food_name": "Rice, white, cooked",
    "qty_g": 150,
    "unit": "cup"                        // optional, default "g"
  }
}

// 200 Response
{
  "item": { /* USDAResult card item, the same shape as chat card items:
               food_name, qty_g, kcal, protein_g, ..., nutrients, fdc_id
               (-1 if estimated), source, estimated, match_confidence, candidates */ },
  "unit": "cup",
  "amount_stated": false,
  "kept_previous_qty": true              // swap with no stated amount, so the old grams were kept
}
```

| Status | Body | When |
|---|---|---|
| 200 | see above | Exactly one food resolved |
| 402 | `{"detail": {"code": "quota_exhausted", "message": "<shared upgrade text>"}}` | No usage left. The LLM is not called |
| 422 | `{"detail": {"code": "rephrase", "message": "Describe one food, e.g. 'brown rice' or '1 tbsp ghee'."}}` | The model returned 0 or 2+ foods, or output that failed validation. The credit is still spent |
| 422 | validation error | Bad mode, empty text, `replacing` missing on swap or present on add |
| 429 | rate-limit body | More than 20 per minute |
| 503 | `{"detail": {"code": "resolve_unavailable"}}` | LLM error or timeout (10 s) |

**Grams rule (server-enforced)**: on a swap where `amount_stated` is false,
`item.qty_g` is `replacing.qty_g`. Otherwise it is the model's grams. See
research R8.

### LLM structured output (internal, not on the wire)

`ReplacementResult { foods: ReplacementFood[] }`, where
`ReplacementFood { food_name, qty_g > 0, unit, amount_stated }` with
`extra="forbid"`. The server enforces `len(foods) == 1`. See research R8.
