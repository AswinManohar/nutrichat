package app.mealsy.android.ui.onboarding

import app.mealsy.data.api.AppMetaResponse
import app.mealsy.data.api.GoalRequest
import app.mealsy.data.api.GoalsResponse
import app.mealsy.data.api.LogItemsRequest
import app.mealsy.data.api.LogItemsResponse
import app.mealsy.data.api.LogTurnRequest
import app.mealsy.data.api.LogTurnResponse
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.QuotaResponse
import app.mealsy.data.api.RegisterDeviceRequest
import app.mealsy.data.api.TodayResponse
import app.mealsy.data.repo.GoalsRepository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * [MealsyApi] is a plain Retrofit interface — faked directly, same as
 * `AppNavViewModelTest`, so these tests exercise [OnboardingViewModel]'s
 * logic through the real [GoalsRepository] without a MockWebServer (goals
 * request/response wire shape is covered by `GoalsRepositoryTest`).
 */
private class FakeMealsyApi(
    private val onCreateGoals: ((GoalRequest) -> GoalsResponse)? = null,
) : MealsyApi {
    var lastCreateRequest: GoalRequest? = null

    override suspend fun logTurn(body: LogTurnRequest): LogTurnResponse = error("not used")
    override suspend fun pending(id: String): LogTurnResponse = error("not used")
    override suspend fun logItems(body: LogItemsRequest): LogItemsResponse = error("not used")
    override suspend fun today(): TodayResponse = error("not used")
    override suspend fun goals(): GoalsResponse = error("not used")

    override suspend fun createGoals(body: GoalRequest): GoalsResponse {
        lastCreateRequest = body
        return onCreateGoals?.invoke(body) ?: error("onCreateGoals not configured for this test")
    }

    override suspend fun updateGoals(body: GoalRequest): GoalsResponse = error("not used")
    override suspend fun quota(): QuotaResponse = error("not used")
    override suspend fun registerDevice(body: RegisterDeviceRequest) = error("not used")
    override suspend fun deleteDevice(token: String) = error("not used")
    override suspend fun appMeta(): AppMetaResponse = error("not used")
}

private fun echoResponse(body: GoalRequest) = GoalsResponse(
    trackingMode = body.trackingMode,
    kcalGoal = body.kcalGoal,
    proteinGoal = body.proteinGoal,
    fiberGoal = body.fiberGoal,
    dietaryPrefs = body.dietaryPrefs,
    firstMealTime = body.firstMealTime,
    streakDays = 0,
)

@OptIn(ExperimentalCoroutinesApi::class)
class OnboardingViewModelTest {

    private val dispatcher = StandardTestDispatcher()

    @Before
    fun setUp() {
        Dispatchers.setMain(dispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun viewModel(api: FakeMealsyApi = FakeMealsyApi(onCreateGoals = ::echoResponse)) =
        OnboardingViewModel(GoalsRepository(api)) to api

    @Test
    fun `defaults prefilled per backend`() = runTest {
        val (viewModel, _) = viewModel()

        val state = viewModel.uiState.value
        assertEquals("goals", state.trackingMode)
        assertEquals(2000.0, state.kcalGoal, 0.0)
        assertEquals(100.0, state.proteinGoal, 0.0)
        assertEquals(30.0, state.fiberGoal, 0.0)
    }

    @Test
    fun `save success navigates`() = runTest {
        val (viewModel, api) = viewModel()

        viewModel.save()
        dispatcher.scheduler.advanceUntilIdle()

        assertTrue(viewModel.uiState.value.done)
        assertEquals("goals", api.lastCreateRequest?.trackingMode)
        assertEquals(2000.0, api.lastCreateRequest?.kcalGoal)
    }

    @Test
    fun `skip creates defaults`() = runTest {
        val (viewModel, api) = viewModel()
        // Simulate the user having changed a value before hitting "Skip for now" —
        // skip must still post the untouched backend defaults, not the edited state.
        viewModel.setKcalGoal(3000.0)

        viewModel.skip()
        dispatcher.scheduler.advanceUntilIdle()

        assertTrue(viewModel.uiState.value.done)
        assertEquals(2000.0, api.lastCreateRequest?.kcalGoal)
        assertEquals(100.0, api.lastCreateRequest?.proteinGoal)
        assertEquals(30.0, api.lastCreateRequest?.fiberGoal)
        assertEquals("goals", api.lastCreateRequest?.trackingMode)
    }

    @Test
    fun `save failure surfaces error and does not navigate`() = runTest {
        val api = FakeMealsyApi(onCreateGoals = { error("boom") })
        val viewModel = OnboardingViewModel(GoalsRepository(api))

        viewModel.save()
        dispatcher.scheduler.advanceUntilIdle()

        assertTrue(viewModel.uiState.value.error != null)
        assertEquals(false, viewModel.uiState.value.done)
    }
}
