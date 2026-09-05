package app.mealsy.android.ui.settings

import app.mealsy.android.push.DeviceTokenStore
import app.mealsy.android.push.FcmTokenProvider
import app.mealsy.android.push.PushRegistrar
import app.mealsy.data.api.AppMetaResponse
import app.mealsy.data.api.GoalRequest
import app.mealsy.data.api.GoalsResponse
import app.mealsy.data.api.LogItemsRequest
import app.mealsy.data.api.LogItemsResponse
import app.mealsy.data.api.LogMyMealRequest
import app.mealsy.data.api.LogTurnRequest
import app.mealsy.data.api.LogTurnResponse
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.QuotaResponse
import app.mealsy.data.api.RegisterDeviceRequest
import app.mealsy.data.api.SaveMealRequest
import app.mealsy.data.api.TodayResponse
import app.mealsy.data.auth.AuthGateway
import app.mealsy.data.auth.SessionManager
import app.mealsy.data.auth.SessionState
import app.mealsy.data.repo.GoalsRepository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
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
}

/**
 * [MealsyApi] faked directly, same convention as `OnboardingViewModelTest` —
 * no MockWebServer/HTTP layer under test here.
 */
private class FakeMealsyApi(
    private val onGoals: (suspend () -> GoalsResponse)? = null,
    private val onDeleteAccount: (suspend () -> Unit)? = null,
) : MealsyApi {
    var deleteAccountCallCount = 0
        private set

    override suspend fun logTurn(body: LogTurnRequest): LogTurnResponse = error("not used")
    override suspend fun pending(id: String): LogTurnResponse = error("not used")
    override suspend fun logItems(body: LogItemsRequest): LogItemsResponse = error("not used")
    override suspend fun today(): TodayResponse = error("not used")

    override suspend fun goals(): GoalsResponse =
        onGoals?.invoke() ?: error("onGoals not configured for this test")

    override suspend fun createGoals(body: GoalRequest): GoalsResponse = error("not used")
    override suspend fun updateGoals(body: GoalRequest): GoalsResponse = error("not used")
    override suspend fun quota(): QuotaResponse = error("not used")
    override suspend fun registerDevice(body: RegisterDeviceRequest) = Unit
    override suspend fun deleteDevice(token: String) = Unit

    override suspend fun appMeta(): AppMetaResponse =
        AppMetaResponse(minSupportedVersionCode = 1, latestVersionCode = 1)

    override suspend fun trends(days: Int) = error("not used")
    override suspend fun categories(days: Int) = error("not used")
    override suspend fun myMeals() = error("not used")
    override suspend fun saveMeal(body: SaveMealRequest) = error("not used")
    override suspend fun logMyMeal(id: String, body: LogMyMealRequest) = error("not used")
    override suspend fun deleteMyMeal(id: String) = error("not used")

    override suspend fun deleteAccount() {
        deleteAccountCallCount++
        onDeleteAccount?.invoke() ?: Unit
    }
}

private fun echoGoals() = GoalsResponse(
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
        fcmToken: String? = null,
    ): Quad<SettingsViewModel, FakeMealsyApi, FakeAuthGateway, FakeDeviceTokenStore> {
        val sessionManager = SessionManager(authGateway, onSignOut)
        // Production wires PushRegistrar and SettingsViewModel to the same
        // @Singleton DeviceTokenStore — sharing one fake here keeps the
        // reminder-toggle state coherent between them, same as real usage.
        val pushRegistrar = PushRegistrar(
            api = api,
            tokenStore = tokenStore,
            fcmTokenProvider = FcmTokenProvider { fcmToken },
        )
        val viewModel = SettingsViewModel(
            goalsRepository = GoalsRepository(api),
            sessionManager = sessionManager,
            api = api,
            pushRegistrar = pushRegistrar,
            tokenStore = tokenStore,
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
    fun `deleteAccount does nothing until confirmation text matches`() = runTest {
        val (viewModel, api, _) = viewModel()
        dispatcher.scheduler.advanceUntilIdle()

        viewModel.setDeleteConfirmationText("not quite")
        viewModel.deleteAccount()
        dispatcher.scheduler.advanceUntilIdle()

        assertEquals(0, api.deleteAccountCallCount)
        assertFalse(viewModel.uiState.value.signedOut)
    }

    @Test
    fun `delete calls api then signOut`() = runTest {
        val authGateway = FakeAuthGateway()
        var signOutHookCalled = false
        val (viewModel, api, _) = viewModel(
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
    fun `api failure keeps account and shows error`() = runTest {
        val authGateway = FakeAuthGateway()
        val api = FakeMealsyApi(
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
    fun `sign out unregisters FCM token`() = runTest {
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
    fun `toggling reminders off then a fresh sign-in ensureRegistered does not silently re-enable`() = runTest {
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
        val pushRegistrar = PushRegistrar(
            api = api,
            tokenStore = sharedTokenStore,
            fcmTokenProvider = FcmTokenProvider { "token-a" },
        )
        pushRegistrar.ensureRegistered()

        assertNull(sharedTokenStore.getLastSentToken())
    }

    @Test
    fun `toggling reminders on clears the disabled flag and registers`() = runTest {
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
}
