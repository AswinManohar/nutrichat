# Mealsy Android Launch — Spec

Date: 2026-09-05 · Branch: `feat/android-app` · Status: draft for implementation

## 1. Goal

Ship Mealsy as a native Android app (Kotlin + Jetpack Compose) as the primary
consumer client, backed by the existing FastAPI backend. Two workstreams:

- **A. Backend Android-readiness** — harden the API for mobile clients
  (bursty traffic, retries, flaky networks, push) *before* the first APK.
- **B. Android client (production)** — full consumer app: onboarding,
  chat-based logging with the confirmation card, today dashboard, trends,
  My Meals, settings with account deletion, crash reporting, push.

Each workstream has its own implementation plan and ships independently.
A must merge (and deploy to staging) before B's API-dependent tasks run
against a live backend, but B can develop against local `uvicorn` from day 1.

## 2. Non-goals (this launch)

- iOS (but Gradle modules are structured so a KMP split is possible later).
- Streaming/SSE (post-launch; the pending-card endpoint is the precursor).
- Mindful/nutrient-checkup surfaces and Telegram account linking stay
  web-only at launch (additive later; no API changes needed).
- **In-app purchases.** Google Play requires Play Billing for digital
  subscriptions and forbids linking out to external payment pages. Until
  Play Billing is implemented (post-launch plan), the over-quota state
  shows the limit plainly with NO upgrade link or price — upgrading
  happens on the web, unprompted by the app.
- Offline queueing of **chat** turns. Offline supports only direct
  (no-LLM) logging via `POST /meals/log-items` replay; free-text logging
  requires connectivity and says so in the UI.
- Web push. FCM replaces it for Android; the existing `push_subscription`
  table and `/push/*` routes stay untouched for the web app.

## 3. Backend Android-readiness (Workstream A)

### A1. Checkpointer pool sizing + loud exhaustion
`db/checkpointer.py`: pool `max_size` from env `CHECKPOINTER_POOL_SIZE`
(default 8), `timeout=5.0` so exhaustion raises `PoolTimeout` (→ 500 +
Logfire event) instead of stalling. Railway: web=8, worker=3, bot=2. Sum of
all pools must stay under the Supabase session-pooler cap (verify in
dashboard before deploy).

### A2. Idempotent direct logging
`POST /meals/log-items` accepts optional `client_request_id: str (UUID)`.
New nullable column `meal_log.client_request_id` + partial unique index on
`(user_id, client_request_id) WHERE client_request_id IS NOT NULL`
(migration 012). On conflict, return the existing row's result with
`"deduplicated": true` instead of inserting. This is both the offline-queue
replay guard and the mobile retry-storm defense.

### A3. Pending-card recovery
`GET /meals/pending?conversation_id=` → the paused confirmation card for
that thread, or `{"paused": false}`. Reads `graph.aget_state(config)`;
when `state.next` is non-empty, rebuild the same `{status, message, paused,
items}` dict the original `POST /meals/log` returned (items from
`state.values["usda_results"]`, message from the last AI message). Lets a
client that lost the response (process death, network drop) recover instead
of re-sending the turn (which would burn quota and re-extract).

### A4. FCM device registration + sender
- Migration 013: table `device_token(id uuid pk, user_id fk→user_goal
  cascade, platform text check in ('fcm'), token text unique, created_at,
  last_seen_at)`.
- `POST /devices/register {token, platform:"fcm"}` (authed, upsert on
  token: re-registration moves a token to the current user and bumps
  `last_seen_at`). `DELETE /devices/{token}` for sign-out.
- Celery task `send_push_fcm(user_id, title, body, data)` using
  `firebase-admin` (`FIREBASE_CREDENTIALS_JSON` env, service-account JSON
  string). `UNREGISTERED`/`INVALID_ARGUMENT` responses delete the token row.
- Wire-in (launch scope): `send_daily_summary_telegram`'s beat slot gains a
  sibling `send_daily_summary_push` at 07:00 that fans out one
  `send_push_fcm` per user with tokens (chunked: the beat task only
  enqueues per-user tasks).

### A5. App-version gate
`GET /meta/app` → `{"min_supported_version_code": int, "latest_version_code": int}`
from env `ANDROID_MIN_VERSION_CODE` / `ANDROID_LATEST_VERSION_CODE`
(default 1). Unauthed. The app checks at cold start; below-min shows a
blocking upgrade screen.

### A6. Account deletion (Play policy + GDPR)
`DELETE /account` (authed): hard-deletes the user's rows — `user_goal`
cascades to `meal_log`, `user_meal`, `user_memory`, summaries,
`nutrient_checkup`, `device_token`; plus `telegram_link`,
`integration_token`, `push_subscription`, LangGraph checkpoints for the
user's threads — then deletes the Supabase Auth user via the Admin API
(`SUPABASE_SERVICE_ROLE_KEY`, new env var). Returns 204. Google Play
requires in-app account deletion AND a web deletion URL for the store
listing (the web app gains the same button post-launch, calling this
endpoint).

### A7. Contract freeze
The response shapes of `POST /meals/log`, `POST /meals/log-items`,
`GET /meals/today`, `GET /goals`, `GET /quota` are frozen additive-only
from A-merge onward. Documented in `docs/reference/mobile-api.md`
(generated section from FastAPI's OpenAPI + hand-written invariants:
fields never removed/renamed; enums never shrink; unknown fields must be
ignored by clients).

Deferred from A (separate scaling plan, pre-launch but independent):
fact-extraction debounce, quota-consume-on-success, Celery chunking.

## 4. Android client — production scope (Workstream B)

### Product surface
1. **Auth**: email magic-link + Google OAuth via Supabase (PKCE, deep link
   `mealsy://auth-callback`). Session persisted; silent refresh.
2. **Chat / logging** (home screen): text input + camera button (CameraX →
   JPEG → base64). Turns render as chat bubbles; a paused turn renders the
   **confirmation card**: item rows (name, qty g editable, kcal/protein),
   remove item, meal-type picker, portion stepper, Confirm / Cancel.
   Confirm posts the edited card to `/meals/log-items` with a fresh
   `client_request_id`; corrections (swap food) go as text through
   `/meals/log`. On cold start, `GET /meals/pending` restores an
   unanswered card.
3. **Today header**: kcal + protein vs goal from `GET /meals/today` +
   `GET /goals`, refreshed after each log.
4. **Offline**: direct logs (card confirm) enqueue to Room and replay via
   WorkManager with the stored `client_request_id`; chat input is disabled
   offline with an explanatory banner.
5. **Push**: FCM token registered after login; notification tap deep-links
   to chat. 07:00 daily summary is the only notification at launch.
6. **Version gate**: `/meta/app` check at start.
7. **Quota**: over-quota reply renders as a distinct informational card —
   no upgrade link, no price (Play payments policy, see §2). Direct
   logging (`/meals/log-items`, no LLM) keeps working over quota.
8. **Onboarding**: first sign-in with no `user_goal` (GET /goals → 404)
   routes to a goal-setup flow (tracking mode, kcal/protein/fiber goals,
   dietary prefs) posting `POST /goals`; skippable with sensible defaults.
9. **Trends**: 7/30-day kcal + protein charts from `GET /meals/trends`,
   category breakdown from `GET /meals/categories`.
10. **My Meals**: list, save-from-card, quick-log, delete via `/my-meals`.
11. **Settings**: edit goals, notification toggle, sign out, **delete
    account** (double-confirm → `DELETE /account` → sign out), privacy
    policy link, app version.
12. **Production quality bar**: Crashlytics crash + non-fatal reporting;
    every network surface has loading/empty/error-with-retry states;
    TalkBack labels on all interactive elements and the card rows; session
    stored via supabase-kt with encrypted preferences storage; R8 enabled
    with tested rules; Play data-safety form drafted from the contract doc
    (data collected: email, meal text/photos, health-adjacent nutrition
    data — declared as health info, not shared, deletable).

### Technical stack
Kotlin 2.x · Jetpack Compose + Material 3 · Hilt · Retrofit +
kotlinx.serialization · supabase-kt (auth) · Room · WorkManager ·
CameraX · Firebase Messaging · JUnit5 + MockWebServer + Turbine for tests;
Compose UI tests for the card.

### Module layout (KMP-ready)
```
android/
├── app/            # Compose UI, navigation, DI wiring, FCM service
├── core/data/      # Retrofit API, DTOs, repositories, Room, auth session
└── core/domain/    # pure Kotlin: models, card edit logic, offline queue policy
```
`core/domain` has no Android dependencies (future KMP `commonMain`).

### API contract used (all existing unless marked A#)
`POST /meals/log` · `POST /meals/log-items` (+`client_request_id`, A2) ·
`GET /meals/pending` (A3) · `GET /meals/today` · `GET /meals/trends` ·
`GET /meals/categories` · `GET/POST/PUT /goals` · `GET /quota` ·
`GET/POST/DELETE /my-meals*` · `POST /devices/register` /
`DELETE /devices/{token}` (A4) · `GET /meta/app` (A5) ·
`DELETE /account` (A6). Auth: `Authorization: Bearer <supabase access token>`.

## 5. Risks / open questions
- Supabase Google OAuth on Android needs the Android client ID added in
  Supabase Auth settings + SHA-1 fingerprint in Google Cloud console
  (manual, pre-B4).
- Firebase project creation + `google-services.json` (manual, pre-B8).
- Image upload size: `image_b64` in JSON is fine at launch (client
  downscales to ≤1024px JPEG q80, ~150–300 KB); multipart upload is a
  post-launch improvement.
- Privacy policy document: must exist at a public URL before Play
  submission (listing + data-safety form reference it). Writing it is a
  small standalone task outside these plans; the settings screen links it.
- Play review timeline: first submission includes account-deletion review
  and health-data declarations; budget 1–2 weeks of review buffer.

## 6. Plans
- Workstream A: `docs/superpowers/plans/2026-09-05-android-backend-readiness.md`
- Workstream B: `docs/superpowers/plans/2026-09-05-android-app.md`
