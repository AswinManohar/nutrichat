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
./gradlew :app:bundleRelease      # release AAB — the artifact Play requires
./gradlew :app:assembleRelease    # release APK — sideload/QA only, NOT the Play artifact
```

Both release tasks share the same `release` build type (minified, shrunk
resources, `signingConfig` from env vars below), so the same "Release
signing" setup applies to whichever one you run. `bundleRelease` produces
the Android App Bundle at:

```
app/build/outputs/bundle/release/app-release.aab
```

Release builds fall back to the debug keystore when no signing env vars are
set (see "Release signing" below), so both tasks build locally without any
extra setup — the output just won't be Play-signed. Use `assembleRelease`
(APK) only for local sideload/manual QA on a device; upload the AAB from
`bundleRelease` to Play.

### Release signing

`app/build.gradle.kts` reads the release `signingConfig` from environment
variables:

```bash
export MEALSY_KEYSTORE_PATH=/path/to/release.keystore
export MEALSY_KEYSTORE_PASSWORD=...
export MEALSY_KEY_ALIAS=...
export MEALSY_KEY_PASSWORD=...
./gradlew :app:bundleRelease
```

If **any** of the four are unset or blank, the release build type silently
falls back to signing with the debug keystore instead — the build still
succeeds and still produces an `.aab`, but it is not signed with your
upload key and Play will reject it (or worse, accept the wrong signer).
Before uploading to Play:

- Confirm all four env vars are set and non-blank in the shell that invokes
  Gradle.
- Verify the signer of the produced AAB (e.g. `apksigner verify --print-certs`
  against the AAB's embedded APK, or inspect the bundle with `bundletool`)
  before uploading, rather than trusting that the env vars took effect.

Never commit a real keystore or these values to the repo, and never print
their values in logs or documentation.

**Play App Signing.** Play uses a two-key model:

- **Upload key** — the keystore referenced by `MEALSY_KEYSTORE_*` above.
  You sign every release build (both APK and AAB) with this key locally.
- **App signing key** — held by Google. When you upload an AAB signed with
  your upload key, Google Play re-signs it with the app signing key before
  distributing it to devices; end users never see your upload-key signature.

This means the local keystore in `MEALSY_KEYSTORE_PATH` is your *upload*
key, not the key end users' installs are ultimately signed with — losing it
means requesting an upload-key reset from Google, not losing the app.

**`versionCode` / `versionName`.** Both live in `app/build.gradle.kts`
(`defaultConfig`), currently `versionCode = 1`, `versionName = "1.0"`.

- `versionCode` — a plain integer Play uses to order releases. It must be
  **monotonically increasing** on every Play upload: bump it by at least 1
  each time, never reuse a value, never decrease it. Play rejects an
  upload whose `versionCode` isn't strictly greater than the current one.
- `versionName` — the user-facing string (semver, e.g. `"1.1.0"`). Play
  doesn't enforce anything about it; bump it to communicate the release to
  users/support, independent of the `versionCode` bump.

**R8 mapping / Crashlytics.** The `com.google.gms.google-services` and
`com.google.firebase.crashlytics` Gradle plugins are applied only when
`android/app/google-services.json` exists (see Setup step 2). Until that
file is present, R8's deobfuscation mapping is **not** uploaded to
Crashlytics on a release build — crash stack traces from a release binary
built before Firebase is configured will show obfuscated symbols.

### App update gate (backend)

The backend exposes `GET /meta/app` (`src/backend/api/meta.py`), driven by
two env vars read at request time:

| Var | Meaning | Default |
|---|---|---|
| `ANDROID_MIN_VERSION_CODE` | Floor `versionCode`. Clients below this must block and force an upgrade. | `1` |
| `ANDROID_LATEST_VERSION_CODE` | The newest available `versionCode`. Clients between min and latest may show a soft "update available" nudge rather than blocking. | `1` |

Raise both in the Railway backend environment in step with every Play
release that bumps `versionCode` in `app/build.gradle.kts` — otherwise the
gate keeps quoting a stale floor/latest and either blocks users
unnecessarily or fails to nudge them toward a release that's actually live.

### CI

`.github/workflows/android.yml` runs on pushes and PRs that touch
`android/**` or the workflow file itself. It:

- Sets up Temurin JDK 21 and Gradle (`gradle/actions/setup-gradle@v4`).
- Runs `./gradlew :app:assembleDebug :app:testDebugUnitTest :core:data:test
  :core:domain:test :core:ui:verifyRoborazziDebug --stacktrace` — a debug
  build, unit tests across `:app`/`:core:data`/`:core:domain`, and
  Roborazzi golden verification for `:core:ui`.
- Uploads Roborazzi diff artifacts (`android/core/ui/build/outputs/roborazzi`)
  on failure, for inspecting screenshot mismatches.
- Deliberately runs with **no** `google-services.json` or
  `local.properties` present, matching the constraint that the build must
  succeed without either.

It does **not** build, sign, or upload a release artifact (no
`assembleRelease`/`bundleRelease` step) — release builds and Play uploads
are a manual, local step per "Release signing" above.

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

## Store listing assets

- **Phone screenshots** — generated from the `:core:ui` Roborazzi goldens in
  `android/core/ui/src/test/screenshots/`, rendered at the design's
  reference width (390dp, per `ScreenshotTestBase`'s `w390dp-h844dp-xhdpi`
  qualifier) on the theme's cream canvas background
  (`MealsyTheme.colors.canvas`). Component goldens (e.g. `MealsyButton_*`,
  `ChatBubble_*`, `TotalsStrip_*`, `Olli_*`) are component-level captures,
  not full-screen shots — use them as visual reference for composing actual
  screen-level Play screenshots (e.g. chat, confirmation card, trends), not
  as the Play screenshots themselves.
- **Feature graphic** (1024x500) — should feature Olli the mascot (see
  `design/mascot/Olli.kt` in `:core:ui`), consistent with the in-app
  branding.
- **App icon** — 512x512, per Play's standard icon requirement.
- **Short description** / **full description** — standard Play listing
  copy fields; not yet drafted here.

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
  `DELETE /account` endpoint. A public web account-deletion URL,
  `https://<frontend-host>/account/delete`, is also required for the Play
  listing's data-safety section (Play requires a public URL, not just an
  in-app path) — see "Known launch prerequisites" below.
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
- Web account-deletion page at `https://<frontend-host>/account/delete` —
  required for the Play listing's data-safety deletion URL. Served by the
  Mealsy web frontend and requires `SUPABASE_SERVICE_ROLE_KEY` set in the
  production backend environment; without it, `DELETE /account` returns
  502 and deletes nothing (in-app deletion via Settings → Delete account
  hits the same endpoint and has the same requirement).
- Raise `ANDROID_MIN_VERSION_CODE` / `ANDROID_LATEST_VERSION_CODE` in the
  Railway backend environment to match the `versionCode` being uploaded
  (see "App update gate (backend)" above).
- Eval gate (`eval/run_eval.py`) run and green against the backend version
  the app is targeting, per repo root eval-harness convention.
