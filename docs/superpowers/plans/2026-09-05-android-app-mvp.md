# Android App MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Native Android client (Kotlin + Compose) for Mealsy: Supabase login, chat-based meal logging with an editable confirmation card, today header, offline direct-log replay, FCM push, version gate.

**Architecture:** Three Gradle modules under `android/` — `core:domain` (pure Kotlin: models + card-edit logic, KMP-ready), `core:data` (Retrofit API, supabase-kt session, Room offline queue, repositories), `app` (Compose UI, Hilt wiring, FCM service). All server state flows through repositories; UI state via `ViewModel` + `StateFlow`.

**Tech Stack:** Kotlin 2.0 · AGP 8.5+ · Compose BOM + Material 3 · Hilt · Retrofit 2.11 + kotlinx.serialization · supabase-kt 2.x (`gotrue-kt`) · Room 2.6 · WorkManager 2.9 · CameraX · firebase-messaging · JUnit4 + MockWebServer + Turbine + Robolectric for data tests.

**Spec:** `docs/specs/2026-09-05-android-launch.md` (§4)

## Global Constraints

- Package root `app.mealsy.android`; `minSdk 26`, `targetSdk 35`, `versionCode` starts at 1.
- `core:domain` must have **zero** Android/AndroidX dependencies (enforced: its build.gradle.kts applies only `kotlin("jvm")` + kotlinx-serialization).
- All API DTOs use kotlinx.serialization with `ignoreUnknownKeys = true` (backend contract: unknown fields must be ignored).
- Backend base URL from `BuildConfig.API_BASE_URL` (debug: `http://10.0.2.2:8000`, release: prod URL); Supabase URL/anon key likewise BuildConfig fields from `local.properties` — never hardcoded, never committed.
- Every network write except `POST /meals/log` is retry-safe; `POST /meals/log` is never auto-retried (contract doc `docs/reference/mobile-api.md`).
- Unit tests run with `./gradlew :core:domain:test :core:data:test`; commit after each green task.
- Manual prerequisites (do once, before Task 4 / Task 9): add Android deep link `mealsy://auth-callback` to Supabase Auth → URL Configuration; create Firebase project + download `android/app/google-services.json` (gitignored template note in README).

---

### Task 1: Gradle skeleton + CI-able build

**Files:**
- Create: `android/settings.gradle.kts`, `android/build.gradle.kts`, `android/gradle/libs.versions.toml`, `android/gradle.properties`, `android/app/build.gradle.kts`, `android/core/domain/build.gradle.kts`, `android/core/data/build.gradle.kts`, `android/app/src/main/AndroidManifest.xml`, `android/app/src/main/java/app/mealsy/android/MainActivity.kt`, `android/app/src/main/java/app/mealsy/android/MealsyApp.kt`, `android/.gitignore`
- Modify: repo root `.gitignore` (add `android/local.properties`, `android/app/google-services.json`)

**Interfaces:**
- Produces: modules `:app`, `:core:domain`, `:core:data`; version catalog aliases used by all later tasks (`libs.retrofit`, `libs.room.runtime`, `libs.supabase.gotrue`, `libs.hilt.android`, etc.); `MealsyApp : Application` annotated `@HiltAndroidApp`; `MainActivity` rendering a placeholder `Text("Mealsy")`.

- [ ] **Step 1:** Write the version catalog (`libs.versions.toml`) pinning: kotlin 2.0.x, agp 8.5.x, compose-bom, hilt 2.51, retrofit 2.11, kotlinx-serialization 1.7, okhttp 4.12, room 2.6.1, work 2.9, supabase-kt 2.6 (`io.github.jan-tennert.supabase:gotrue-kt`), camerax 1.3, firebase-bom, junit4, mockwebserver, turbine, robolectric, coroutines-test.
- [ ] **Step 2:** Write the three `build.gradle.kts` files. `core:domain`: `kotlin("jvm")` + serialization only. `core:data`: android-library, Hilt, Retrofit, Room (ksp), supabase-kt, depends on `:core:domain`. `app`: android-application, Compose, Hilt, CameraX, WorkManager, firebase-messaging (google-services plugin applied **conditionally**: `if (file("google-services.json").exists())` so the build works before Firebase setup), depends on both cores. BuildConfig fields `API_BASE_URL`, `SUPABASE_URL`, `SUPABASE_ANON_KEY` read from `local.properties` with debug defaults (`http://10.0.2.2:8000`, empty, empty).
- [ ] **Step 3:** `MealsyApp.kt` (`@HiltAndroidApp class MealsyApp : Application()`), `MainActivity.kt` (`@AndroidEntryPoint`, `setContent { MaterialTheme { Text("Mealsy") } }`), manifest with `MainActivity` exported + launcher intent filter and `<uses-permission android:name="android.permission.INTERNET"/>`.
- [ ] **Step 4:** Verify: `cd android && ./gradlew :app:assembleDebug` → BUILD SUCCESSFUL (generate the wrapper first: `gradle wrapper --gradle-version 8.9` or copy from a new AS project).
- [ ] **Step 5:** Commit: `git add android/ .gitignore && git commit -m "feat(android): gradle skeleton — app + core:domain + core:data"`

---

### Task 2: Domain models + card edit logic (pure Kotlin, TDD)

**Files:**
- Create: `android/core/domain/src/main/kotlin/app/mealsy/domain/CardItem.kt`, `.../ConfirmationCard.kt`, `.../CardEditor.kt`
- Test: `android/core/domain/src/test/kotlin/app/mealsy/domain/CardEditorTest.kt`

**Interfaces:**
- Produces (used by Tasks 3, 6, 7):

```kotlin
@Serializable
data class CardItem(
    val foodName: String,
    val qtyG: Double,          // resolved base weight (scaling base)
    val targetQtyG: Double,    // user-edited weight
    val kcal: Double, val proteinG: Double, val carbsG: Double,
    val fatG: Double, val fiberG: Double,
    val fdcId: Long, val estimated: Boolean = false,
    val extras: JsonObject = JsonObject(emptyMap()),  // verbatim passthrough
)

data class ConfirmationCard(
    val message: String,
    val items: List<CardItem>,
    val mealType: String = "unspecified",
    val portion: Double = 1.0,
)

object CardEditor {
    fun removeItem(card: ConfirmationCard, index: Int): ConfirmationCard
    fun editQty(card: ConfirmationCard, index: Int, newQtyG: Double): ConfirmationCard
    fun setPortion(card: ConfirmationCard, portion: Double): ConfirmationCard
    fun totals(card: ConfirmationCard): Totals  // Totals(kcal, proteinG) scaled by targetQty/qty * portion
}
```

- [ ] **Step 1: Failing tests** — `CardEditorTest`: `removeItem drops the row`, `editQty rejects nonpositive (throws IllegalArgumentException)`, `totals scale linearly with targetQtyG` (item 100 g/200 kcal edited to 150 g → 300 kcal), `totals scale with portion` (portion 0.5 halves), `removing last item yields empty items (Confirm disabled is UI concern, not thrown here)`.
- [ ] **Step 2:** Run `./gradlew :core:domain:test` → FAIL (unresolved references).
- [ ] **Step 3:** Implement the three files exactly per the interface block; scaling: `factor = (targetQtyG / qtyG) * portion`, applied to all five macros.
- [ ] **Step 4:** `./gradlew :core:domain:test` → PASS.
- [ ] **Step 5:** Commit: `feat(android): domain card model and edit logic`

---

### Task 3: API client + DTOs (MockWebServer TDD)

**Files:**
- Create in `android/core/data/src/main/kotlin/app/mealsy/data/api/`: `MealsyApi.kt` (Retrofit interface), `Dtos.kt`, `AuthInterceptor.kt`, `ApiModule.kt` (Hilt)
- Test: `android/core/data/src/test/kotlin/app/mealsy/data/api/MealsyApiTest.kt`

**Interfaces:**
- Consumes: Task 2's `CardItem` mapping (`Dtos.kt` provides `LogTurnResponse.toCard(): ConfirmationCard?`).
- Produces (Retrofit interface used by repositories in Tasks 5–7):

```kotlin
interface MealsyApi {
    @POST("meals/log") suspend fun logTurn(@Body body: LogTurnRequest): LogTurnResponse
    @GET("meals/pending") suspend fun pending(@Query("conversation_id") id: String): LogTurnResponse
    @POST("meals/log-items") suspend fun logItems(@Body body: LogItemsRequest): LogItemsResponse
    @GET("meals/today") suspend fun today(): TodayResponse
    @GET("goals") suspend fun goals(): GoalsResponse
    @GET("quota") suspend fun quota(): QuotaResponse
    @POST("devices/register") suspend fun registerDevice(@Body body: RegisterDeviceRequest)
    @DELETE("devices/{token}") suspend fun deleteDevice(@Path("token") token: String)
    @GET("meta/app") suspend fun appMeta(): AppMetaResponse
}
```

DTO field names mirror the backend JSON exactly via `@SerialName` (`user_input`, `conversation_id`, `image_b64`, `meal_type`, `action`, `client_request_id`, `target_qty_g`, `min_supported_version_code`, …). `LogTurnResponse(status, message, paused, items, deduplicated=false)`; `LogItemsRequest(mealType, portion, clientRequestId, items)`.
- `AuthInterceptor(tokenProvider: suspend () -> String?)`: adds `Authorization: Bearer`; on 401 response, asks `tokenProvider` for a **forced-refresh** token once and replays; second 401 propagates.

- [ ] **Step 1: Failing tests** with MockWebServer: `logTurn serializes snake_case body` (enqueue 200, assert recorded request JSON contains `"user_input"`), `paused card parses items`, `401 triggers one refresh retry` (enqueue 401 then 200; fake tokenProvider counts calls == 2), `unknown response fields ignored` (extra key in JSON parses fine).
- [ ] **Step 2:** `./gradlew :core:data:test` → FAIL.
- [ ] **Step 3:** Implement DTOs (`Json { ignoreUnknownKeys = true; explicitNulls = false }`), Retrofit + OkHttp with `AuthInterceptor` as an OkHttp `Interceptor` (do the refresh-retry in `intercept` via `runBlocking` — standard OkHttp pattern; document why), `ApiModule` providing `MealsyApi` singleton from `BuildConfig.API_BASE_URL`.
- [ ] **Step 4:** `./gradlew :core:data:test` → PASS.
- [ ] **Step 5:** Commit: `feat(android): retrofit client with auth refresh-once interceptor`

---

### Task 4: Supabase auth session

**Files:**
- Create: `android/core/data/src/main/kotlin/app/mealsy/data/auth/SessionManager.kt`, `AuthModule.kt`
- Modify: `android/app/src/main/AndroidManifest.xml` (deep-link intent filter), `MainActivity.kt` (handle deep link)
- Test: `android/core/data/src/test/kotlin/app/mealsy/data/auth/SessionManagerTest.kt`

**Interfaces:**
- Produces:

```kotlin
class SessionManager @Inject constructor(private val gotrue: Auth) {
    val sessionState: StateFlow<SessionState>   // Loading | SignedOut | SignedIn(userId)
    suspend fun signInWithMagicLink(email: String)
    suspend fun signInWithGoogle(activity: Activity)   // supabase-kt OAuth flow
    suspend fun currentToken(forceRefresh: Boolean = false): String?
    suspend fun signOut()   // also calls api.deleteDevice(fcmToken) best-effort (wired in Task 9)
}
```

Task 3's `AuthInterceptor` gets `SessionManager::currentToken` injected as its provider (bind in `AuthModule`).
- supabase-kt config: `installGotrue { scheme = "mealsy"; host = "auth-callback"; flowType = FlowType.PKCE }`, URL/key from BuildConfig; session persisted by supabase-kt's default settings storage.

- [ ] **Step 1: Failing tests** (fake `Auth` via interface seam or supabase-kt test artifact): `sessionState is SignedIn after gotrue emits a session`, `currentToken(forceRefresh=true) calls refreshSession`, `signOut clears state`.
- [ ] **Step 2:** RED run. **Step 3:** implement; manifest gains `<intent-filter>` with `mealsy` scheme / `auth-callback` host on `MainActivity` (`launchMode="singleTask"`), and `MainActivity.onNewIntent` forwards the URI to supabase-kt's `handleDeeplinks(intent)`. **Step 4:** GREEN run + manual check: magic-link email → tap → app resumes signed in (needs the Supabase dashboard redirect URL prerequisite). **Step 5:** commit `feat(android): supabase PKCE auth with deep-link callback`.

---

### Task 5: Login + version-gate screens

**Files:**
- Create: `android/app/src/main/java/app/mealsy/android/ui/login/LoginScreen.kt`, `LoginViewModel.kt`, `ui/gate/UpdateRequiredScreen.kt`, `ui/AppNav.kt`
- Test: `android/app/src/test/java/app/mealsy/android/ui/login/LoginViewModelTest.kt`

**Interfaces:**
- Consumes: `SessionManager` (Task 4), `MealsyApi.appMeta()` (Task 3).
- Produces: `AppNav` composable — routes `login`, `chat`; startup logic: `appMeta()` (3 s timeout, failure = proceed) → if `BuildConfig.VERSION_CODE < min_supported_version_code` show `UpdateRequiredScreen` (Play Store button, no bypass); else route on `sessionState`.

- [ ] **Step 1: Failing ViewModel tests** (Turbine): `submit email calls signInWithMagicLink and enters AwaitingEmail state`, `invalid email shows error, no call`, `gate blocks when versionCode below min`.
- [ ] **Step 2:** RED. **Step 3:** implement screens — login: email field + "Send magic link" + Google button; states Idle/AwaitingEmail/Error. **Step 4:** GREEN + `./gradlew :app:assembleDebug`. **Step 5:** commit `feat(android): login and version-gate screens`.

---

### Task 6: Chat screen + confirmation card

**Files:**
- Create: `android/core/data/src/main/kotlin/app/mealsy/data/repo/ChatRepository.kt`; `android/app/src/main/java/app/mealsy/android/ui/chat/ChatScreen.kt`, `ChatViewModel.kt`, `ConfirmationCardView.kt`, `TodayHeader.kt`
- Test: `android/core/data/src/test/.../repo/ChatRepositoryTest.kt`, `android/app/src/test/.../ui/chat/ChatViewModelTest.kt`, `android/app/src/androidTest/.../CardInteractionTest.kt` (Compose UI test)

**Interfaces:**
- Consumes: `MealsyApi`, `CardEditor`, `ConfirmationCard`.
- Produces:

```kotlin
class ChatRepository @Inject constructor(private val api: MealsyApi) {
    val conversationId: String                    // UUID, rotated after log/cancel
    suspend fun sendTurn(text: String, imageB64: String? = null): TurnResult
    suspend fun recoverPending(): ConfirmationCard?          // GET /meals/pending
    suspend fun confirmCard(card: ConfirmationCard): LogOutcome
        // → POST /meals/log-items with fresh clientRequestId (UUID.randomUUID)
    suspend fun cancelCard(): TurnResult          // sendTurn("cancel") on paused thread
}
sealed interface TurnResult { data class Reply(val message: String): TurnResult
    data class Card(val card: ConfirmationCard): TurnResult
    data class UpgradeRequired(val message: String): TurnResult }
```

`UpgradeRequired` is detected by `status == "quota_exhausted"` if present, else message-match fallback — check the backend `_UPGRADE_MSG` path in `orchestrator.py` during implementation and prefer a structured field (if none exists, file it as a backend follow-up and match on `paused==false && quota().remaining==0`).
- ChatViewModel state: `messages: List<ChatMsg>`, `pendingCard: ConfirmationCard?`, `sending: Boolean`, `offline: Boolean`; on init calls `recoverPending()`.

- [ ] **Step 1: Failing repository tests** (MockWebServer): `sendTurn maps paused response to Card`, `confirmCard posts client_request_id and edited target_qty_g`, `confirmCard on replayed 200 with deduplicated=true still returns success`, `recoverPending maps paused=false to null`, `conversationId rotates after confirm`.
- [ ] **Step 2:** RED. **Step 3:** implement repository.
- [ ] **Step 4: Failing ViewModel tests**: `send appends user bubble then card`, `edit qty updates totals via CardEditor`, `confirm disables card and appends success message`, `init restores pending card`.
- [ ] **Step 5:** implement ChatViewModel + Compose UI. Card UI: LazyColumn rows (name, qty `OutlinedTextField` numeric, kcal), swipe-to-remove, meal-type `SegmentedButton` (breakfast/lunch/snack/dinner), portion stepper, totals row, Confirm (disabled when items empty or sending) / Cancel. `TodayHeader`: kcal + protein progress vs goals, refreshed after every `LogOutcome`.
- [ ] **Step 6:** Compose UI test: editing a qty updates the totals text; remove hides the row.
- [ ] **Step 7:** `./gradlew :core:data:test :app:testDebugUnitTest` → PASS; UI test on emulator if available (`connectedDebugAndroidTest`), else mark step done with a note.
- [ ] **Step 8:** commit `feat(android): chat screen with editable confirmation card`

---

### Task 7: Offline direct-log queue (Room + WorkManager)

**Files:**
- Create: `android/core/data/src/main/kotlin/app/mealsy/data/offline/PendingLogEntity.kt`, `PendingLogDao.kt`, `MealsyDb.kt`, `ReplayWorker.kt`, `OfflineModule.kt`
- Modify: `ChatRepository.confirmCard` (queue on IOException)
- Test: `android/core/data/src/test/.../offline/ReplayWorkerTest.kt` (Robolectric + WorkManager test framework)

**Interfaces:**
- Consumes: `MealsyApi.logItems`, Task 2 serialization.
- Produces: `PendingLogEntity(clientRequestId pk, payloadJson, createdAt, attempts)`; `ReplayWorker` (CoroutineWorker, `Constraints(NetworkType.CONNECTED)`, backoff exponential 30 s): posts each row, deletes on 2xx **or** on `deduplicated=true`, gives up (deletes + logs) after 50 attempts or 7 days; `ChatRepository.confirmCard` catches `IOException`, persists the exact request payload (same clientRequestId), enqueues unique work `"replay-pending-logs"`, returns `LogOutcome.Queued`.

- [ ] **Step 1: Failing worker tests**: `success deletes row`, `deduplicated response deletes row`, `HTTP 500 keeps row (Result.retry)`, `422 deletes row and does not retry` (poison message — malformed payload will never succeed).
- [ ] **Step 2:** RED. **Step 3:** implement entity/dao/db/worker/module; wire queueing into `confirmCard`; ChatViewModel renders `Queued` as "Saved — will sync when you're back online" and the chat input shows the offline banner via a `ConnectivityManager` callback flow.
- [ ] **Step 4:** GREEN `./gradlew :core:data:test`. **Step 5:** commit `feat(android): offline replay queue for direct logs`

---

### Task 8: Camera capture → base64 turn

**Files:**
- Create: `android/app/src/main/java/app/mealsy/android/ui/chat/CameraSheet.kt`, `android/core/data/src/main/kotlin/app/mealsy/data/image/ImageEncoder.kt`
- Test: `android/core/data/src/test/.../image/ImageEncoderTest.kt` (Robolectric)

**Interfaces:**
- Produces: `ImageEncoder.encode(bitmap: Bitmap): String` — downscale longest edge to 1024 px, JPEG q80, base64 (no data-URI prefix; backend expects raw b64 in `image_b64`). CameraSheet returns a Bitmap to ChatViewModel, which calls `sendTurn("", imageB64 = encoded)`.

- [ ] **Step 1: Failing tests**: `encode caps longest edge at 1024`, `output decodes back to a JPEG`, `already-small bitmap not upscaled`.
- [ ] **Step 2:** RED. **Step 3:** implement encoder + CameraX capture sheet (permission rationale, capture button, retake/use). **Step 4:** GREEN + assembleDebug. **Step 5:** commit `feat(android): meal photo capture and b64 encoding`

---

### Task 9: FCM registration + notification deep link

**Files:**
- Create: `android/app/src/main/java/app/mealsy/android/push/MealsyMessagingService.kt`, `push/PushRegistrar.kt`
- Modify: manifest (service + `POST_NOTIFICATIONS` permission), `MainActivity` (notification-tap intent → chat), `SessionManager.signOut` (best-effort `deleteDevice`)
- Test: `android/app/src/test/.../push/PushRegistrarTest.kt`

**Interfaces:**
- Consumes: `MealsyApi.registerDevice/deleteDevice` (Task 3), backend contract from readiness plan Task 4 (`{token, platform:"fcm"}`).
- Produces: `PushRegistrar.ensureRegistered()` — called after sign-in and in `onNewToken`; requests `POST_NOTIFICATIONS` at first chat entry (API 33+); notifications with `data["deeplink"]=="mealsy://chat"` open ChatScreen.

- [ ] **Step 1: Failing tests**: `ensureRegistered posts current token once per token value` (idempotent via stored last-sent token in DataStore), `signOut deletes device token, swallows network failure`.
- [ ] **Step 2:** RED. **Step 3:** implement (guard everything behind `FirebaseApp.getApps(context).isNotEmpty()` so builds without google-services.json still run). **Step 4:** GREEN. **Step 5:** commit `feat(android): FCM registration and daily-summary deep link`

---

### Task 10: Release readiness

**Files:**
- Create: `android/README.md` (setup: local.properties keys, google-services.json, Supabase redirect URL, emulator-vs-device base URL), `android/app/proguard-rules.pro`
- Modify: `android/app/build.gradle.kts` (release build type: minify + shrink, signingConfig placeholder from env), `.github/workflows/android.yml` if a CI dir exists (else skip with note)

- [ ] **Step 1:** Proguard/R8 keep rules for kotlinx-serialization DTOs and Retrofit interfaces (standard published rules; verify `assembleRelease` output boots against staging).
- [ ] **Step 2:** `./gradlew :app:assembleRelease` → BUILD SUCCESSFUL; install release APK, full manual pass: login → log "2 eggs and toast" → edit qty → confirm → kill app → reopen (pending/today correct) → airplane-mode confirm → restore network → row synced → push test via backend `send_push_fcm` task.
- [ ] **Step 3:** Record the manual-pass checklist results in `android/README.md` under "Launch QA".
- [ ] **Step 4:** commit `chore(android): release build config and QA checklist`

---

## Self-review notes

- Spec §4 coverage: auth→T4/5, chat+card→T6, today header→T6, offline→T7, camera→T8, push→T9, version gate→T5, quota upsell→T6 (`UpgradeRequired`), contract compliance→T3 (`ignoreUnknownKeys`, retry rules). Trends/settings/my-meals: explicitly post-MVP per spec §2.
- Type consistency: `ConfirmationCard`/`CardItem`/`CardEditor` defined once in T2 and consumed by name in T3/T6/T7; `client_request_id` naming matches backend plan Task 2; `min_supported_version_code` matches backend plan Task 5.
- Known judgment call: quota-exhaustion detection (T6) depends on a backend field that may not exist — flagged inline with a concrete fallback.
