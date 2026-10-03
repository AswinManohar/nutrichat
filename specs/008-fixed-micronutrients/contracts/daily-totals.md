# Contract: Per-day micronutrient totals

`GET /nutrients/daily`. This uses the authenticated user (Supabase JWT, the
same as other user endpoints). It is read-only, and results are computed from
`meal_log` on every call (FR-018). Nothing is stored.

This is the data source for the future visualization feature (FR-017,
SC-008, SC-009). The Check-up, Mindful panel and coaching call the same
service function, `get_daily_micros`, internally (SC-006).

## Query parameters

| Name | Type | Rule |
|---|---|---|
| from | date (YYYY-MM-DD) | Required. Nutrition day, inclusive |
| to | date | Required. `to − from` must be at most 364 days, otherwise 422 |
| keys | comma-separated catalogue keys | Optional. Defaults to all active keys. An unknown key returns 422 |
| meals | bool | Optional, default false. True adds per-meal contributions |

## Response 200

```json
{
  "from": "2026-09-27",
  "to": "2026-10-03",
  "days": [
    {
      "date": "2026-10-02",
      "logged": true,
      "n_meals": 3,
      "items": 7,
      "values": {
        "sodium": {"total": 2140.0, "est": 600.0, "known": 7},
        "salt":   {"total": 5.35,   "est": 1.5,   "known": 7},
        "fiber":  {"total": 24.1,   "est": 0.0,   "known": 7},
        "biotin": {"total": 18.0,   "est": 18.0,  "known": 5}
      },
      "meals": [
        {"meal_id": "7f3a…", "meal_type": "lunch", "label": "Dal and rice",
         "values": {"sodium": {"total": 302.0, "est": 300.0, "known": 2}},
         "foods": [
           {"food_name": "dal", "values": {"sodium": {"total": 300.0, "est": 300.0, "known": 1}}},
           {"food_name": "Rice, white, cooked", "values": {"sodium": {"total": 2.0, "est": 0.0, "known": 1}}}
         ]}
      ]
    },
    {"date": "2026-10-03", "logged": false, "n_meals": 0, "items": 0, "values": {}}
  ]
}
```

## Rules

- Every day in the range appears in the response. A day with no meals has
  `logged: false`, and the client shows "no data", not 0 (FR-006 of spec 004,
  FR-017 here).
- If a key is missing from `values`, every food that day was unknown for it.
- Completeness is `known / items`. The estimated share is `est / total`.
- `salt` is computed from `sodium`. `fiber` comes from the `fiber_g` column.
  Fiber's `est` is 0 and `known` equals `items`, because fiber is a macro that
  is always present.
- Day boundaries use the app's nutrition day (`NUTRITION_DATE_SQL`, with the
  reset hour and timezone).
- Soft-deleted meals are excluded.
- `meals` is included only when `meals=true`. Each meal lists its `foods`,
  so "top contributors" (spec 004) can be attributed to individual foods.
- Performance: p95 under 1 s for 90 days and all keys (SC-008).
