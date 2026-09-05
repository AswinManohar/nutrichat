package app.mealsy.android.ui.onboarding

import app.mealsy.data.api.AppMetaResponse
import app.mealsy.data.api.GoalRequest
import app.mealsy.data.api.GoalsResponse
import app.mealsy.data.api.LogItemsRequest
import app.mealsy.data.api.LogItemsResponse
import app.mealsy.data.api.LogTurnRequest
import app.mealsy.data.api.LogTurnResponse
import app.mealsy.data.api.LogMyMealRequest
import app.mealsy.data.api.SaveMealRequest
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.QuotaResponse
import app.mealsy.data.api.RegisterDeviceRequest
import app.mealsy.data.api.TodayResponse
import app.mealsy.data.repo.GoalsRepository
import app.mealsy.domain.Goals
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Response

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
    override suspend fun trends(days: Int) = error("not used")
    override suspend fun categories(days: Int) = error("not used")
    override suspend fun myMeals() = error("not used")
    override suspend fun saveMeal(body: SaveMealRequest) = error("not used")
    override suspend fun logMyMeal(id: String, body: LogMyMealRequest) = error("not used")
    override suspend fun deleteMyMeal(id: String) = error("not used")
    override suspend fun deleteAccount() = error("not used")
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
    fun `defaults prefilled (app-chosen, not from a backend default)`() = runTest {
        val (viewModel, _) = viewModel()

        val state = viewModel.uiState.value
        assertEquals("goals", state.trackingMode)
        assertEquals(2000.0, state.kcalGoal, 0.0)
        assertEquals(100.0, state.proteinGoal, 0.0)
        assertEquals(30.0, state.fiberGoal, 0.0)
    }

    @Test
    fun `goal steppers clamp at a positive floor, never zero`() = runTest {
        val (viewModel, _) = viewModel()

        // Repeatedly stepping down (as the "-" stepper button does) must never reach 0 —
        // the backend rejects kcal_goal/protein_goal/fiber_goal <= 0 in "goals" mode.
        repeat(100) { viewModel.setKcalGoal(viewModel.uiState.value.kcalGoal - 50.0) }
        repeat(100) { viewModel.setProteinGoal(viewModel.uiState.value.proteinGoal - 5.0) }
        repeat(100) { viewModel.setFiberGoal(viewModel.uiState.value.fiberGoal - 5.0) }
        // Also clamp on a single, drastically negative input.
        viewModel.setKcalGoal(-1_000_000.0)
        viewModel.setProteinGoal(-1_000_000.0)
        viewModel.setFiberGoal(-1_000_000.0)

        val state = viewModel.uiState.value
        assertTrue("kcalGoal must be > 0, was ${state.kcalGoal}", state.kcalGoal > 0.0)
        assertTrue("proteinGoal must be > 0, was ${state.proteinGoal}", state.proteinGoal > 0.0)
        assertTrue("fiberGoal must be > 0, was ${state.fiberGoal}", state.fiberGoal > 0.0)
        assertEquals(MIN_KCAL_GOAL, state.kcalGoal, 0.0)
        assertEquals(MIN_PROTEIN_GOAL, state.proteinGoal, 0.0)
        assertEquals(MIN_FIBER_GOAL, state.fiberGoal, 0.0)
    }

    @Test
    fun `goalsSubmissionError flags a non-positive goal in goals mode with a specific message`() {
        val invalid = Goals(
            trackingMode = "goals",
            kcalGoal = 0.0,
            proteinGoal = 100.0,
            fiberGoal = 30.0,
        )

        val error = goalsSubmissionError(invalid)

        assertEquals("Calories goal must be greater than 0.", error)
    }

    @Test
    fun `goalsSubmissionError allows non-positive fields outside goals mode`() {
        val mindful = Goals(
            trackingMode = "mindful",
            kcalGoal = null,
            proteinGoal = null,
            fiberGoal = null,
        )

        assertNull(goalsSubmissionError(mindful))
    }

    @Test
    fun `submitting an invalid value does not call the API and shows the specific message`() = runTest {
        val (viewModel, api) = viewModel()
        val invalid = Goals(
            trackingMode = "goals",
            kcalGoal = 0.0,
            proteinGoal = 100.0,
            fiberGoal = 30.0,
        )

        viewModel.submit(invalid)
        dispatcher.scheduler.advanceUntilIdle()

        assertNull(api.lastCreateRequest)
        assertFalse(viewModel.uiState.value.done)
        assertEquals("Calories goal must be greater than 0.", viewModel.uiState.value.error)
    }

    @Test
    fun `409 from create is treated as success`() = runTest {
        val api = FakeMealsyApi(onCreateGoals = {
            throw HttpException(Response.error<Any>(409, "".toResponseBody(null)))
        })
        val viewModel = OnboardingViewModel(GoalsRepository(api))

        viewModel.save()
        dispatcher.scheduler.advanceUntilIdle()

        assertTrue(viewModel.uiState.value.done)
        assertNull(viewModel.uiState.value.error)
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
