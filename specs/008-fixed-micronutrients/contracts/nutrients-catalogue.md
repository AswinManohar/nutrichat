# Contract: Nutrient catalogue

`GET /meta/nutrients`. This is public (no auth), like `GET /meta/app`, and it
can be cached (`Cache-Control: public, max-age=3600`).

This is the only place where clients learn the tracked nutrients (FR-015).
Clients MUST NOT hard-code the list. Field meanings are defined in
[data-model.md §1](../data-model.md).

## Response 200

```json
{
  "version": 1,
  "groups": [
    {"id": "carbs",    "name": "Carbohydrate detail", "order": 1},
    {"id": "fat",      "name": "Fat detail",          "order": 2},
    {"id": "other",    "name": "Other",               "order": 3},
    {"id": "vitamins", "name": "Vitamins",            "order": 4},
    {"id": "minerals", "name": "Minerals",            "order": 5}
  ],
  "micronutrient_tabs": [
    {"id": "electrolytes", "name": "Electrolytes",
     "keys": ["sodium", "potassium", "calcium", "magnesium", "phosphorus"]},
    {"id": "vitamins", "name": "Vitamins", "keys": ["vitamin_a", "vitamin_c"]},
    {"id": "minerals", "name": "Minerals", "keys": ["iron", "zinc"]}
  ],
  "micronutrient_summary": ["vitamin_c", "vitamin_d", "iron", "sodium"],
  "nutrients": [
    {
      "key": "sodium",
      "name": "Sodium",
      "unit": "mg",
      "group": "other",
      "order": 4,
      "direction": "limit",
      "daily_value": 2300,
      "usda_only": false,
      "derived": null,
      "status": "active"
    },
    {
      "key": "salt",
      "name": "Salt",
      "unit": "g",
      "group": "other",
      "order": 3,
      "direction": "limit",
      "daily_value": null,
      "usda_only": false,
      "derived": {"from": "sodium", "factor": 0.0025},
      "status": "active"
    }
  ]
}
```

- `version` goes up whenever a nutrient is added or retired. Keys never
  change (FR-016).
- Server-only fields (`usda_names`, `max_per_100g`, `column`) are **not**
  exposed.
- `micronutrient_tabs` is the Android Micronutrients screen's selection
  (tunables `micronutrient_view`, shortened above): which nutrients it charts,
  in which tab and order. It holds keys only; names, units, daily values and
  direction come from `nutrients`. Every key is active and has a
  `daily_value`, and no key is in two tabs (checked at startup).
- `micronutrient_summary` is the short list on the Android Journey screen,
  in order (tunables `micronutrient_view.summary_keys`). Every key is in one
  of the tabs.
- The response lists all 48 entries (spec FR-001). Retired entries are still
  listed, with `"status": "retired"`.
