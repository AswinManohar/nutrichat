# Contract: Patient profile API

Router `api/profile.py`, prefix `/profile`, Supabase JWT (`get_current_user_id`).
All bodies are Pydantic models with `extra="forbid"`. Every write is
idempotent (Constitution III): `POST /profile/entries` and retire take a
`client_request_id` and a repeat returns the original result; confirm, deny,
feedback, soft `PATCH` and soft `DELETE` return 200/204 with the current state
when the same action was already applied, and 409 only when the entry is in a
state the action cannot reach.

Replaces `/memory` (GET, DELETE) once the Android screen ships (PR 5); `/memory`
stays until then for the released app and is marked `deprecated` in OpenAPI.

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
      "retire_requested": false,
      "acknowledged": false
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
`[]` for now; each item will be `{"name": str, "role": str}`. `hard` lists live entries (pending + confirmed). 503 with
`safety.profile_unavailable_text` when the profile cannot be loaded; never a
partial list.

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
(`retired_reason='denied'`). Repeating the action that was already applied
returns 200 with the entry; 409 only for a conflicting state (for example deny
on a confirmed entry).

Also accepted on a confirmed entry with source `inferred`: sets
`acknowledged_at` (the patient agrees with what was inferred).

## POST /profile/entries/{id}/retire

Body `{"confirm": true, "client_request_id": "…"}`. Retires a confirmed entry
(`retired_by='patient'`). Without `confirm: true` → 422. The app shows its own
confirmation dialog before sending (US5-5). Diet settings toggled off in
Settings use this route too.

## POST /profile/entries

Patient-entered hard entry from the app (Settings: conditions, diet settings).
Body `{type, value, label, client_request_id, replaces_id?}`. With
`replaces_id` it is an edit: the old confirmed entry of the same type is
retired (`replaced`) and the new one replaces it, in one transaction. Created **confirmed** with
source `patient`: the act of entering it in Settings is the confirmation. A
`clinician` source is rejected with 403 (FR-031).

## PATCH /profile/soft/{id} · DELETE /profile/soft/{id}

Body of PATCH: `{"text"?: str (1-200), "kind"?: "dislike"|"like"|"cuisine"|"budget"|"cooking_time"|"habit"|"context"}`,
at least one field; the edit counts as stated by the patient and returns the
updated `soft` item (the surviving one when the new text equals another
preference and the two merge). 404 for an unknown or foreign id, 422 for an
empty body or an older note with no kind.

DELETE creates a tombstone (FR-022, US5-4) so the preference is not learned
again unless the patient restates it. Always 204 for a well-formed id, whether
the preference was live, already deleted or never existed.

## GET /profile/meals?days=21

```json
{"days": 21,
 "recommendations": [{"recommendation_id": "uuid", "name": "Lentil soup", "status": "rejected",
                      "rejection_reason": "too spicy", "created_at": "…"}],
 "eaten": [{"label": "Lunch: rice and dal", "logged_at": "…"}]}
```

`days` ≤ 90. Eaten meals come from `meal_log`; nothing is copied.

## POST /profile/meals/{recommendation_id}/feedback

Body `{"status": "accepted" | "rejected", "reason": "…" | null}` (FR-025).

## GET /profile/export

Full JSON copy of everything remembered (FR-040b): `hard` (every entry with its
history, as in `/profile/history`), `soft` (live preferences; deleted ones are
not exported), `recommendations` (id, date, recipe, status, rejection reason),
`escalations` (date, rule label, notify status and the patient's own message).
Content type `application/json`, attachment filename `mealsy-profile.json`.
Rate limited to 10 a minute.

## Goals API (changed, shape kept)

`GET/PUT /goals` keeps `conditions: list[str]` and `dietary_prefs: dict` in the
response and request so released clients keep working. On PUT, differences are
written as confirmed `diagnosis` / `diet_setting` entries or retirements; the
response is derived from the profile.

## Chat response (changed)

`/chat` responses gain an optional field:

```json
{"readback": {"entry_id": "uuid", "kind": "add", "text": "I'll note this on your profile: Shellfish allergy. Is that right?"}}
```

`kind` is `add` (a pending entry awaits confirmation) or `retire` (a confirmed
entry awaits confirmation to stop applying). The field names the latest
question asked in the reply; when several entries are asked in one turn, one
short reply ("yes" / "no") answers all of them. The answer is an ordinary chat
message; the server reads it before routing (research R13), so the client sends
"Yes" or "No" as text.

Released clients ignore it (the text is also in `message`). A recipe reply
carries `recommendation_id` so the app can send feedback, and `constraint_note`:
the sentence naming what the recipe was kept to ("Kept this free of peanut
because of your peanut allergy."), or `null` when no confirmed entry applied.
The sentence is also part of `message`; the app shows `constraint_note` on its
own instead of parsing it out of the text.

```json
{"recipe": {"…": "…"}, "recommendation_id": "uuid", "constraint_note": "Kept this free of peanut because of your peanut allergy."}
```
