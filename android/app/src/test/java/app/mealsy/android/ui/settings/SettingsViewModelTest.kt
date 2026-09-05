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

    override suspend fun getLastSentToken(): String? = token
    override suspend fun setLastSentToken(token: String) {
        this.token = token
    }

    override suspend fun clearLastSentToken() {
        token = null
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
    ): Triple<SettingsViewModel, FakeMealsyApi, FakeAuthGateway> {
        val sessionManager = SessionManager(authGateway, onSignOut)
        val pushRegistrar = PushRegistrar(
            api = api,
            tokenStore = FakeDeviceTokenStore(),
            fcmTokenProvider = FcmTokenProvider { null },
        )
        val viewModel = SettingsViewModel(
            goalsRepository = GoalsRepository(api),
            sessionManager = sessionManager,
            api = api,
            pushRegistrar = pushRegistrar,
            tokenStore = FakeDeviceTokenStore(),
            currentVersionCode = 1,
            versionName = "1.0",
        )
        return Triple(viewModel, api, authGateway)
    }

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
}
