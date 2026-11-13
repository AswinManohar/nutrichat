# Contract: Patient profile API

Router `api/profile.py`, prefix `/profile`, Supabase JWT (`get_current_user_id`).
All bodies are Pydantic models with `extra="forbid"`. Writes accept an optional
`client_request_id`; a repeat with the same id returns the original result
(Constitution III).

Replaces `/memory` (GET, DELETE) once the Android screen ships (PR 5); `/memory`
stays until then for the released app.

## GET /profile

```json
{
  "version": "sha256…",
  "hard": [
    {
      "id": "uuid", "type": "allergy", "label": "Peanut allergy",
      "value": {"allergen_group": "peanut"},
      "source": "patient", "state": "confirmed",
      "created_at": "2026-11-20T10:00:00Z", "confirmed_at": "2026-11-20T10:01:00Z",
      "retire_requested": false
    }
  ],
  "pending_count": 1,
  "care_team": [],
  "soft": [
    {"id": "uuid", "kind": "dislike", "text": "coriander", "source": "stated", "created_at": "…", "updated_at": "…"}
  ],
  "missing_values": ["potassium limit for chronic kidney disease"]
}
```

`care_team` is a placeholder for the clinician role (decision Q1): always
`[]` for now; each item will be `{"name": str, "role": str}`. `hard` lists live entries (pending + confirmed). 500 with a retry message when
the profile cannot be loaded; never a partial list.

## GET /profile/limits/today

Progress for the Care profile banner and bars. Derived on read from today's
`meal_log` (nutrition-day boundaries); nothing is stored.

```json
{
  "on_track": 5, "total": 5,
  "limits": [
    {"entry_id": "uuid", "nutrient": "sodium", "label": "Up to 1,500 mg a day",
     "amount": 1500, "min_amount": null, "unit": "mg", "period": "per_day",
     "so_far": 920, "unknown_items": 0, "on_track": true}
  ]
}
```

`on_track` is false when `so_far` exceeds `amount`. Per-meal limits report
the highest single meal today. `unknown_items` counts logged items with no
value for that nutrient, so the app can say the total may be low.

## GET /profile/history

Every hard entry including retired ones, newest first, with `retired_at`,
`retired_by`, `retired_reason`, `replaces_id`.

## POST /profile/entries/{id}/confirm · POST /profile/entries/{id}/deny

Pending → confirmed (source unchanged, `confirmed_by='patient'`) or → retired
(`retired_reason='denied'`). 409 if the entry is neither pending nor an
unacknowledged inferred entry.

Also accepted on a confirmed entry with source `inferred`: sets
`acknowledged_at` (the patient agrees with what was inferred).

## POST /profile/entries/{id}/retire

Body `{"confirm": true, "client_request_id": "…"}`. Retires a confirmed entry
(`retired_by='patient'`). Without `confirm: true` → 422. The app shows its own
confirmation dialog before sending (US5-5). Diet settings toggled off in
Settings use this route too.

## POST /profile/entries

Patient-entered hard entry from the app (Settings: conditions, diet settings).
Body `{type, value, label, client_request_id}`. Created **confirmed** with
source `patient`: the act of entering it in Settings is the confirmation. A
`clinician` source is rejected with 403 (FR-031).

## PATCH /profile/soft/{id} · DELETE /profile/soft/{id}

Edit text/kind; delete creates a tombstone (FR-022, US5-4).

## GET /profile/meals?days=21

Recommendations (shown, accepted, rejected with reason) and logged meal labels
for the window. `days` ≤ 90.

## POST /profile/meals/{recommendation_id}/feedback

Body `{"status": "accepted" | "rejected", "reason": "…" | null}` (FR-025).

## GET /profile/export

Full JSON copy of everything remembered: hard entries with history, soft facts,
recommendations, escalations about the patient (FR-040b). Content type
`application/json`, attachment filename `mealsy-profile.json`.

## Goals API (changed, shape kept)

`GET/PUT /goals` keeps `conditions: list[str]` and `dietary_prefs: dict` in the
response and request so released clients keep working. On PUT, differences are
written as confirmed `diagnosis` / `diet_setting` entries or retirements; the
response is derived from the profile.

## Chat response (changed)

`/chat` responses gain an optional field:

```json
{"readback": {"entry_id": "uuid", "text": "I'll note that you're allergic to shellfish. Is that right?"}}
```

Released clients ignore it (the text is also in `message`). A recipe reply
carries `recommendation_id` so the app can send feedback.
