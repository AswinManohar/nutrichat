# Mobile API contract

This is the frozen contract between the Mealsy backend and the Android
client. It is hand-maintained — update it whenever an endpoint's shape
changes.

## Invariants

These hold for every endpoint below, for as long as an Android client built
against an older server version may still be in the field:

1. **Fields are never removed or renamed.** A field can be added, and can be
   deprecated (stop being written, always `null`/`0`/empty), but an existing
   field's name and meaning never change.
2. **Enums never shrink.** New values (`meal_type`, `platform`, `tier`, etc.)
   may be added; existing values are never removed or repurposed.
3. **Clients must ignore unknown fields.** The server may add new response
   fields at any time without a version bump; a client that fails to parse
   on an unrecognized field is broken by design and must not ship that way.

## Auth

Every endpoint below requires a Supabase bearer token (`Authorization: Bearer
<jwt>`) via `get_current_user_id`, **except** `GET /meta/app`, which is
unauthed on purpose (it must be reachable before login, to decide whether the
app is even allowed to run).

## Retry rules

- **`POST /meals/log` must never be auto-retried.** It drives an LLM
  extraction pipeline and can take 2–6 seconds; a client-side timeout does
  not mean the server didn't commit the write. On a timeout or dropped
  connection, call `GET /meals/pending?conversation_id=...` to recover the
  in-flight confirmation card instead of resending the original message.
- **`POST /meals/log-items` is the only safe-to-retry write**, and only when
  a `client_request_id` is supplied. The server deduplicates on
  `(user_id, client_request_id)`; a replay returns the original meal with
  `"deduplicated": true` instead of logging a second time.
- All other writes (`POST /goals`, `PUT /goals`, `POST /devices/register`,
  `DELETE /devices/{token}`, `POST /my-meals`, `DELETE /my-meals/{id}`,
  `POST /my-meals/{id}/log`, `DELETE /meals/log/{id}`) are not idempotency-
  keyed; do not blind-retry them on timeout without checking server state
  first (e.g. re-`GET` before re-`POST`).

---

## `POST /meals/log`

Log or resume a meal-logging conversation turn (drives the LLM extraction
graph). Slow (2–6 s) — see retry rules above.

Request:

```json
{
  "user_input": "two eggs and toast",
  "conversation_id": "abc123",
  "image_b64": null,
  "meal_type": null,
  "action": null
}
```

`conversation_id` is optional (defaults to a per-user `"default"` thread).
The server namespaces the LangGraph thread id as `{user_id}:{conversation_id
or 'default'}`, so one user can never read or resume another user's paused
conversation even by guessing their `conversation_id`.

Response:

```json
{
  "status": "confirm",
  "message": "Got it — 2 eggs and 1 slice of toast. Log as breakfast?",
  "paused": true,
  "items": [ { "food_name": "egg", "qty_g": 100, "kcal": 155, "...": "..." } ]
}
```

`status`/`message`/`items` content varies by turn (extraction, clarification,
confirmation, coaching reply); `paused` indicates whether the graph is
waiting on a confirm/correct/decompose action before it will commit.

## `GET /meals/pending?conversation_id=`

Recover the paused confirmation card for a conversation (e.g. after a
`POST /meals/log` timeout). `conversation_id` is required; pass `"default"`
to reach the same thread as a `POST /meals/log` call made with no
`conversation_id`.

Response shape matches `POST /meals/log`'s response (`status`, `message`,
`paused`, `items`). If nothing is pending, `paused` is `false`.

## `POST /meals/log-items`

Log a confirmation card's final, client-edited item set directly — no LLM
round-trip. **The only safe-to-retry write** (see retry rules).

Request:

```json
{
  "meal_type": "breakfast",
  "portion": 1.0,
  "items": [
    { "food_name": "egg", "qty_g": 50, "target_qty_g": 100, "kcal": 78, "fdc_id": 12345 }
  ],
  "client_request_id": "a1b2c3-client-uuid"
}
```

`items[].qty_g` is the originally resolved gram weight (scaling base);
`target_qty_g` is the user-edited weight before the `portion` multiplier is
applied. Extra fields on each item (nutrients, `fdc_id`, macros, `source`,
`estimated`) are preserved verbatim. `client_request_id` is optional but
required for idempotent retries.

Response (`MealLogResult`):

```json
{
  "meal_id": "m_789",
  "meal_type": "breakfast",
  "n_items": 1,
  "kcal": 156.0,
  "protein_g": 12.4,
  "carbs_g": 1.2,
  "fat_g": 10.8,
  "fiber_g": 0.0,
  "message": "Logged breakfast.",
  "deduplicated": false
}
```

On a retried request with the same `client_request_id`, the server returns
the original meal with `"message": "Already logged."` and
`"deduplicated": true` instead of creating a second row.

## `GET /meals/today`

Response:

```json
{
  "kcal": 1450.0,
  "protein_g": 88.0,
  "fiber_g": 14.0,
  "n_meals": 3,
  "by_type": [
    { "meal_type": "breakfast", "kcal": 450.0, "summary": "eggs, toast" }
  ]
}
```

## `GET /meals/trends?days=91`

Per-day aggregates for the trends view (`days` in `[1, 366]`, default 91).
Days with no logged meals are omitted — clients fill gaps as empty cells.

Response: list of

```json
{
  "date": "2026-09-01",
  "kcal": 1800.0,
  "protein_g": 95.0,
  "carbs_g": 200.0,
  "fiber_g": 20.0,
  "n_meals": 3,
  "junk_meals": 1
}
```

## `GET /meals/categories?days=30`

Per-meal-category macro averages and frequency over the last `days` days
(`days` in `[1, 366]`, default 30). Categories with no meals in the window
are omitted.

Response: list of

```json
{
  "meal_type": "breakfast",
  "n_meals": 12,
  "days_logged": 10,
  "avg_kcal": 420.5,
  "avg_protein_g": 22.1,
  "avg_carbs_g": 45.0,
  "avg_fat_g": 15.2,
  "avg_fiber_g": 5.0,
  "total_kcal": 5046.0,
  "share_kcal_pct": 28.4
}
```

## `GET /goals`

Response (404 if the user hasn't onboarded yet):

```json
{
  "tracking_mode": "goals",
  "kcal_goal": 2200.0,
  "protein_goal": 140.0,
  "fiber_goal": 30.0,
  "dietary_prefs": {},
  "first_meal_time": "08:00",
  "streak_days": 4
}
```

## `POST /goals`

Create goals (409 if already onboarded). `tracking_mode` is `"goals"` or
`"mindful"`; `kcal_goal`/`protein_goal`/`fiber_goal` are required when
`tracking_mode == "goals"`.

Request:

```json
{
  "tracking_mode": "goals",
  "kcal_goal": 2200.0,
  "protein_goal": 140.0,
  "fiber_goal": 30.0,
  "dietary_prefs": {},
  "first_meal_time": "08:00"
}
```

Response: same `GoalResponse` shape as `GET /goals`, 201.

## `PUT /goals`

Same request/response shape as `POST /goals`; 404 if not yet onboarded.

## `GET /quota`

Response:

```json
{
  "used": 12,
  "limit": 50,
  "remaining": 38,
  "exhausted": false,
  "tier": "free"
}
```

## `GET /my-meals`

Saved "quick log" meals. Response: list of

```json
{
  "id": "meal_1",
  "name": "Usual breakfast",
  "kcal": 450.0,
  "protein_g": 28.0,
  "carbs_g": 40.0,
  "fat_g": 18.0,
  "fiber_g": 6.0,
  "n_ingredients": 3,
  "logged_today": false
}
```

## `GET /my-meals/{id}`

Same fields as the list item, plus `ingredients: [...]` (full stored
ingredient dicts, extra fields preserved). 404 if not found or not owned by
the caller.

## `POST /my-meals`

Save a new quick-log meal.

Request:

```json
{
  "name": "Usual breakfast",
  "ingredients": [
    { "food_name": "egg", "qty_g": 100, "kcal": 155, "protein_g": 13, "carbs_g": 1.1, "fat_g": 11, "fiber_g": 0 }
  ]
}
```

Response: `MyMealSummary` (same shape as one `GET /my-meals` list item), 201.
Totals (`kcal`, macros) are always recomputed server-side from
`ingredients` — client-supplied totals are never trusted.

## `DELETE /my-meals/{id}`

Soft-delete a saved meal. 204, no body.

## `POST /my-meals/{id}/log`

Log a saved meal (quick-log, or customized). Omit `ingredients` for a 1x
quick-log of everything as saved; provide it to keep only the listed
ingredients (by stored `index`) at their edited `qty_g` — the rest are
dropped.

Request:

```json
{
  "meal_type": "lunch",
  "portion": 1.0,
  "ingredients": [ { "index": 0, "qty_g": 120 } ]
}
```

Response: `MealLogResult` — same shape as `POST /meals/log-items`.

## `POST /devices/register`

Upsert an FCM push token. Re-registering the same token rebinds it to the
current user (a device switching accounts moves the token rather than
duplicating it).

Request:

```json
{ "token": "fcm-token-string", "platform": "fcm" }
```

Response: `{"status": "registered"}`, 201.

## `DELETE /devices/{token}`

Remove a device token for the authenticated user (e.g. on logout). 204, no
body. Only removes the token if it belongs to the caller.

## `GET /meta/app`

**Unauthed.** Android client version gate — call before/independently of
login to decide whether the installed build may run at all.

Response:

```json
{ "min_supported_version_code": 1, "latest_version_code": 1 }
```

Sourced from env vars `ANDROID_MIN_VERSION_CODE` / `ANDROID_LATEST_VERSION_CODE`
(both default to `1`). A client whose own version code is below
`min_supported_version_code` must block usage and prompt a mandatory
upgrade; a client between `min_supported_version_code` and
`latest_version_code` may show a dismissible soft-nudge.

## `DELETE /account`

Permanently deletes the caller's account: the Supabase Auth user and every
database row scoped to them (goals, meal logs, saved meals, memory,
summaries, nutrient checkups, Telegram link, integration tokens, device
tokens, push subscriptions, and LangGraph conversation history). This
cannot be undone.

204, no body, on success.

The Supabase Auth user is deleted first; if that call fails, the endpoint
returns `502` and **no data is deleted** — safe to retry. Once the auth
user is gone, database rows are removed in a single transaction.
