package app.mealsy.android.data

import app.mealsy.data.api.AppMetaResponse
import app.mealsy.data.api.CategoryStatDto
import app.mealsy.data.api.CoachingFeedbackRequest
import app.mealsy.data.api.DayTrendDto
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
import app.mealsy.data.api.MyMealDetailDto
import app.mealsy.data.api.QuotaResponse
import app.mealsy.data.api.RegisterDeviceRequest
import app.mealsy.data.api.SaveMealRequest
import app.mealsy.data.api.SavedMealDto
import app.mealsy.data.api.TodayResponse
import app.mealsy.data.repo.GoalsRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.IOException

/**
 * A [MealsyApi] fake that counts `today()`/`goals()` calls and can hold each
 * response behind a suspending gate, so tests can force two [TodayRepository.get]
 * calls to overlap in time.
 */
private class CountingMealsyApi(
    private val todayGate: kotlinx.coroutines.CompletableDeferred<Unit>? = null,
    private var throwOnToday: Boolean = false,
) : MealsyApi {
    var todayCallCount = 0
        private set
    var goalsCallCount = 0
        private set

    override suspend fun today(): TodayResponse {
        todayCallCount++
        todayGate?.await()
        if (throwOnToday) throw IOException("offline")
        return TodayResponse(
            kcal = 1000.0,
            proteinG = 50.0,
            carbsG = 100.0,
            fatG = 30.0,
            fiberG = 10.0,
            nMeals = 2,
            byType = emptyList(),
        )
    }

    override suspend fun goals(): GoalsResponse {
        goalsCallCount++
        return GoalsResponse(
            trackingMode = "goals",
            kcalGoal = 2000.0,
            proteinGoal = 140.0,
            fiberGoal = 30.0,
            dietaryPrefs = JsonObject(emptyMap<String, JsonPrimitive>()),
        )
    }

    override suspend fun logTurn(body: LogTurnRequest): LogTurnResponse = notImplemented()

    override suspend fun pending(id: String): LogTurnResponse = notImplemented()

    override suspend fun logItems(body: LogItemsRequest): LogItemsResponse = notImplemented()

    override suspend fun createGoals(body: GoalRequest): GoalsResponse = notImplemented()

    override suspend fun updateGoals(body: GoalRequest): GoalsResponse = notImplemented()

    override suspend fun quota(): QuotaResponse = notImplemented()

    override suspend fun registerDevice(body: RegisterDeviceRequest): Unit = notImplemented()

    override suspend fun deleteDevice(token: String): Unit = notImplemented()

    override suspend fun appMeta(): AppMetaResponse = notImplemented()

    override suspend fun trends(days: Int): List<DayTrendDto> = notImplemented()

    override suspend fun categories(days: Int): List<CategoryStatDto> = notImplemented()

    override suspend fun myMeals(): List<SavedMealDto> = notImplemented()

    override suspend fun myMeal(id: String): MyMealDetailDto = notImplemented()

    override suspend fun saveMeal(body: SaveMealRequest): SavedMealDto = notImplemented()

    override suspend fun updateMyMeal(
        id: String,
        body: app.mealsy.data.api.UpdateMealRequest,
    ): app.mealsy.data.api.MyMealDetailDto = notImplemented()

    override suspend fun logMyMeal(
        id: String,
        body: LogMyMealRequest,
    ): LogItemsResponse = notImplemented()

    override suspend fun deleteMyMeal(id: String): Unit = notImplemented()

    override suspend fun listMealLogs(
        date: String?,
        mealType: String?,
    ): List<MealLogSummaryDto> = notImplemented()

    override suspend fun mealLog(id: String): MealLogDetailDto = notImplemented()

    override suspend fun deleteMealLog(id: String): Unit = notImplemented()

    override suspend fun searchFoods(
        q: String,
        qtyG: Double,
        limit: Int,
    ): app.mealsy.data.api.FoodSearchResponseDto = notImplemented()

    override suspend fun getFood(
        fdcId: Long,
        qtyG: Double,
    ): app.mealsy.data.api.ItemDto = notImplemented()

    override suspend fun deleteAccount(): Unit = notImplemented()

    override suspend fun coachingFeedback(
        id: String,
        body: CoachingFeedbackRequest,
    ): Unit = notImplemented()

    private fun <T> notImplemented(): T = throw UnsupportedOperationException("not used by TodayRepositoryTest")
}

/**
 * #49 item 4: verifies [TodayRepository.get]'s in-flight coalescing — the
 * fix for the measured duplicate `/goals + /meals/today` pair right after
 * Home's mount (its own `init { load() }` racing the `DisposableEffect`'s
 * synthetic `ON_RESUME`).
 */
@OptIn(ExperimentalCoroutinesApi::class)
class TodayRepositoryTest {
    // Shared with `runTest` below so `repo`'s ApplicationScope-style dispatcher
    // and the test body advance on the same virtual-time scheduler.
    private val testDispatcher = StandardTestDispatcher()

    @Before
    fun setUp() {
        Dispatchers.setMain(testDispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun concurrentCalls_shareOneNetworkRoundTrip() =
        runTest(testDispatcher) {
            val gate = kotlinx.coroutines.CompletableDeferred<Unit>()
            val api = CountingMealsyApi(todayGate = gate)
            val repo =
                TodayRepository(
                    api = api,
                    goalsRepository = GoalsRepository(api),
                    scope = CoroutineScope(SupervisorJob() + testDispatcher),
                )

            // Both calls start before either `today()` gate opens, mirroring Home's
            // init-load racing its DisposableEffect's synthetic ON_RESUME refresh.
            val first = async { repo.get() }
            val second = async { repo.get() }
            advanceUntilIdle()
            assertEquals(1, api.todayCallCount)
            assertEquals(1, api.goalsCallCount)

            gate.complete(Unit)
            advanceUntilIdle()
            val firstResult = first.await()
            val secondResult = second.await()
            assertSame(firstResult, secondResult)
        }

    @Test
    fun sequentialCalls_eachFetchFresh() =
        runTest(testDispatcher) {
            val api = CountingMealsyApi()
            val repo =
                TodayRepository(
                    api = api,
                    goalsRepository = GoalsRepository(api),
                    scope = CoroutineScope(SupervisorJob() + testDispatcher),
                )

            repo.get()
            repo.get()

            // Unlike the concurrent case, two calls that don't overlap in time
            // (e.g. an initial load, then a pull-to-refresh long after) must each
            // hit the network — this is in-flight coalescing, not a stale cache.
            assertEquals(2, api.todayCallCount)
            assertEquals(2, api.goalsCallCount)
        }

    @Test
    fun get_updatesState() =
        runTest(testDispatcher) {
            val api = CountingMealsyApi()
            val repo =
                TodayRepository(
                    api = api,
                    goalsRepository = GoalsRepository(api),
                    scope = CoroutineScope(SupervisorJob() + testDispatcher),
                )

            assertEquals(null, repo.state.value)
            val result = repo.get()
            assertEquals(result, repo.state.value)
            assertTrue(repo.state.value?.today?.kcal == 1000.0)
        }
}
