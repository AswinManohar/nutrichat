package app.mealsy.android.ui.home

import app.mealsy.android.data.TodayRepository
import app.mealsy.data.api.AppMetaResponse
import app.mealsy.data.api.ByTypeDto
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
import app.mealsy.data.repo.Profile
import app.mealsy.data.repo.ProfileStore
import app.mealsy.data.repo.TodayRefreshSignal
import app.mealsy.domain.ProteinFood
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.IOException
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset

/** A [MealsyApi] fake that only implements what [HomeViewModel] and [GoalsRepository] use. */
private class FakeMealsyApi(
    var todayResponse: TodayResponse,
    var goalsResponse: GoalsResponse?,
    var throwOnToday: Boolean = false,
) : MealsyApi {
    override suspend fun logTurn(body: LogTurnRequest): LogTurnResponse = notImplemented()

    override suspend fun pending(id: String): LogTurnResponse = notImplemented()

    override suspend fun logItems(body: LogItemsRequest): LogItemsResponse = notImplemented()

    override suspend fun today(): TodayResponse {
        if (throwOnToday) throw IOException("offline")
        return todayResponse
    }

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

    override suspend fun myMeal(id: String): MyMealDetailDto = notImplemented()

    override suspend fun saveMeal(body: SaveMealRequest): SavedMealDto = notImplemented()

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

    override suspend fun deleteAccount(): Unit = notImplemented()

    override suspend fun coachingFeedback(
        id: String,
        body: CoachingFeedbackRequest,
    ): Unit = notImplemented()

    private fun <T> notImplemented(): T = throw UnsupportedOperationException("not used by HomeViewModel tests")
}

private class FakeProfileStore(initial: Profile) : ProfileStore {
    private var current = initial
    private val flow = MutableStateFlow(initial)
    override val profile: Flow<Profile> get() = flow

    override suspend fun get(): Profile = flow.first()

    override suspend fun set(
        firstName: String?,
        goalFocus: String?,
    ) {
        current = current.copy(firstName = firstName ?: current.firstName, goalFocus = goalFocus ?: current.goalFocus)
        flow.value = current
    }

    override suspend fun clear() {
        current = Profile()
        flow.value = current
    }
}

private fun today(
    kcal: Double = 1340.0,
    proteinG: Double = 86.0,
    carbsG: Double = 152.0,
    fatG: Double = 48.0,
    nMeals: Int = 4,
    byType: List<ByTypeDto> =
        listOf(
            ByTypeDto(mealType = "breakfast", kcal = 400.0, summary = "", nMeals = 2),
            ByTypeDto(mealType = "lunch", kcal = 500.0, summary = "", nMeals = 1),
            ByTypeDto(mealType = "snack", kcal = 440.0, summary = "", nMeals = 1),
        ),
) = TodayResponse(kcal = kcal, proteinG = proteinG, carbsG = carbsG, fatG = fatG, fiberG = 20.0, nMeals = nMeals, byType = byType)

private fun goalsResponse(
    trackingMode: String = "goals",
    kcalGoal: Double? = 1900.0,
    proteinGoal: Double? = 140.0,
    dietaryPrefs: Map<String, Boolean> = emptyMap(),
) = GoalsResponse(
    trackingMode = trackingMode,
    kcalGoal = kcalGoal,
    proteinGoal = proteinGoal,
    fiberGoal = 30.0,
    dietaryPrefs = JsonObject(dietaryPrefs.mapValues { (_, v) -> JsonPrimitive(v) }),
)

/**
 * A real [TodayRepository] over a [FakeMealsyApi] — [HomeViewModel] no
 * longer talks to [MealsyApi]/[GoalsRepository] directly (#49 item 4's
 * in-flight-coalescing dedupe), so tests build the repository the same way
 * production DI does rather than faking it out.
 */
private fun todayRepository(api: FakeMealsyApi): TodayRepository =
    TodayRepository(
        api = api,
        goalsRepository = GoalsRepository(api),
        scope = CoroutineScope(SupervisorJob() + Dispatchers.Unconfined),
    )

/** Clock fixed at a given local hour on an arbitrary date, in UTC. */
private fun clockAtHour(
    hour: Int,
    minute: Int = 0,
): Clock = Clock.fixed(Instant.parse("2026-09-16T00:00:00Z").plusSeconds((hour * 3600 + minute * 60).toLong()), ZoneOffset.UTC)

@OptIn(ExperimentalCoroutinesApi::class)
class HomeViewModelTest {
    @Before
    fun setUp() {
        Dispatchers.setMain(Dispatchers.Unconfined)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun buildViewModel(
        todayResponse: TodayResponse = today(),
        goals: GoalsResponse? = goalsResponse(),
        profile: Profile = Profile(firstName = "Alex"),
        clock: Clock = clockAtHour(13),
        throwOnToday: Boolean = false,
    ): Pair<HomeViewModel, FakeMealsyApi> {
        val api = FakeMealsyApi(todayResponse, goals, throwOnToday)
        val vm =
            HomeViewModel(
                todayRepository = todayRepository(api),
                profileStore = FakeProfileStore(profile),
                todayRefreshSignal = TodayRefreshSignal(),
                clock = clock,
            )
        return vm to api
    }

    // --- Day part boundaries -------------------------------------------

    @Test
    fun dayPart_morningBefore1159() {
        val (vm, _) = buildViewModel(clock = clockAtHour(11, 59))
        assertEquals(DayPart.Morning, vm.uiState.value.dayPart)
    }

    @Test
    fun dayPart_afternoonAt1200() {
        val (vm, _) = buildViewModel(clock = clockAtHour(12, 0))
        assertEquals(DayPart.Afternoon, vm.uiState.value.dayPart)
    }

    @Test
    fun dayPart_afternoonAt1659() {
        val (vm, _) = buildViewModel(clock = clockAtHour(16, 59))
        assertEquals(DayPart.Afternoon, vm.uiState.value.dayPart)
    }

    @Test
    fun dayPart_eveningAt1700() {
        val (vm, _) = buildViewModel(clock = clockAtHour(17, 0))
        assertEquals(DayPart.Evening, vm.uiState.value.dayPart)
    }

    @Test
    fun dayPart_morningAt0800() {
        val (vm, _) = buildViewModel(clock = clockAtHour(8))
        assertEquals(DayPart.Morning, vm.uiState.value.dayPart)
    }

    @Test
    fun dayPart_eveningAt1900() {
        val (vm, _) = buildViewModel(clock = clockAtHour(19))
        assertEquals(DayPart.Evening, vm.uiState.value.dayPart)
    }

    // --- Greeting / first name -------------------------------------------

    @Test
    fun firstName_nullRendersNoName() {
        val (vm, _) = buildViewModel(profile = Profile(firstName = null))
        assertNull(vm.uiState.value.firstName)
    }

    @Test
    fun firstName_blankRendersNoName() {
        val (vm, _) = buildViewModel(profile = Profile(firstName = "   "))
        assertNull(vm.uiState.value.firstName)
    }

    @Test
    fun firstName_presentIsTrimmed() {
        val (vm, _) = buildViewModel(profile = Profile(firstName = " Alex "))
        assertEquals("Alex", vm.uiState.value.firstName)
    }

    // --- Eaten fraction clamp ---------------------------------------------

    @Test
    fun eatenFraction_zeroWhenNothingLogged() {
        val (vm, _) = buildViewModel(todayResponse = today(kcal = 0.0), goals = goalsResponse(kcalGoal = 2000.0))
        assertEquals(0f, vm.uiState.value.eatenFraction)
    }

    @Test
    fun eatenFraction_midRange() {
        val (vm, _) = buildViewModel(todayResponse = today(kcal = 1000.0), goals = goalsResponse(kcalGoal = 2000.0))
        assertEquals(0.5f, vm.uiState.value.eatenFraction)
    }

    @Test
    fun eatenFraction_clampsAtOneWhenOverGoal() {
        val (vm, _) = buildViewModel(todayResponse = today(kcal = 3000.0), goals = goalsResponse(kcalGoal = 2000.0))
        assertEquals(1f, vm.uiState.value.eatenFraction)
    }

    @Test
    fun eatenFraction_zeroWhenGoalMissing() {
        val (vm, _) = buildViewModel(todayResponse = today(kcal = 1000.0), goals = goalsResponse(kcalGoal = null, trackingMode = "mindful"))
        assertEquals(0f, vm.uiState.value.eatenFraction)
    }

    // --- State label wording ------------------------------------------------

    @Test
    fun kcalState_leftWording() {
        val (vm, _) = buildViewModel(todayResponse = today(kcal = 1340.0), goals = goalsResponse(kcalGoal = 1900.0))
        assertEquals(HomeKcalState.Left("560"), vm.uiState.value.kcalState)
    }

    @Test
    fun kcalState_overWording() {
        val (vm, _) = buildViewModel(todayResponse = today(kcal = 2020.0), goals = goalsResponse(kcalGoal = 1900.0))
        assertEquals(HomeKcalState.Over("120"), vm.uiState.value.kcalState)
    }

    // --- Mindful variant ------------------------------------------------------

    @Test
    fun mindful_whenGoalsNull() {
        val (vm, _) = buildViewModel(goals = null)
        val state = vm.uiState.value
        assertTrue(state.mindful)
        assertEquals(HomeKcalState.NoTarget, state.kcalState)
        assertTrue(state.coachNote is HomeCoachNote.Mindful)
    }

    @Test
    fun mindful_whenTrackingModeMindful() {
        val (vm, _) = buildViewModel(goals = goalsResponse(trackingMode = "mindful", kcalGoal = 2000.0))
        assertTrue(vm.uiState.value.mindful)
    }

    @Test
    fun mindful_whenKcalGoalNull() {
        val (vm, _) = buildViewModel(goals = goalsResponse(kcalGoal = null))
        assertTrue(vm.uiState.value.mindful)
    }

    @Test
    fun mindfulCoachNote_carriesMealCount() {
        val (vm, _) = buildViewModel(goals = null, todayResponse = today(nMeals = 3))
        assertEquals(HomeCoachNote.Mindful(nMeals = 3), vm.uiState.value.coachNote)
    }

    // --- Coach note branches -----------------------------------------------

    @Test
    fun coachNote_proteinGapAfternoon_singleFoodForSmallGap() {
        val (vm, _) =
            buildViewModel(
                todayResponse = today(proteinG = 110.0),
                goals = goalsResponse(proteinGoal = 125.0),
                clock = clockAtHour(13),
            )
        assertEquals(
            HomeCoachNote.ProteinGapSingleFood(gapG = 15, food = ProteinFood.GreekYogurt),
            vm.uiState.value.coachNote,
        )
    }

    @Test
    fun coachNote_proteinGapMorning_singleFoodForSmallGap() {
        val (vm, _) =
            buildViewModel(
                todayResponse = today(proteinG = 110.0),
                goals = goalsResponse(proteinGoal = 125.0),
                clock = clockAtHour(8),
            )
        assertEquals(HomeCoachNote.ProteinGapSingleFood(gapG = 15, food = ProteinFood.Egg), vm.uiState.value.coachNote)
    }

    @Test
    fun coachNote_proteinGapEvening_singleFoodForSmallGap() {
        val (vm, _) =
            buildViewModel(
                todayResponse = today(proteinG = 110.0),
                goals = goalsResponse(proteinGoal = 125.0),
                clock = clockAtHour(19),
            )
        assertEquals(HomeCoachNote.ProteinGapSingleFood(gapG = 15, food = ProteinFood.Milk), vm.uiState.value.coachNote)
    }

    @Test
    fun coachNote_proteinGapSpread_forLargeGap() {
        val (vm, _) =
            buildViewModel(
                todayResponse = today(proteinG = 100.0),
                goals = goalsResponse(proteinGoal = 140.0),
                clock = clockAtHour(13),
            )
        assertEquals(HomeCoachNote.ProteinGapSpread(gapG = 40), vm.uiState.value.coachNote)
    }

    @Test
    fun coachNote_proteinGapRespectsVeganPrefs() {
        val (vm, _) =
            buildViewModel(
                todayResponse = today(proteinG = 110.0),
                goals = goalsResponse(proteinGoal = 125.0, dietaryPrefs = mapOf("vegan" to true)),
                clock = clockAtHour(8),
            )
        assertEquals(HomeCoachNote.ProteinGapSingleFood(gapG = 15, food = ProteinFood.Tofu), vm.uiState.value.coachNote)
    }

    @Test
    fun coachNote_noProteinGapNudgeBeforeFirstMeal() {
        val (vm, _) =
            buildViewModel(
                todayResponse = today(proteinG = 0.0, nMeals = 0),
                goals = goalsResponse(proteinGoal = 140.0, kcalGoal = null),
            )
        assertFalse(vm.uiState.value.coachNote is HomeCoachNote.ProteinGapSingleFood)
        assertFalse(vm.uiState.value.coachNote is HomeCoachNote.ProteinGapSpread)
    }

    @Test
    fun coachNote_proteinGapBoundary_14gIsNotAGap() {
        val (vm, _) = buildViewModel(todayResponse = today(proteinG = 126.0), goals = goalsResponse(proteinGoal = 140.0))
        assertFalse(vm.uiState.value.coachNote is HomeCoachNote.ProteinGapSingleFood)
        assertFalse(vm.uiState.value.coachNote is HomeCoachNote.ProteinGapSpread)
    }

    @Test
    fun coachNote_proteinGapBoundary_15gIsAGap() {
        val (vm, _) = buildViewModel(todayResponse = today(proteinG = 125.0), goals = goalsResponse(proteinGoal = 140.0))
        assertTrue(vm.uiState.value.coachNote is HomeCoachNote.ProteinGapSingleFood)
    }

    @Test
    fun coachNote_kcalRemainingWhenNoProteinGap() {
        val (vm, _) =
            buildViewModel(
                todayResponse = today(kcal = 1340.0, proteinG = 140.0),
                goals = goalsResponse(kcalGoal = 1900.0, proteinGoal = 140.0),
            )
        assertEquals(HomeCoachNote.KcalRemaining(kcal = 560), vm.uiState.value.coachNote)
    }

    @Test
    fun coachNote_targetReachedWhenGoalMetExactly() {
        val (vm, _) =
            buildViewModel(
                todayResponse = today(kcal = 1900.0, proteinG = 140.0),
                goals = goalsResponse(kcalGoal = 1900.0, proteinGoal = 140.0),
            )
        assertEquals(HomeCoachNote.TargetReached, vm.uiState.value.coachNote)
    }

    @Test
    fun coachNote_targetReachedWhenOverGoal() {
        val (vm, _) =
            buildViewModel(
                todayResponse = today(kcal = 2200.0, proteinG = 140.0),
                goals = goalsResponse(kcalGoal = 1900.0, proteinGoal = 140.0),
            )
        assertEquals(HomeCoachNote.TargetReached, vm.uiState.value.coachNote)
    }

    // --- Meal rows ------------------------------------------------------------

    @Test
    fun mealRows_missingOrZeroCountRendersNull() {
        val (vm, _) =
            buildViewModel(
                todayResponse =
                    today(
                        byType =
                            listOf(
                                ByTypeDto(mealType = "breakfast", kcal = 0.0, summary = "", nMeals = 0),
                                ByTypeDto(mealType = "lunch", kcal = 500.0, summary = "", nMeals = 1),
                            ),
                    ),
            )
        val meals = vm.uiState.value.meals.associateBy { it.mealType }
        assertNull(meals.getValue("breakfast").count)
        assertEquals(1, meals.getValue("lunch").count)
        assertNull(meals.getValue("dinner").count)
        assertNull(meals.getValue("snack").count)
    }

    @Test
    fun mealRows_alwaysFourInOrder() {
        val (vm, _) = buildViewModel()
        assertEquals(
            listOf("breakfast", "lunch", "dinner", "snack"),
            vm.uiState.value.meals.map { it.mealType },
        )
    }

    // --- Refresh signal ---------------------------------------------------

    @Test
    fun refreshSignal_reloadsWithoutFlippingLoading() =
        kotlinx.coroutines.test.runTest {
            val api = FakeMealsyApi(today(kcal = 1000.0), goalsResponse())
            val signal = TodayRefreshSignal()
            val vm =
                HomeViewModel(
                    todayRepository = todayRepository(api),
                    profileStore = FakeProfileStore(Profile(firstName = "Alex")),
                    todayRefreshSignal = signal,
                    clock = clockAtHour(13),
                )
            assertFalse(vm.uiState.value.loading)
            api.todayResponse = today(kcal = 1500.0)
            signal.notifyLogged()
            assertFalse(vm.uiState.value.loading)
            assertEquals("1,500", vm.uiState.value.eatenKcal)
        }

    // --- Error / retry ------------------------------------------------------

    @Test
    fun error_whenTodayThrows() {
        val (vm, _) = buildViewModel(throwOnToday = true)
        assertTrue(vm.uiState.value.error)
        assertFalse(vm.uiState.value.loading)
    }

    @Test
    fun retry_clearsErrorOnSuccess() {
        val api = FakeMealsyApi(today(), goalsResponse(), throwOnToday = true)
        val vm =
            HomeViewModel(
                todayRepository = todayRepository(api),
                profileStore = FakeProfileStore(Profile(firstName = "Alex")),
                todayRefreshSignal = TodayRefreshSignal(),
                clock = clockAtHour(13),
            )
        assertTrue(vm.uiState.value.error)
        api.throwOnToday = false
        vm.retry()
        assertFalse(vm.uiState.value.error)
        assertFalse(vm.uiState.value.loading)
    }
}
