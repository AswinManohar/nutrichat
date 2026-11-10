package app.mealsy.android.ui.journey

import app.mealsy.android.ui.common.ErrorKind
import app.mealsy.data.api.DailyNutrientsDto
import app.mealsy.data.api.DayTrendDto
import app.mealsy.data.api.GoalsResponse
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.MicronutrientTabDto
import app.mealsy.data.api.NutrientAmountDto
import app.mealsy.data.api.NutrientCatalogDto
import app.mealsy.data.api.NutrientDayDto
import app.mealsy.data.api.NutrientDefDto
import app.mealsy.data.repo.GoalsRepository
import app.mealsy.data.repo.NutrientsRepository
import app.mealsy.data.repo.TrendsRepository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.IOException
import java.lang.reflect.Proxy
import java.time.Clock
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneOffset

private val CLOCK = Clock.fixed(Instant.parse("2026-11-10T12:00:00Z"), ZoneOffset.UTC)

private val CATALOG =
    NutrientCatalogDto(
        version = 1,
        nutrients = listOf(NutrientDefDto("iron", "Iron", "mg", "target", 18.0)),
        micronutrientTabs = listOf(MicronutrientTabDto("minerals", "Minerals", listOf("iron"))),
        micronutrientSummary = listOf("iron"),
    )

private val DAY =
    DayTrendDto(
        date = "2026-11-10",
        kcal = 1800.0,
        proteinG = 90.0,
        carbsG = 200.0,
        fatG = 60.0,
        fiberG = 20.0,
        nMeals = 3,
        junkMeals = 0,
    )

/** Answers trends, goals and the two nutrient calls; anything else fails the test. */
private class FakeJourneyApi : MealsyApi by unsupported() {
    var trends: suspend (Int) -> List<DayTrendDto> = { listOf(DAY) }
    var goals: suspend () -> GoalsResponse = { GoalsResponse(trackingMode = "goals", kcalGoal = 2000.0, proteinGoal = 110.0) }
    var daily: suspend (Int) -> DailyNutrientsDto = {
        DailyNutrientsDto(listOf(NutrientDayDto("2026-11-10", logged = true, values = mapOf("iron" to NutrientAmountDto(9.0)))))
    }
    val trendDays = mutableListOf<Int>()

    override suspend fun trends(days: Int): List<DayTrendDto> {
        trendDays += days
        return trends.invoke(days)
    }

    override suspend fun goals(): GoalsResponse = goals.invoke()

    override suspend fun nutrientCatalog(): NutrientCatalogDto = CATALOG

    override suspend fun dailyNutrients(
        days: Int,
        keys: String?,
        meals: Boolean,
    ): DailyNutrientsDto = daily(days)
}

private fun unsupported(): MealsyApi =
    Proxy.newProxyInstance(MealsyApi::class.java.classLoader, arrayOf(MealsyApi::class.java)) { _, method, _ ->
        error("unexpected MealsyApi.${method.name}")
    } as MealsyApi

@OptIn(ExperimentalCoroutinesApi::class)
class JourneyViewModelTest {
    @Before
    fun setUp() {
        Dispatchers.setMain(Dispatchers.Unconfined)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun viewModel(api: FakeJourneyApi) =
        JourneyViewModel(TrendsRepository(api), GoalsRepository(api), NutrientsRepository(api), CLOCK)

    @Test
    fun firstLoad_isSevenDaysWithGoalsAndMicros() =
        runBlocking {
            val api = FakeJourneyApi()
            val vm = viewModel(api)
            vm.readyJob.join()

            val content = vm.uiState.value.content as JourneyContent.Loaded
            assertEquals(listOf(7), api.trendDays)
            assertEquals(2000.0, content.kcalGoal!!, 0.0)
            assertEquals(LocalDate.of(2026, 11, 10), content.today)
            val micros = content.micros as JourneyMicros.Loaded
            assertEquals(listOf("iron"), micros.summary.highlights.map { it.nutrient.key })
        }

    @Test
    fun microsFailing_onlyMarksThatSectionUnavailable() =
        runBlocking {
            // e.g. production before spec 008 ships: /nutrients/daily 404s.
            val api = FakeJourneyApi().apply { daily = { throw IllegalStateException("404") } }
            val vm = viewModel(api)
            vm.readyJob.join()

            val content = vm.uiState.value.content as JourneyContent.Loaded
            assertEquals(JourneyMicros.Unavailable, content.micros)
            assertEquals(1, content.days.size)
        }

    @Test
    fun goalsFailing_dropsOnlyTheTargets() =
        runBlocking {
            val api = FakeJourneyApi().apply { goals = { throw IllegalStateException("500") } }
            val vm = viewModel(api)
            vm.readyJob.join()

            val content = vm.uiState.value.content as JourneyContent.Loaded
            assertNull(content.kcalGoal)
            assertNull(content.proteinGoal)
        }

    @Test
    fun trendsOffline_isAScreenError_andRetryRecovers() =
        runBlocking {
            val api = FakeJourneyApi().apply { trends = { throw IOException("offline") } }
            val vm = viewModel(api)
            vm.readyJob.join()
            assertEquals(JourneyContent.Error(ErrorKind.Offline), vm.uiState.value.content)

            api.trends = { listOf(DAY) }
            vm.retry().join()
            assertTrue(vm.uiState.value.content is JourneyContent.Loaded)
        }

    @Test
    fun nothingLogged_isEmptyMicros() =
        runBlocking {
            val api =
                FakeJourneyApi().apply {
                    trends = { emptyList() }
                    daily = { DailyNutrientsDto(listOf(NutrientDayDto("2026-11-10", logged = false))) }
                }
            val vm = viewModel(api)
            vm.readyJob.join()
            assertEquals(JourneyMicros.Empty, (vm.uiState.value.content as JourneyContent.Loaded).micros)
        }

    @Test
    fun rangeSwitch_refetchesThatManyDays() =
        runBlocking {
            val api = FakeJourneyApi()
            val vm = viewModel(api)
            vm.readyJob.join()
            vm.setRange(JourneyRange.Quarter)!!.join()
            assertEquals(listOf(7, 90), api.trendDays)
            assertNull(vm.setRange(JourneyRange.Quarter))
        }
}
