package app.mealsy.android.ui.mealdetail

import androidx.lifecycle.SavedStateHandle
import app.mealsy.data.api.AppMetaResponse
import app.mealsy.data.api.CategoryStatDto
import app.mealsy.data.api.CoachingFeedbackRequest
import app.mealsy.data.api.DayTrendDto
import app.mealsy.data.api.GoalRequest
import app.mealsy.data.api.GoalsResponse
import app.mealsy.data.api.ItemDto
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
import app.mealsy.data.offline.PendingLogQueue
import app.mealsy.data.repo.ChatRepository
import app.mealsy.data.repo.ConversationIdStore
import app.mealsy.data.repo.GoalsRepository
import app.mealsy.data.repo.MealsRepository
import app.mealsy.data.repo.MyMealsRefreshSignal
import app.mealsy.data.repo.MyMealsRepository
import app.mealsy.data.repo.TodayRefreshSignal
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.GlobalScope
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset

/** A [MealsyApi] fake implementing only what [MealDetailViewModel] and its repositories use. */
private class FakeMealsyApi(
    var mealLogDetail: MealLogDetailDto? = null,
    var myMealDetail: MyMealDetailDto? = null,
    var goalsResponse: GoalsResponse? = null,
    var todayResponse: TodayResponse =
        TodayResponse(
            kcal = 0.0,
            proteinG = 0.0,
            carbsG = 0.0,
            fatG = 0.0,
            fiberG = 0.0,
            nMeals = 0,
        ),
    var logItemsResponse: LogItemsResponse =
        LogItemsResponse(
            mealId = "new_meal", mealType = "lunch", nItems = 1,
            kcal = 100.0, proteinG = 10.0, carbsG = 10.0, fatG = 5.0, fiberG = 2.0,
            message = "Logged",
        ),
) : MealsyApi {
    val logItemsCalls = mutableListOf<LogItemsRequest>()
    val deleteMealLogCalls = mutableListOf<String>()

    override suspend fun logTurn(body: LogTurnRequest): LogTurnResponse = notImplemented()

    override suspend fun pending(id: String): LogTurnResponse = notImplemented()

    override suspend fun logItems(body: LogItemsRequest): LogItemsResponse {
        logItemsCalls += body
        return logItemsResponse
    }

    override suspend fun today(): TodayResponse = todayResponse

    override suspend fun goals(): GoalsResponse =
        goalsResponse ?: throw retrofit2.HttpException(
            retrofit2.Response.error<Any>(404, "".toResponseBody(null)),
        )

    override suspend fun createGoals(body: GoalRequest): GoalsResponse = notImplemented()

    override suspend fun updateGoals(body: GoalRequest): GoalsResponse = notImplemented()

    override suspend fun quota(): QuotaResponse = notImplemented()

    override suspend fun registerDevice(body: RegisterDeviceRequest): Unit = notImplemented()

    override suspend fun deleteDevice(token: String): Unit = notImplemented()

    override suspend fun appMeta(): AppMetaResponse = notImplemented()

    override suspend fun trends(days: Int): List<DayTrendDto> = notImplemented()

    override suspend fun categories(days: Int): List<CategoryStatDto> = notImplemented()

    override suspend fun myMeals(): List<SavedMealDto> = notImplemented()

    override suspend fun myMeal(id: String): MyMealDetailDto = myMealDetail ?: notImplemented()

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

    override suspend fun mealLog(id: String): MealLogDetailDto = mealLogDetail ?: notImplemented()

    override suspend fun deleteMealLog(id: String) {
        deleteMealLogCalls += id
    }

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

    private fun <T> notImplemented(): T = throw UnsupportedOperationException("not used by this test")
}

private class FakeConversationIdStore : ConversationIdStore {
    private var value: String? = null

    override suspend fun get(): String? = value ?: "conv_1".also { value = it }

    override suspend fun set(id: String) {
        value = id
    }
}

private class FakePendingLogQueue : PendingLogQueue {
    override suspend fun enqueue(
        clientRequestId: String,
        payloadJson: String,
    ) = Unit
}

private fun usdaItem(
    foodName: String = "Chicken, broiler or fryers, breast, cooked, grilled",
    proteinG: Double = 30.0,
    estimated: Boolean = false,
    source: String? = "USDA",
) = ItemDto(
    foodName = foodName,
    qtyG = 120.0,
    targetQtyG = 120.0,
    kcal = 200.0,
    proteinG = proteinG,
    carbsG = 0.0,
    fatG = 5.0,
    fiberG = 0.0,
    fdcId = 111L,
    estimated = estimated,
    extras = source?.let { JsonObject(mapOf("source" to JsonPrimitive(it))) } ?: JsonObject(emptyMap()),
)

private fun mealLogDetail(items: List<ItemDto>) =
    MealLogDetailDto(
        mealId = "meal_1",
        mealType = "lunch",
        loggedAt = "2026-09-16T12:40:00Z",
        label = "Chicken salad",
        kcal = 412.0,
        proteinG = 28.0,
        carbsG = 18.0,
        fatG = 20.0,
        fiberG = 4.0,
        nItems = items.size,
        items = items,
    )

private fun myMealDetail(items: List<ItemDto>) =
    MyMealDetailDto(
        id = "saved_1",
        name = "Usual breakfast",
        kcal = 450.0,
        proteinG = 28.0,
        carbsG = 40.0,
        fatG = 18.0,
        fiberG = 6.0,
        nIngredients = items.size,
        loggedToday = false,
        ingredients = items,
    )

private fun goalsResponse(
    kcalGoal: Double? = 1900.0,
    trackingMode: String = "goals",
) = GoalsResponse(
    trackingMode = trackingMode,
    kcalGoal = kcalGoal,
    proteinGoal = 140.0,
    fiberGoal = 30.0,
)

private fun clockAtHour(
    hour: Int,
    minute: Int = 0,
): Clock = Clock.fixed(Instant.parse("2026-09-16T00:00:00Z").plusSeconds((hour * 3600 + minute * 60).toLong()), ZoneOffset.UTC)

@OptIn(ExperimentalCoroutinesApi::class)
class MealDetailViewModelTest {
    @Before
    fun setUp() {
        Dispatchers.setMain(Dispatchers.Unconfined)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun buildViewModel(
        api: FakeMealsyApi,
        navArgs: Map<String, String>,
        clock: Clock = clockAtHour(13),
    ): MealDetailViewModel {
        val todayRefreshSignal = TodayRefreshSignal()
        return MealDetailViewModel(
            savedStateHandle = SavedStateHandle(navArgs),
            mealsRepository = MealsRepository(api, todayRefreshSignal),
            myMealsRepository = MyMealsRepository(api, todayRefreshSignal, MyMealsRefreshSignal()),
            chatRepository = ChatRepository(api, FakeConversationIdStore(), FakePendingLogQueue(), Json, todayRefreshSignal),
            goalsRepository = GoalsRepository(api),
            api = api,
            clock = clock,
        )
    }

    @Test
    fun `loads a logged meal`() =
        runBlockingTest {
            val api =
                FakeMealsyApi(
                    mealLogDetail = mealLogDetail(listOf(usdaItem())),
                    goalsResponse = goalsResponse(),
                    todayResponse = TodayResponse(kcal = 1200.0, proteinG = 80.0, carbsG = 0.0, fatG = 0.0, fiberG = 0.0, nMeals = 1),
                )
            val vm = buildViewModel(api, mapOf("mealId" to "meal_1"))
            vm.readyJob.join()

            val state = vm.uiState.value
            assertTrue(state is MealDetailUiState.Loaded)
            state as MealDetailUiState.Loaded
            assertEquals(MealDetailMode.Logged("meal_1"), state.mode)
            assertEquals("lunch", state.mealType)
            assertEquals(1, state.items.size)
        }

    @Test
    fun `loads a saved My Meal`() =
        runBlockingTest {
            val api =
                FakeMealsyApi(
                    myMealDetail = myMealDetail(listOf(usdaItem())),
                    goalsResponse = goalsResponse(),
                )
            val vm = buildViewModel(api, mapOf("id" to "saved_1"))
            vm.readyJob.join()

            val state = vm.uiState.value
            assertTrue(state is MealDetailUiState.Loaded)
            state as MealDetailUiState.Loaded
            assertEquals(MealDetailMode.MyMeal("saved_1"), state.mode)
            assertEquals(null, state.mealType)
            assertEquals("Usual breakfast", state.title)
        }

    @Test
    fun `all items USDA and not estimated shows the verified tag`() =
        runBlockingTest {
            val api =
                FakeMealsyApi(
                    mealLogDetail = mealLogDetail(listOf(usdaItem(estimated = false, source = "USDA"))),
                    goalsResponse = goalsResponse(),
                )
            val vm = buildViewModel(api, mapOf("mealId" to "meal_1"))
            vm.readyJob.join()

            val state = vm.uiState.value as MealDetailUiState.Loaded
            assertEquals(MealDetailThirdTag.UsdaVerified, state.thirdTag)
        }

    @Test
    fun `any estimated item shows the estimated tag`() =
        runBlockingTest {
            val api =
                FakeMealsyApi(
                    mealLogDetail =
                        mealLogDetail(
                            listOf(usdaItem(estimated = false, source = "USDA"), usdaItem(estimated = true, source = "USDA")),
                        ),
                    goalsResponse = goalsResponse(),
                )
            val vm = buildViewModel(api, mapOf("mealId" to "meal_1"))
            vm.readyJob.join()

            val state = vm.uiState.value as MealDetailUiState.Loaded
            assertEquals(MealDetailThirdTag.Estimated, state.thirdTag)
        }

    @Test
    fun `neither all-USDA nor estimated shows no third tag`() =
        runBlockingTest {
            val api =
                FakeMealsyApi(
                    mealLogDetail = mealLogDetail(listOf(usdaItem(estimated = false, source = "estimate"))),
                    goalsResponse = goalsResponse(),
                )
            val vm = buildViewModel(api, mapOf("mealId" to "meal_1"))
            vm.readyJob.join()

            val state = vm.uiState.value as MealDetailUiState.Loaded
            assertEquals(MealDetailThirdTag.None, state.thirdTag)
        }

    @Test
    fun `status is FitsBudget when under the daily goal`() =
        runBlockingTest {
            val api =
                FakeMealsyApi(
                    mealLogDetail = mealLogDetail(listOf(usdaItem())),
                    goalsResponse = goalsResponse(kcalGoal = 1900.0),
                    todayResponse = TodayResponse(kcal = 1400.0, proteinG = 0.0, carbsG = 0.0, fatG = 0.0, fiberG = 0.0, nMeals = 1),
                )
            val vm = buildViewModel(api, mapOf("mealId" to "meal_1"))
            vm.readyJob.join()

            val state = vm.uiState.value as MealDetailUiState.Loaded
            assertTrue(state.status is MealDetailStatus.FitsBudget)
            assertEquals("500", (state.status as MealDetailStatus.FitsBudget).kcalRemaining)
        }

    @Test
    fun `status is OverBudget when over the daily goal`() =
        runBlockingTest {
            val api =
                FakeMealsyApi(
                    mealLogDetail = mealLogDetail(listOf(usdaItem())),
                    goalsResponse = goalsResponse(kcalGoal = 1900.0),
                    todayResponse = TodayResponse(kcal = 2100.0, proteinG = 0.0, carbsG = 0.0, fatG = 0.0, fiberG = 0.0, nMeals = 1),
                )
            val vm = buildViewModel(api, mapOf("mealId" to "meal_1"))
            vm.readyJob.join()

            val state = vm.uiState.value as MealDetailUiState.Loaded
            assertTrue(state.status is MealDetailStatus.OverBudget)
            assertEquals("200", (state.status as MealDetailStatus.OverBudget).kcalOver)
        }

    @Test
    fun `status kcal values use a locale thousands separator above 999`() =
        runBlockingTest {
            val api =
                FakeMealsyApi(
                    mealLogDetail = mealLogDetail(listOf(usdaItem())),
                    goalsResponse = goalsResponse(kcalGoal = 4000.0),
                    todayResponse = TodayResponse(kcal = 1989.0, proteinG = 0.0, carbsG = 0.0, fatG = 0.0, fiberG = 0.0, nMeals = 1),
                )
            val vm = buildViewModel(api, mapOf("mealId" to "meal_1"), clock = clockAtHour(13))
            vm.readyJob.join()

            val state = vm.uiState.value as MealDetailUiState.Loaded
            assertEquals("2,011", (state.status as MealDetailStatus.FitsBudget).kcalRemaining)
        }

    @Test
    fun `coach note skips the protein-source line for a single-item meal`() =
        runBlockingTest {
            val api =
                FakeMealsyApi(
                    mealLogDetail = mealLogDetail(listOf(usdaItem(estimated = false))),
                    goalsResponse = goalsResponse(),
                )
            val vm = buildViewModel(api, mapOf("mealId" to "meal_1"), clock = clockAtHour(13))
            vm.readyJob.join()

            val state = vm.uiState.value as MealDetailUiState.Loaded
            assertEquals(MealDetailCoachNote.None, state.coachNote)
        }

    @Test
    fun `coach note names the protein source for a multi-item meal`() =
        runBlockingTest {
            val api =
                FakeMealsyApi(
                    mealLogDetail =
                        mealLogDetail(
                            listOf(usdaItem(foodName = "Rice", proteinG = 4.0), usdaItem(foodName = "Chicken", proteinG = 30.0)),
                        ),
                    goalsResponse = goalsResponse(),
                )
            val vm = buildViewModel(api, mapOf("mealId" to "meal_1"), clock = clockAtHour(13))
            vm.readyJob.join()

            val state = vm.uiState.value as MealDetailUiState.Loaded
            assertTrue(state.coachNote is MealDetailCoachNote.ProteinSource)
            assertEquals("Chicken", (state.coachNote as MealDetailCoachNote.ProteinSource).itemName)
        }

    @Test
    fun `status is Logged in mindful mode with no kcal goal`() =
        runBlockingTest {
            val api =
                FakeMealsyApi(
                    mealLogDetail = mealLogDetail(listOf(usdaItem())),
                    goalsResponse = goalsResponse(kcalGoal = null, trackingMode = "mindful"),
                    todayResponse = TodayResponse(kcal = 800.0, proteinG = 0.0, carbsG = 0.0, fatG = 0.0, fiberG = 0.0, nMeals = 1),
                )
            val vm = buildViewModel(api, mapOf("mealId" to "meal_1"))
            vm.readyJob.join()

            val state = vm.uiState.value as MealDetailUiState.Loaded
            assertEquals(MealDetailStatus.Logged, state.status)
        }

    @Test
    fun `log-again in logged mode builds a ConfirmationCard and calls confirmCard once`() =
        runBlockingTest {
            val api =
                FakeMealsyApi(
                    mealLogDetail = mealLogDetail(listOf(usdaItem())),
                    goalsResponse = goalsResponse(),
                )
            val vm = buildViewModel(api, mapOf("mealId" to "meal_1"), clock = clockAtHour(13))
            vm.readyJob.join()

            vm.openSheet()
            vm.selectSheetMealType("dinner")
            vm.selectSheetPortion(2.0)
            vm.confirmSheet()

            assertEquals(1, api.logItemsCalls.size)
            val request = api.logItemsCalls[0]
            assertEquals("dinner", request.mealType)
            assertEquals(2.0, request.portion, 0.0)
            assertEquals(1, request.items.size)
            assertEquals("Chicken, broiler or fryers, breast, cooked, grilled", request.items[0].foodName)
        }

    @Test
    fun `delete in logged mode calls MealsRepository delete and signals a pop`() =
        runBlockingTest {
            val api =
                FakeMealsyApi(
                    mealLogDetail = mealLogDetail(listOf(usdaItem())),
                    goalsResponse = goalsResponse(),
                )
            val vm = buildViewModel(api, mapOf("mealId" to "meal_1"))
            vm.readyJob.join()

            var deleted = false
            val job =
                GlobalScope.launch(Dispatchers.Unconfined) {
                    vm.events.collect { event -> if (event is MealDetailEvent.Deleted) deleted = true }
                }

            vm.delete()

            assertEquals(listOf("meal_1"), api.deleteMealLogCalls)
            assertTrue(deleted)
            job.cancel()
        }
}

/** Small alias so tests read like the rest of the suite without a TestDispatcher (see [MyMealsViewModelTest]). */
private fun runBlockingTest(block: suspend kotlinx.coroutines.CoroutineScope.() -> Unit) = kotlinx.coroutines.runBlocking(block = block)
