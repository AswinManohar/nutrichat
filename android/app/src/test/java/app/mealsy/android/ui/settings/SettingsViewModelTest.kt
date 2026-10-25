package app.mealsy.android.ui.settings

import app.mealsy.android.push.DeviceTokenStore
import app.mealsy.android.push.FcmTokenProvider
import app.mealsy.android.push.NotificationPermissionChecker
import app.mealsy.android.push.NotificationPermissionState
import app.mealsy.android.push.PushRegistrar
import app.mealsy.android.ui.onboarding.DEFAULT_FIBER_GOAL
import app.mealsy.android.ui.onboarding.DEFAULT_KCAL_GOAL
import app.mealsy.android.ui.onboarding.DEFAULT_PROTEIN_GOAL
import app.mealsy.android.ui.onboarding.OnboardingGoal
import app.mealsy.data.api.AppMetaResponse
import app.mealsy.data.api.CoachingFeedbackRequest
import app.mealsy.data.api.GoalRequest
import app.mealsy.data.api.GoalsResponse
import app.mealsy.data.api.LogItemsRequest
import app.mealsy.data.api.LogItemsResponse
import app.mealsy.data.api.LogMyMealRequest
import app.mealsy.data.api.LogTurnRequest
import app.mealsy.data.api.LogTurnResponse
import app.mealsy.data.api.MealLogDetailDto
import app.mealsy.data.api.MealLogSummaryDto
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.QuotaResponse
import app.mealsy.data.api.RegisterDeviceRequest
import app.mealsy.data.api.SaveMealRequest
import app.mealsy.data.api.TodayResponse
import app.mealsy.data.auth.AuthGateway
import app.mealsy.data.auth.ProfileMetadata
import app.mealsy.data.auth.SessionManager
import app.mealsy.data.auth.SessionState
import app.mealsy.data.repo.GoalsRepository
import app.mealsy.data.repo.Profile
import app.mealsy.data.repo.ProfileStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** Minimal [AuthGateway] fake, same convention as `SessionManagerTest`/`AppNavViewModelTest`. */
private class FakeAuthGateway(
    initialState: SessionState = SessionState.SignedIn(userId = "user-123"),
) : AuthGateway {
    override val sessionState = MutableStateFlow<SessionState>(initialState)
    var signOutCallCount = 0
        private set

    override suspend fun signInWithMagicLink(email: String) = Unit

    override suspend fun signInWithGoogle(activity: android.app.Activity) = Unit

    override suspend fun refreshCurrentSession(): String? = null

    override fun currentAccessTokenOrNull(): String? = null

    override suspend fun signOut() {
        signOutCallCount++
        sessionState.value = SessionState.SignedOut
    }

    var lastUpdatedProfileMetadata: Pair<String, String>? = null
        private set

    override suspend fun updateProfileMetadata(
        firstName: String,
        goalFocus: String,
    ) {
        lastUpdatedProfileMetadata = firstName to goalFocus
    }

    override suspend fun currentProfileMetadata(): ProfileMetadata? = null
}

/** In-memory [ProfileStore] fake, same convention as `OnboardingViewModelTest`'s. */
private class FakeProfileStore(initial: Profile = Profile()) : ProfileStore {
    private val state = MutableStateFlow(initial)
    override val profile: Flow<Profile> = state

    override suspend fun get(): Profile = state.value

    override suspend fun set(
        firstName: String?,
        goalFocus: String?,
    ) {
        state.value =
            state.value.copy(
                firstName = firstName ?: state.value.firstName,
                goalFocus = goalFocus ?: state.value.goalFocus,
            )
    }

    override suspend fun clear() {
        state.value = Profile()
    }
}

/**
 * [MealsyApi] faked directly, same convention as `OnboardingViewModelTest` —
 * no MockWebServer/HTTP layer under test here.
 */
private class FakeMealsyApi(
    private val onGoals: (suspend () -> GoalsResponse)? = null,
    private var onDeleteAccount: (suspend () -> Unit)? = null,
) : MealsyApi {
    /** Swaps the delete behavior mid-test, e.g. to simulate a retry that now succeeds. */
    fun setOnDeleteAccount(block: (suspend () -> Unit)?) {
        onDeleteAccount = block
    }

    var deleteAccountCallCount = 0
        private set

    override suspend fun logTurn(body: LogTurnRequest): LogTurnResponse = error("not used")

    override suspend fun pending(id: String): LogTurnResponse = error("not used")

    override suspend fun logItems(body: LogItemsRequest): LogItemsResponse = error("not used")

    override suspend fun today(): TodayResponse = error("not used")

    override suspend fun goals(): GoalsResponse = onGoals?.invoke() ?: error("onGoals not configured for this test")

    override suspend fun createGoals(body: GoalRequest): GoalsResponse = error("not used")

    val updateGoalsCalls = mutableListOf<GoalRequest>()

    override suspend fun updateGoals(body: GoalRequest): GoalsResponse {
        updateGoalsCalls += body
        return GoalsResponse(
            trackingMode = body.trackingMode,
            kcalGoal = body.kcalGoal,
            proteinGoal = body.proteinGoal,
            fiberGoal = body.fiberGoal,
            dietaryPrefs = body.dietaryPrefs,
        )
    }

    override suspend fun quota(): QuotaResponse = error("not used")

    override suspend fun registerDevice(body: RegisterDeviceRequest) = Unit

    override suspend fun deleteDevice(token: String) = Unit

    override suspend fun appMeta(): AppMetaResponse = AppMetaResponse(minSupportedVersionCode = 1, latestVersionCode = 1)

    override suspend fun trends(days: Int) = error("not used")

    override suspend fun categories(days: Int) = error("not used")

    override suspend fun myMeals() = error("not used")

    override suspend fun myMeal(id: String) = error("not used")

    override suspend fun saveMeal(body: SaveMealRequest) = error("not used")

    override suspend fun updateMyMeal(
        id: String,
        body: app.mealsy.data.api.UpdateMealRequest,
    ): app.mealsy.data.api.MyMealDetailDto = error("not used")

    override suspend fun logMyMeal(
        id: String,
        body: LogMyMealRequest,
    ) = error("not used")

    override suspend fun deleteMyMeal(id: String) = error("not used")

    override suspend fun listMealLogs(
        date: String?,
        mealType: String?,
    ): List<MealLogSummaryDto> = error("not used")

    override suspend fun mealLog(id: String): MealLogDetailDto = error("not used")

    override suspend fun deleteMealLog(id: String) = error("not used")

    override suspend fun searchFoods(
        q: String,
        qtyG: Double,
        limit: Int,
    ) = error("not used")

    override suspend fun getFood(
        fdcId: Long,
        qtyG: Double,
    ) = error("not used")

    override suspend fun deleteAccount() {
        deleteAccountCallCount++
        onDeleteAccount?.invoke() ?: Unit
    }

    override suspend fun coachingFeedback(
        id: String,
        body: CoachingFeedbackRequest,
    ) = error("not used")
}

private fun echoGoals() =
    GoalsResponse(
        trackingMode = "goals",
        kcalGoal = 2000.0,
        proteinGoal = 100.0,
        fiberGoal = 30.0,
    )

private class FakeDeviceTokenStore : DeviceTokenStore {
    private var token: String? = null
    private var remindersDisabled: Boolean = false

    override suspend fun getLastSentToken(): String? = token

    override suspend fun setLastSentToken(token: String) {
        this.token = token
    }

    override suspend fun clearLastSentToken() {
        token = null
    }

    override suspend fun isRemindersDisabled(): Boolean = remindersDisabled

    override suspend fun setRemindersDisabled(disabled: Boolean) {
        remindersDisabled = disabled
    }
}

/**
 * In-memory [NotificationPermissionChecker] fake — mirrors the real
 * [app.mealsy.android.push.AndroidNotificationPermissionChecker]'s
 * "permanently denied after [permanentlyDeniedAfter] requests" behavior
 * without touching `PackageManager`/`NotificationManagerCompat`.
 */
private class FakeNotificationPermissionChecker(
    private var granted: Boolean = true,
    private val permanentlyDeniedAfter: Int = 2,
) : NotificationPermissionChecker {
    var requestAttempts: Int = 0
        private set

    fun setGranted(value: Boolean) {
        granted = value
    }

    override suspend fun currentState(): NotificationPermissionState =
        when {
            granted -> NotificationPermissionState.GRANTED
            requestAttempts < permanentlyDeniedAfter -> NotificationPermissionState.ASKABLE
            else -> NotificationPermissionState.DENIED_PERMANENTLY
        }

    override suspend fun recordRequestAttempt() {
        requestAttempts++
    }
}

@OptIn(ExperimentalCoroutinesApi::class)
class SettingsViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @Before
    fun setUp() {
        Dispatchers.setMain(dispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun viewModel(
        api: FakeMealsyApi = FakeMealsyApi(onGoals = ::echoGoals),
        authGateway: FakeAuthGateway = FakeAuthGateway(),
        onSignOut: suspend () -> Unit = {},
        tokenStore: FakeDeviceTokenStore = FakeDeviceTokenStore(),
        notificationPermissionChecker: FakeNotificationPermissionChecker = FakeNotificationPermissionChecker(),
        profileStore: FakeProfileStore = FakeProfileStore(),
        fcmToken: String? = null,
    ): Quad<SettingsViewModel, FakeMealsyApi, FakeAuthGateway, FakeDeviceTokenStore> {
        val sessionManager = SessionManager(authGateway, onSignOut)
        // Production wires PushRegistrar and SettingsViewModel to the same
        // @Singleton DeviceTokenStore — sharing one fake here keeps the
        // reminder-toggle state coherent between them, same as real usage.
        val pushRegistrar =
            PushRegistrar(
                api = api,
                tokenStore = tokenStore,
                fcmTokenProvider = FcmTokenProvider { fcmToken },
            )
        val viewModel =
            SettingsViewModel(
                goalsRepository = GoalsRepository(api),
                sessionManager = sessionManager,
                api = api,
                pushRegistrar = pushRegistrar,
                tokenStore = tokenStore,
                notificationPermissionChecker = notificationPermissionChecker,
                profileStore = profileStore,
                currentVersionCode = 1,
                versionName = "1.0",
            )
        return Quad(viewModel, api, authGateway, tokenStore)
    }

    private data class Quad<A, B, C, D>(val first: A, val second: B, val third: C, val fourth: D)

    @Test
    fun `delete requires typed confirmation DELETE`() {
        assertFalse(isDeleteConfirmed(""))
        assertFalse(isDeleteConfirmed("delete"))
        assertFalse(isDeleteConfirmed("DELET"))
        assertTrue(isDeleteConfirmed("DELETE"))
    }

    @Test
    fun `goalFocusDefaults derives targets from the chosen goal, not a flat 2000`() {
        val maintain = goalFocusDefaults(OnboardingGoal.Maintain.key)
        assertEquals(2200.0, maintain.kcalGoal, 0.0)
        assertEquals(110.0, maintain.proteinGoal, 0.0) // round(2200 * 0.20 / 4)
        assertEquals(31.0, maintain.fiberGoal, 0.0) // round(14 * 2200 / 1000)

        val build = goalFocusDefaults(OnboardingGoal.Build.key)
        assertEquals(2600.0, build.kcalGoal, 0.0)
        assertEquals(195.0, build.proteinGoal, 0.0) // round(2600 * 0.30 / 4)
    }

    @Test
    fun `goalFocusDefaults falls back to flat defaults for Learn and unknown keys`() {
        val learn = goalFocusDefaults(OnboardingGoal.Learn.key)
        assertEquals(DEFAULT_KCAL_GOAL, learn.kcalGoal, 0.0)
        assertEquals(DEFAULT_PROTEIN_GOAL, learn.proteinGoal, 0.0)
        assertEquals(DEFAULT_FIBER_GOAL, learn.fiberGoal, 0.0)

        val unknown = goalFocusDefaults("not-a-real-goal")
        assertEquals(DEFAULT_KCAL_GOAL, unknown.kcalGoal, 0.0)
    }

    @Test
    fun `turning tracking on with no saved goals falls back to the goal-focus default, not flat 2000`() =
        runTest {
            val profileStore = FakeProfileStore(Profile(goalFocus = OnboardingGoal.Build.key))
            val api = FakeMealsyApi(onGoals = { error("404") })
            val (viewModel, _, _) = viewModel(api = api, profileStore = profileStore)
            dispatcher.scheduler.advanceUntilIdle()

            viewModel.setTrackingEnabled(true)
            dispatcher.scheduler.advanceUntilIdle()

            assertEquals(2600.0, viewModel.uiState.value.kcalGoal, 0.0)
            assertEquals(195.0, viewModel.uiState.value.proteinGoal, 0.0)
        }

    @Test
    fun `deleteAccount does nothing until confirmation text matches`() =
        runTest {
            val (viewModel, api, _) = viewModel()
            dispatcher.scheduler.advanceUntilIdle()

            viewModel.setDeleteConfirmationText("not quite")
            viewModel.deleteAccount()
            dispatcher.scheduler.advanceUntilIdle()

            assertEquals(0, api.deleteAccountCallCount)
            assertFalse(viewModel.uiState.value.signedOut)
        }

    @Test
    fun `delete calls api then signOut`() =
        runTest {
            val authGateway = FakeAuthGateway()
            var signOutHookCalled = false
            val (viewModel, api, _) =
                viewModel(
                    authGateway = authGateway,
                    onSignOut = { signOutHookCalled = true },
                )
            dispatcher.scheduler.advanceUntilIdle()

            viewModel.setDeleteConfirmationText("DELETE")
            viewModel.deleteAccount()
            dispatcher.scheduler.advanceUntilIdle()

            assertEquals(1, api.deleteAccountCallCount)
            assertEquals(1, authGateway.signOutCallCount)
            assertTrue(signOutHookCalled)
            assertTrue(viewModel.uiState.value.signedOut)
            assertNull(viewModel.uiState.value.deleteError)
        }

    @Test
    fun `api failure keeps account and shows error`() =
        runTest {
            val authGateway = FakeAuthGateway()
            val api =
                FakeMealsyApi(
                    onGoals = ::echoGoals,
                    onDeleteAccount = { error("boom") },
                )
            val (viewModel, _, _) = viewModel(api = api, authGateway = authGateway)
            dispatcher.scheduler.advanceUntilIdle()

            viewModel.setDeleteConfirmationText("DELETE")
            viewModel.deleteAccount()
            dispatcher.scheduler.advanceUntilIdle()

            assertEquals(1, api.deleteAccountCallCount)
            assertEquals(0, authGateway.signOutCallCount)
            assertFalse(viewModel.uiState.value.signedOut)
            assertTrue(viewModel.uiState.value.deleteError != null)
        }

    @Test
    fun `retrying deleteAccount after a failure can succeed`() =
        runTest {
            val authGateway = FakeAuthGateway()
            val api =
                FakeMealsyApi(
                    onGoals = ::echoGoals,
                    onDeleteAccount = { error("boom") },
                )
            val (viewModel, _, _) = viewModel(api = api, authGateway = authGateway)
            dispatcher.scheduler.advanceUntilIdle()
            viewModel.setDeleteConfirmationText("DELETE")
            viewModel.deleteAccount()
            dispatcher.scheduler.advanceUntilIdle()
            assertTrue(viewModel.uiState.value.deleteError != null)

            api.setOnDeleteAccount(null) // the retry now succeeds
            viewModel.deleteAccount()
            dispatcher.scheduler.advanceUntilIdle()

            assertEquals(2, api.deleteAccountCallCount)
            assertEquals(1, authGateway.signOutCallCount)
            assertTrue(viewModel.uiState.value.signedOut)
            assertNull(viewModel.uiState.value.deleteError)
        }

    @Test
    fun `sign out unregisters FCM token`() =
        runTest {
            // SettingsViewModel.signOut delegates to SessionManager.signOut, whose
            // best-effort FCM-deregistration hook (SignOutHook, wired in
            // PushModule/PushRegistrarSignOutHook in production) is exercised here
            // through the same seam SessionManagerTest uses.
            val authGateway = FakeAuthGateway()
            var hookCalled = false
            val (viewModel, _, _) = viewModel(authGateway = authGateway, onSignOut = { hookCalled = true })
            dispatcher.scheduler.advanceUntilIdle()

            viewModel.signOut()
            dispatcher.scheduler.advanceUntilIdle()

            assertTrue(hookCalled)
            assertEquals(1, authGateway.signOutCallCount)
            assertTrue(viewModel.uiState.value.signedOut)
        }

    @Test
    fun `toggling reminders off then a fresh sign-in ensureRegistered does not silently re-enable`() =
        runTest {
            // Regression: AppNavViewModel calls PushRegistrar.ensureRegistered()
            // unconditionally after every sign-in. Without the "disabled" flag
            // this toggle-off sets, that call would re-register the token this
            // test just deleted.
            val tokenStore = FakeDeviceTokenStore()
            val (viewModel, api, _, sharedTokenStore) =
                viewModel(tokenStore = tokenStore, fcmToken = "token-a")
            dispatcher.scheduler.advanceUntilIdle()
            // Register once first, as a real sign-in would.
            sharedTokenStore.setLastSentToken("token-a")

            viewModel.setReminderEnabled(false)
            dispatcher.scheduler.advanceUntilIdle()

            assertFalse(viewModel.uiState.value.reminderEnabled)
            assertNull(sharedTokenStore.getLastSentToken())
            assertTrue(sharedTokenStore.isRemindersDisabled())

            // Simulate AppNavViewModel's unconditional post-sign-in call.
            val pushRegistrar =
                PushRegistrar(
                    api = api,
                    tokenStore = sharedTokenStore,
                    fcmTokenProvider = FcmTokenProvider { "token-a" },
                )
            pushRegistrar.ensureRegistered()

            assertNull(sharedTokenStore.getLastSentToken())
        }

    @Test
    fun `toggling reminders on clears the disabled flag and registers`() =
        runTest {
            val tokenStore = FakeDeviceTokenStore()
            tokenStore.setRemindersDisabled(true)
            val (viewModel, _, _, sharedTokenStore) =
                viewModel(tokenStore = tokenStore, fcmToken = "token-a")
            dispatcher.scheduler.advanceUntilIdle()

            viewModel.setReminderEnabled(true)
            dispatcher.scheduler.advanceUntilIdle()

            assertFalse(sharedTokenStore.isRemindersDisabled())
            assertEquals("token-a", sharedTokenStore.getLastSentToken())
            assertTrue(viewModel.uiState.value.reminderEnabled)
        }

    @Test
    fun `toggling reminders on while permission is askable requests it, not turns on directly`() =
        runTest {
            val checker = FakeNotificationPermissionChecker(granted = false)
            val (viewModel, _, _) = viewModel(notificationPermissionChecker = checker)
            dispatcher.scheduler.advanceUntilIdle()

            var requested = false
            val collectJob = launch(dispatcher) { viewModel.requestNotificationPermission.collect { requested = true } }
            dispatcher.scheduler.advanceUntilIdle()

            viewModel.setReminderEnabled(true)
            dispatcher.scheduler.advanceUntilIdle()

            assertTrue(requested)
            assertFalse(viewModel.uiState.value.reminderEnabled)
            collectJob.cancel()
        }

    @Test
    fun `permission granted after request turns reminders on`() =
        runTest {
            val checker = FakeNotificationPermissionChecker(granted = false)
            val (viewModel, _, _, tokenStore) =
                viewModel(notificationPermissionChecker = checker, fcmToken = "token-a")
            dispatcher.scheduler.advanceUntilIdle()

            viewModel.onNotificationPermissionResult(granted = true)
            dispatcher.scheduler.advanceUntilIdle()

            assertTrue(viewModel.uiState.value.reminderEnabled)
            assertFalse(viewModel.uiState.value.notificationsBlocked)
            assertEquals("token-a", tokenStore.getLastSentToken())
        }

    @Test
    fun `permission denied twice shows the blocked message and keeps reminders off`() =
        runTest {
            val checker = FakeNotificationPermissionChecker(granted = false, permanentlyDeniedAfter = 2)
            val (viewModel, _, _) = viewModel(notificationPermissionChecker = checker)
            dispatcher.scheduler.advanceUntilIdle()

            viewModel.onNotificationPermissionResult(granted = false) // 1st denial: still askable
            dispatcher.scheduler.advanceUntilIdle()
            assertFalse(viewModel.uiState.value.notificationsBlocked)

            viewModel.onNotificationPermissionResult(granted = false) // 2nd denial: permanently denied
            dispatcher.scheduler.advanceUntilIdle()

            assertFalse(viewModel.uiState.value.reminderEnabled)
            assertTrue(viewModel.uiState.value.notificationsBlocked)
        }

    @Test
    fun `toggling reminders on while permanently denied shows the blocked message directly`() =
        runTest {
            val checker = FakeNotificationPermissionChecker(granted = false, permanentlyDeniedAfter = 0)
            val (viewModel, _, _) = viewModel(notificationPermissionChecker = checker)
            dispatcher.scheduler.advanceUntilIdle()

            viewModel.setReminderEnabled(true)
            dispatcher.scheduler.advanceUntilIdle()

            assertFalse(viewModel.uiState.value.reminderEnabled)
            assertTrue(viewModel.uiState.value.notificationsBlocked)
        }

    @Test
    fun `resuming with reminders on but permission revoked turns the switch off`() =
        runTest {
            val checker = FakeNotificationPermissionChecker(granted = true)
            val tokenStore = FakeDeviceTokenStore()
            val (viewModel, _, _) =
                viewModel(tokenStore = tokenStore, notificationPermissionChecker = checker, fcmToken = "token-a")
            dispatcher.scheduler.advanceUntilIdle()
            viewModel.setReminderEnabled(true)
            dispatcher.scheduler.advanceUntilIdle()
            assertTrue(viewModel.uiState.value.reminderEnabled)

            // The user revoked the permission from system settings, then came back.
            checker.setGranted(false)
            viewModel.onResume()
            dispatcher.scheduler.advanceUntilIdle()

            assertFalse(viewModel.uiState.value.reminderEnabled)
        }

    @Test
    fun `editing the name writes both ProfileStore and updateProfileMetadata`() =
        runTest {
            val authGateway = FakeAuthGateway()
            val profileStore = FakeProfileStore(Profile(firstName = "Sam", goalFocus = "maintain"))
            val (viewModel, _, _) = viewModel(authGateway = authGateway, profileStore = profileStore)
            dispatcher.scheduler.advanceUntilIdle()

            viewModel.startEditingName()
            viewModel.setNameDraft("Alex")
            viewModel.saveName()
            dispatcher.scheduler.advanceUntilIdle()

            assertEquals("Alex", viewModel.uiState.value.firstName)
            assertFalse(viewModel.uiState.value.editingName)
            assertEquals("Alex", profileStore.get().firstName)
            assertEquals("Alex" to "maintain", authGateway.lastUpdatedProfileMetadata)
        }

    @Test
    fun `changing goalFocus writes goal_focus and only prompts for a new kcal default in goals mode`() =
        runTest {
            val authGateway = FakeAuthGateway()
            val profileStore = FakeProfileStore()
            val api = FakeMealsyApi(onGoals = ::echoGoals)
            val (viewModel, _, _) = viewModel(api = api, authGateway = authGateway, profileStore = profileStore)
            dispatcher.scheduler.advanceUntilIdle()

            viewModel.selectGoalFocus(OnboardingGoal.Build)
            dispatcher.scheduler.advanceUntilIdle()

            assertEquals(OnboardingGoal.Build.key, viewModel.uiState.value.goalFocus)
            assertEquals("" to OnboardingGoal.Build.key, authGateway.lastUpdatedProfileMetadata)
            assertEquals(OnboardingGoal.Build.key, profileStore.get().goalFocus)
            assertEquals(OnboardingGoal.Build, viewModel.uiState.value.kcalPromptGoal)

            // In mindful mode, changing the goal focus must not surface the kcal prompt.
            val mindfulApi =
                FakeMealsyApi(
                    onGoals = { GoalsResponse(trackingMode = "mindful") },
                )
            val (mindfulViewModel, _, _) = viewModel(api = mindfulApi)
            dispatcher.scheduler.advanceUntilIdle()
            mindfulViewModel.selectGoalFocus(OnboardingGoal.Learn)
            dispatcher.scheduler.advanceUntilIdle()
            assertNull(mindfulViewModel.uiState.value.kcalPromptGoal)
        }

    @Test
    fun `toggling track daily targets off sends mindful with nulled goals, on restores or defaults`() =
        runTest {
            val api = FakeMealsyApi(onGoals = ::echoGoals)
            val (viewModel, capturedApi, _) = viewModel(api = api)
            dispatcher.scheduler.advanceUntilIdle()

            viewModel.setTrackingEnabled(false)
            dispatcher.scheduler.advanceUntilIdle()

            val offRequest = capturedApi.updateGoalsCalls.last()
            assertEquals("mindful", offRequest.trackingMode)
            assertNull(offRequest.kcalGoal)
            assertNull(offRequest.proteinGoal)
            assertNull(offRequest.fiberGoal)
            assertEquals("mindful", viewModel.uiState.value.trackingMode)

            viewModel.setTrackingEnabled(true)
            dispatcher.scheduler.advanceUntilIdle()

            val onRequest = capturedApi.updateGoalsCalls.last()
            assertEquals("goals", onRequest.trackingMode)
            // Restored from the goals fetched at load time (echoGoals: 2000/100/30).
            assertEquals(2000.0, onRequest.kcalGoal)
            assertEquals(100.0, onRequest.proteinGoal)
            assertEquals(30.0, onRequest.fiberGoal)

            // With no prior goals at all, toggling on falls back to the default
            // profile's goal focus ("maintain", the SettingsUiState default) —
            // 2200/110/31, not a flat 2000/100/30 that ignores it (#43).
            val neverHadGoalsApi = FakeMealsyApi(onGoals = { error("404") })
            val (freshViewModel, freshApi, _) = viewModel(api = neverHadGoalsApi)
            dispatcher.scheduler.advanceUntilIdle()
            freshViewModel.setTrackingEnabled(true)
            dispatcher.scheduler.advanceUntilIdle()
            val fallbackRequest = freshApi.updateGoalsCalls.last()
            assertEquals(2200.0, fallbackRequest.kcalGoal)
            assertEquals(110.0, fallbackRequest.proteinGoal)
            assertEquals(31.0, fallbackRequest.fiberGoal)
        }

    @Test
    fun `rapid stepper edits are debounced into a single PUT with the final value`() =
        runTest {
            val api = FakeMealsyApi(onGoals = ::echoGoals)
            val (viewModel, capturedApi, _) = viewModel(api = api)
            dispatcher.scheduler.advanceUntilIdle()
            capturedApi.updateGoalsCalls.clear()

            viewModel.setKcalGoal(2050.0)
            dispatcher.scheduler.advanceTimeBy(200)
            viewModel.setKcalGoal(2100.0)
            dispatcher.scheduler.advanceTimeBy(200)
            viewModel.setKcalGoal(2150.0)
            dispatcher.scheduler.advanceTimeBy(GOALS_SAVE_DEBOUNCE_MS + 100)

            assertEquals(1, capturedApi.updateGoalsCalls.size)
            assertEquals(2150.0, capturedApi.updateGoalsCalls.single().kcalGoal)
        }

    @Test
    fun `toggling a dietary pref sends the full dietary_prefs set`() =
        runTest {
            val api = FakeMealsyApi(onGoals = ::echoGoals)
            val (viewModel, capturedApi, _) = viewModel(api = api)
            dispatcher.scheduler.advanceUntilIdle()
            capturedApi.updateGoalsCalls.clear()

            viewModel.toggleDietaryPref("vegetarian")
            dispatcher.scheduler.advanceTimeBy(GOALS_SAVE_DEBOUNCE_MS + 100)
            viewModel.toggleDietaryPref("gluten_free")
            dispatcher.scheduler.advanceTimeBy(GOALS_SAVE_DEBOUNCE_MS + 100)

            val lastPrefs = capturedApi.updateGoalsCalls.last().dietaryPrefs.keys
            assertTrue("vegetarian" in lastPrefs)
            assertTrue("gluten_free" in lastPrefs)
        }
}
