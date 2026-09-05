# Mealsy Android

Native Android client for Mealsy (see repo root `CLAUDE.md` for the product
overview). Kotlin, Jetpack Compose, Hilt, Retrofit, Room, supabase-kt.

## Setup

### 1. `local.properties`

Create `android/local.properties` (gitignored) with:

```properties
sdk.dir=/path/to/Android/sdk
API_BASE_URL=http://10.0.2.2:8000
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_ANON_KEY=eyJ...
PRIVACY_POLICY_URL=https://mealsy.app/privacy
```

Notes:
- `API_BASE_URL` — **on the Android emulator**, `10.0.2.2` is the host
  loopback alias (not `10.2.2.2` — a typo that silently fails to connect).
  On a **physical device** on the same network as your dev machine, use your
  machine's LAN IP instead (e.g. `http://192.168.1.20:8000`) — the emulator
  alias does not resolve on real hardware.
- `SUPABASE_URL` / `SUPABASE_ANON_KEY` — same project as the backend/web
  frontend (see repo root env vars).
- All four keys have safe debug defaults except the Supabase ones, which are
  required for auth to work at all — see `app/build.gradle.kts` for the
  `buildConfigField` fallbacks.

### 2. `google-services.json`

Create a Firebase project, add an Android app with package
`app.mealsy.android`, and download `google-services.json` into
`android/app/google-services.json` (gitignored). Without this file:
- The `com.google.gms.google-services` and
  `com.google.firebase.crashlytics` Gradle plugins are **not applied** (see
  the conditional `if (file("google-services.json").exists())` block in
  `app/build.gradle.kts`) — the build still succeeds.
- Push notifications and Crashlytics silently no-op (see
  `ErrorReporting`/`PushRegistrar`'s `FirebaseApp.getApps(context).isEmpty()`
  guards) rather than crashing.

### 3. Supabase dashboard redirect URL

Add `mealsy://auth-callback` under Authentication → URL Configuration →
Redirect URLs in the Supabase dashboard. Required for the magic-link /
OAuth PKCE deep link (`MainActivity`'s `mealsy://auth-callback` intent
filter) to resume the app after sign-in.

### 4. Build

```bash
cd android
./gradlew :app:assembleDebug      # debug build, installs against API_BASE_URL
./gradlew :app:assembleRelease    # release build (minified, shrunk resources)
```

Release builds fall back to the debug keystore when no signing env vars are
set (see "Release signing" below), so `assembleRelease` builds locally
without any extra setup — it just won't be Play-signed.

### Release signing

`app/build.gradle.kts` reads the release `signingConfig` from environment
variables:

```bash
export MEALSY_KEYSTORE_PATH=/path/to/release.keystore
export MEALSY_KEYSTORE_PASSWORD=...
export MEALSY_KEY_ALIAS=...
export MEALSY_KEY_PASSWORD=...
./gradlew :app:assembleRelease
```

If any of the four are unset, the release build type signs with the debug
keystore instead — never commit a real keystore or these values to the repo.

### CI

There is no `.github/` directory in this repo yet, so no GitHub Actions
workflow is configured. When CI is set up, wire in:
`./gradlew :app:assembleRelease :app:testDebugUnitTest :core:data:test`.

## Launch QA

Manual pass against a release build with `google-services.json` and a
staging `API_BASE_URL` configured. **PENDING USER RUN** — this environment
has no emulator/device, so none of the boxes below have been exercised; do
not treat them as verified until someone runs them.

- [ ] PENDING USER RUN — Login via magic link, land on chat screen signed in
- [ ] PENDING USER RUN — Log "2 eggs and toast", confirmation card appears
- [ ] PENDING USER RUN — Edit a row's quantity, totals update correctly
- [ ] PENDING USER RUN — Confirm the card, success message + today totals update
- [ ] PENDING USER RUN — Kill the app and reopen; pending/today state still correct
- [ ] PENDING USER RUN — Enable airplane mode, confirm a card (queued/offline banner shown)
- [ ] PENDING USER RUN — Restore network, queued row syncs automatically
- [ ] PENDING USER RUN — Trigger a push notification via the backend
      `send_push_fcm` Celery task, notification is received
- [ ] PENDING USER RUN — Onboarding flow completes end-to-end as a fresh user
- [ ] PENDING USER RUN — Save a My Meal, then quick-log it from My Meals
- [ ] PENDING USER RUN — Trends screen renders both 7-day and 30-day ranges
- [ ] PENDING USER RUN — Delete a second test account end-to-end (Settings →
      Delete account): rows gone from the DB, login on that account fails
      afterward
- [ ] PENDING USER RUN — Forced Crashlytics test crash appears in the
      Firebase console (add a temporary `throw RuntimeException("Test crash")`
      behind a debug-only button, trigger it, remove it before shipping)

## Play data-safety form (draft)

Draft answers for the Play Console "Data safety" section (spec §4.12).
Confirm final wording against the live Play Console UI before submitting —
category names and required disclosures change between Play releases.

**Data collected:**

| Data type | Collected | Purpose | Shared with third parties |
|---|---|---|---|
| Email address | Yes | Account management, authentication | No |
| Health info (meal descriptions, meal photos, nutrition/macro data) | Yes | App functionality (meal logging, nutrition tracking) | No |

- **Data sharing:** No data is shared with third parties.
- **Data deletion:** Users can delete their account and all associated data
  in-app via Settings → Delete account, which calls the backend
  `DELETE /account` endpoint.
- **Data encrypted in transit:** Yes (HTTPS/TLS to the backend and to
  Supabase; FCM tokens and push payloads likewise sent over TLS).
- **Data retention:** Meal and nutrition data is retained until the user
  deletes their account; deletion is immediate and irreversible.

## Known launch prerequisites

External steps that must be done outside this repo before submitting to
Play, none of which this task can complete from here:

- Firebase project created and `android/app/google-services.json` placed
  (see Setup step 2) — required for push and Crashlytics.
- Supabase Auth redirect URL `mealsy://auth-callback` added in the
  dashboard (see Setup step 3) — required for sign-in to complete.
- `SUPABASE_SERVICE_ROLE_KEY` set in the Railway backend environment —
  required for server-side account deletion and admin operations the app
  calls into.
- Privacy policy live at the URL configured as `PRIVACY_POLICY_URL` —
  required both in-app and for the Play Store listing (spec §5).
- Web account-deletion page calling `DELETE /account` — required for the
  Play listing's data-safety deletion URL; not yet built (in-app deletion
  via Settings → Delete account is the only working path today).
- Eval gate (`eval/run_eval.py`) run and green against the backend version
  the app is targeting, per repo root eval-harness convention.
