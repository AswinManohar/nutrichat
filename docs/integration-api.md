# Integration API — read-only nutrition feed

A read-only API for third-party consumers (e.g. a personal "life-os" dashboard)
to poll a user's nutrition data. Lives under `/v1/integrations`.

## Authentication

Every endpoint requires a service token with the `nutrition:read` scope.
Tokens are minted offline (never via the API) and stored as a SHA-256 hash in
`integration_token`.

Mint a token:

```bash
DATABASE_URL=postgresql+asyncpg://... uv run python -m backend.scripts.mint_token \
    --user-id <uuid> --name "life-os"
```

The plaintext `nck_<...>` token is printed once and never stored — if lost,
mint a new one and revoke the old row (`UPDATE integration_token SET
revoked_at = now() WHERE id = ...`).

Send the token as either:

```
Authorization: Bearer nck_<token>
```

or

```
X-API-Key: nck_<token>
```

A missing, unknown, revoked token, or one without `nutrition:read` returns
`401`.

## Endpoints

All paginated endpoints share the shape `{items, next_cursor, has_more}` and
accept `since` (opaque cursor) and `limit` (default 100, max 500).

### `GET /v1/integrations/meals`

Returns `meal_log` rows updated since the cursor, oldest-first.

- **Active meals** include the macros, `entities`, `flags` and `micros`
  (the meal-level micronutrient summary, see below). `embedding` is never
  exposed.
- **Soft-deleted meals** are returned as tombstones:
  `{"meal_id": "...", "updated_at": "...", "deleted": true}` — all other
  fields are `null`/omitted. Consumers should remove the meal from their
  local cache on seeing a tombstone.
- **Edits resurface**: any update to a meal_log row (via the trigger-bumped
  `updated_at`) causes it to reappear on the next poll with its new values.

Dedup on `meal_id` — a consumer's local store should upsert by `meal_id`,
treating tombstones as deletes.

**`micros`** (spec 008) is `{key: {"total", "est", "known"}}` for every
tracked nutrient with at least one known value: `total` is the sum over the
meal's foods, `est` the AI-estimated part of it, `known` how many foods had a
value. A missing key means unknown, not zero. Keys and units come from
`GET /meta/nutrients`. `null` on tombstones.

> **Changelog 2026-10-03 (breaking):** `entities[].nutrients` (the per-item
> USDA nutrient map) is no longer stored or returned, and `entities[].sugar_g`
> / `sat_fat_g` are gone from stored items. Read micronutrients from the new
> meal-level `micros` field instead.

### `GET /v1/integrations/daily-summary`

Returns `daily_summary` rows updated since the cursor. Written nightly by
the `aggregate_daily_summary` Celery task (00:05). Not a live view of today —
see the `/meals/today` note below if you need same-day totals.

### `GET /v1/integrations/weekly-summary`

Returns `weekly_summary` rows updated since the cursor. Written by
`build_weekly_summary` (Sunday 23:00).

### `GET /v1/integrations/goals`

Returns the user's current goals and dietary preferences (not paginated):

```json
{
  "kcal_goal": 2200,
  "protein_goal": 150,
  "fiber_goal": 30,
  "dietary_prefs": {},
  "streak_days": 4
}
```

### `GET /v1/integrations/health`

`{"status": "ok", "version": "1.0"}` — liveness/version check.

## Cursor semantics

`next_cursor` is an opaque token: `base64("<updated_at_iso>|<id>")`. Pass it
back as `since` to fetch the next page. Pagination is a strict keyset compare
on `(updated_at, id) > (cursor_updated_at, cursor_id)`, so it is stable even
if new rows are inserted mid-poll (idempotent re-poll from the same cursor
never skips or duplicates rows beyond what's already been seen). `has_more`
is `true` only when more rows exist beyond the current page; when `false`,
`next_cursor` is `null` — re-poll with the same `since` value later to pick
up new changes.

## Limitations

- **Today's totals**: `meal_log` rows for "today" are written immediately,
  but the day's running totals also live in Redis (`/meals/today`, not part
  of this API) and `daily_summary` for today is not written until the
  nightly aggregation. To compute "today so far" from this API, sum active
  (non-deleted) `meals` rows for the current date yourself.
- **Polling ceiling**: poll no more than once per minute per resource.
  `limit` is capped at 500; use the cursor to page through larger backlogs.
- This API is strictly read-only — there is no way to write, edit, or delete
  data through it.
