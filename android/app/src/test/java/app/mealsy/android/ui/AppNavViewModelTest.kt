package app.mealsy.android.ui

import app.cash.turbine.test
import app.mealsy.data.api.AppMetaResponse
import app.mealsy.data.api.GoalsResponse
import app.mealsy.data.api.LogItemsRequest
import app.mealsy.data.api.LogItemsResponse
import app.mealsy.data.api.LogTurnRequest
import app.mealsy.data.api.LogTurnResponse
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.QuotaResponse
import app.mealsy.data.api.RegisterDeviceRequest
import app.mealsy.data.api.TodayResponse
import app.mealsy.data.auth.AuthGateway
import app.mealsy.data.auth.SessionManager
import app.mealsy.data.auth.SessionState
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test

/** Minimal [AuthGateway] fake — [AppNavViewModel] only reads [SessionManager.sessionState]. */
private class FakeAuthGateway : AuthGateway {
    override val sessionState = MutableStateFlow<SessionState>(SessionState.SignedOut)

    override suspend fun signInWithMagicLink(email: String) = Unit
    override suspend fun signInWithGoogle(activity: android.app.Activity) = Unit
    override suspend fun refreshCurrentSession(): String? = null
    override fun currentAccessTokenOrNull(): String? = null
    override suspend fun signOut() = Unit
}

/**
 * [MealsyApi] is a plain Retrofit interface, so it's faked directly rather than routed through
 * MockWebServer — no HTTP layer is under test here, only [AppNavViewModel]'s handling of
 * [MealsyApi.appMeta]'s result/timeout/failure.
 */
private class FakeMealsyApi(
    private val appMetaResult: (suspend () -> AppMetaResponse)? = null,
) : MealsyApi {
    override suspend fun logTurn(body: LogTurnRequest): LogTurnResponse = error("not used")
    override suspend fun pending(id: String): LogTurnResponse = error("not used")
    override suspend fun logItems(body: LogItemsRequest): LogItemsResponse = error("not used")
    override suspend fun today(): TodayResponse = error("not used")
    override suspend fun goals(): GoalsResponse = error("not used")
    override suspend fun quota(): QuotaResponse = error("not used")
    override suspend fun registerDevice(body: RegisterDeviceRequest) = error("not used")
    override suspend fun deleteDevice(token: String) = error("not used")

    override suspend fun appMeta(): AppMetaResponse =
        appMetaResult?.invoke() ?: error("appMetaResult not configured for this test")
}

@OptIn(ExperimentalCoroutinesApi::class)
class AppNavViewModelTest {

    private val dispatcher = StandardTestDispatcher()

    @Before
    fun setUp() {
        Dispatchers.setMain(dispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun sessionManager() = SessionManager(FakeAuthGateway())

    @Test
    fun `appMeta throws yields fail-open Ready`() = runTest {
        val api = FakeMealsyApi(appMetaResult = { throw RuntimeException("boom") })
        val viewModel = AppNavViewModel(api, sessionManager(), currentVersionCode = 5)

        viewModel.gateState.test {
            assertEquals(GateState.Checking, awaitItem())
            assertEquals(GateState.Ready, awaitItem())
        }
    }

    @Test
    fun `appMeta timeout yields fail-open Ready`() = runTest {
        val neverResolves = CompletableDeferred<AppMetaResponse>()
        val api = FakeMealsyApi(appMetaResult = {
            // Longer than AppNavViewModel's 3s withTimeout — never actually completes on its
            // own; withTimeout cancels this delay once the 3s window elapses.
            delay(10_000)
            neverResolves.await()
        })
        val viewModel = AppNavViewModel(api, sessionManager(), currentVersionCode = 5)

        viewModel.gateState.test {
            assertEquals(GateState.Checking, awaitItem())
            advanceTimeBy(3_001)
            assertEquals(GateState.Ready, awaitItem())
        }
    }

    @Test
    fun `min version above current yields UpdateRequired`() = runTest {
        val api = FakeMealsyApi(appMetaResult = {
            AppMetaResponse(minSupportedVersionCode = 10, latestVersionCode = 10)
        })
        val viewModel = AppNavViewModel(api, sessionManager(), currentVersionCode = 5)

        viewModel.gateState.test {
            assertEquals(GateState.Checking, awaitItem())
            assertEquals(GateState.UpdateRequired, awaitItem())
        }
    }

    @Test
    fun `current at or above min yields Ready`() = runTest {
        val atMin = FakeMealsyApi(appMetaResult = {
            AppMetaResponse(minSupportedVersionCode = 5, latestVersionCode = 5)
        })
        val atMinVm = AppNavViewModel(atMin, sessionManager(), currentVersionCode = 5)
        atMinVm.gateState.test {
            assertEquals(GateState.Checking, awaitItem())
            assertEquals(GateState.Ready, awaitItem())
        }

        val aboveMin = FakeMealsyApi(appMetaResult = {
            AppMetaResponse(minSupportedVersionCode = 5, latestVersionCode = 6)
        })
        val aboveMinVm = AppNavViewModel(aboveMin, sessionManager(), currentVersionCode = 6)
        aboveMinVm.gateState.test {
            assertEquals(GateState.Checking, awaitItem())
            assertEquals(GateState.Ready, awaitItem())
        }
    }
}
