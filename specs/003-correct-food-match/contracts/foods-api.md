# Contract: Foods API and log-items additions

All endpoints require `Authorization: Bearer <Supabase JWT>` (`get_current_user_id`). Errors use FastAPI's `{"detail": ...}` shape.

## GET /foods/search

Free-text search of the reference food DB.

**Query parameters**

| Name | Type | Required | Rules |
|---|---|---|---|
| `q` | string | yes | Trimmed length 2–100. Shorter → 422 |
| `qty_g` | number | no | > 0, ≤ 5000. Default 100. Used only for the preview `kcal`/`protein_g` |
| `limit` | int | no | 1–20, default 10 |

**200**

```json
{
  "query": "white bread toasted",
  "normalized_query": "white bread, toasted",
  "results": [
    {
      "fdc_id": 172687,
      "name": "Bread, white, commercially prepared, toasted",
      "data_type": "sr_legacy",
      "kcal_per_100g": 293.0,
      "protein_g_per_100g": 9.0,
      "kcal": 82.0,
      "protein_g": 2.5
    }
  ]
}
```

- Results are ordered best first (FR-009). An empty `results` array means no match (not an error).
- **429**: rate limited (60/min/user).
- **503** `{"detail": "food_search_unavailable"}`: the reference DB is unavailable. The client shows its "can't search right now" message and keeps the fallbacks (FR-008).

## GET /foods/{fdc_id}

Build a ready-to-log card item for a chosen food.

**Query parameters**: `qty_g` (number, required, > 0, ≤ 5000).

**200**: the **existing card item shape** (same fields as items in a confirm card / `USDAResult`), with `fdc_id`, `food_name` (display name), `qty_g`, the macros, and the full `nutrients` map scaled to `qty_g`. `source = "usda_local"`, `estimated = false`, `match_confidence = 1.0`, `candidates = []`, `candidate_details = []`.

- **404**: unknown `fdc_id`.
- **429**: rate limited (30/min/user).
- **503**: reference DB unavailable.

## Confirm card item: additive field

```json
{
  "food_name": "Shrimp toast",
  "candidates": ["Shrimp toast", "Melba toast", "Anisette toast"],
  "candidate_details": [
    {"fdc_id": 2345, "name": "Shrimp toast", "data_type": "survey_fndds", "kcal_per_100g": 221.0, "protein_g_per_100g": 8.1}
  ],
  "input_phrase": "toast"
}
```

- `candidate_details` defaults to `[]`. Where present, the names match `candidates` in the same order.
- `input_phrase` is optional. The web client ignores both fields (FR-010).

## POST /meals/log-items: additive field on items

```json
{
  "client_request_id": "…",
  "conversation_id": "…",
  "meal_type": "breakfast",
  "items": [
    {
      "food_name": "Bread, white, commercially prepared, toasted",
      "fdc_id": 172687,
      "qty_g": 28, "target_qty_g": 28,
      "kcal": 82.0, "nutrients": {"…": "…"},
      "correction": {
        "original_phrase": "toast",
        "from_fdc_id": 2345,
        "from_name": "Shrimp toast",
        "to_fdc_id": 172687,
        "method": "search",
        "query": "white bread toasted"
      }
    }
  ]
}
```

- `correction` is optional. If present, `to_fdc_id` must equal the item's `fdc_id`, otherwise **422**.
- On success, one `food_correction` row is written per corrected item, in the same transaction as the meal. A replayed `client_request_id` writes nothing new.
- On success with a `conversation_id`, that conversation's pending card is marked resolved, so `GET /meals/pending` no longer returns it (research R4). This applies to every logged card, corrected or not.
- Clients that don't send `correction` behave exactly as today.
