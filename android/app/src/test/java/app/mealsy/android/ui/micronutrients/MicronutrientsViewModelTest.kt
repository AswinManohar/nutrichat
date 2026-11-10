package app.mealsy.android.ui.micronutrients

import app.mealsy.android.ui.common.ErrorKind
import app.mealsy.data.api.DailyNutrientsDto
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.MicronutrientTabDto
import app.mealsy.data.api.NutrientAmountDto
import app.mealsy.data.api.NutrientCatalogDto
import app.mealsy.data.api.NutrientDayDto
import app.mealsy.data.api.NutrientDefDto
import app.mealsy.data.repo.NutrientsRepository
import app.mealsy.domain.MicroRange
import kotlinx.coroutines.CompletableDeferred
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

private val CATALOG =
    NutrientCatalogDto(
        version = 1,
        nutrients =
            listOf(
                NutrientDefDto("iron", "Iron", "mg", "target", 18.0),
                NutrientDefDto("sodium", "Sodium", "mg", "limit", 2300.0),
            ),
        micronutrientTabs =
            listOf(
                MicronutrientTabDto("electrolytes", "Electrolytes", listOf("sodium")),
                MicronutrientTabDto("minerals", "Minerals", listOf("iron")),
            ),
    )

private fun daily(vararg logged: Pair<String, Double>) =
    DailyNutrientsDto(
        days =
            listOf(
                NutrientDayDto(
                    date = "2026-11-10",
                    logged = logged.isNotEmpty(),
                    values = logged.associate { (k, v) -> k to NutrientAmountDto(v) },
                ),
            ),
    )

/** A [MealsyApi] that answers only the two nutrient calls; anything else fails the test. */
private class FakeNutrientsApi(
    var respond: suspend (days: Int) -> DailyNutrientsDto,
) : MealsyApi by unsupported() {
    val requestedDays = mutableListOf<Int>()

    override suspend fun nutrientCatalog(): NutrientCatalogDto = CATALOG

    override suspend fun dailyNutrients(
        days: Int,
        keys: String?,
        meals: Boolean,
    ): DailyNutrientsDto {
        requestedDays += days
        return respond(days)
    }
}

private fun unsupported(): MealsyApi =
    Proxy.newProxyInstance(MealsyApi::class.java.classLoader, arrayOf(MealsyApi::class.java)) { _, method, _ ->
        error("unexpected MealsyApi.${method.name}")
    } as MealsyApi

@OptIn(ExperimentalCoroutinesApi::class)
class MicronutrientsViewModelTest {
    @Before
    fun setUp() {
        Dispatchers.setMain(Dispatchers.Unconfined)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun viewModel(api: FakeNutrientsApi) = MicronutrientsViewModel(NutrientsRepository(api))

    @Test
    fun firstLoad_isTodayAndLoaded() =
        runBlocking {
            val api = FakeNutrientsApi { daily("iron" to 9.0, "sodium" to 1150.0) }
            val vm = viewModel(api)
            vm.readyJob.join()

            val content = vm.uiState.value.content as MicronutrientsContent.Loaded
            assertEquals(listOf(1), api.requestedDays)
            assertEquals(50, content.summary.tabs[1].rows[0].pct)
            assertEquals(MicroRange.Today, vm.uiState.value.range)
        }

    @Test
    fun nothingLogged_isEmpty() =
        runBlocking {
            val vm = viewModel(FakeNutrientsApi { daily() })
            vm.readyJob.join()
            assertEquals(MicronutrientsContent.Empty, vm.uiState.value.content)
        }

    @Test
    fun offlineThenRetry_recovers() =
        runBlocking {
            val api = FakeNutrientsApi { throw IOException("no network") }
            val vm = viewModel(api)
            vm.readyJob.join()
            assertEquals(MicronutrientsContent.Error(ErrorKind.Offline), vm.uiState.value.content)

            api.respond = { daily("iron" to 9.0) }
            vm.retry().join()
            assertTrue(vm.uiState.value.content is MicronutrientsContent.Loaded)
        }

    @Test
    fun serverError_isLoadFailed() =
        runBlocking {
            val vm = viewModel(FakeNutrientsApi { throw IllegalStateException("500") })
            vm.readyJob.join()
            assertEquals(MicronutrientsContent.Error(ErrorKind.LoadFailed), vm.uiState.value.content)
        }

    @Test
    fun rangeSwitch_keepsTheOldChartDimmedUntilTheNewOneArrives() =
        runBlocking {
            val api = FakeNutrientsApi { daily("iron" to 9.0) }
            val vm = viewModel(api)
            vm.readyJob.join()
            vm.toggleNutrient("iron")

            val gate = CompletableDeferred<DailyNutrientsDto>()
            api.respond = { gate.await() }
            val job = vm.setRange(MicroRange.Week)!!

            val stale = vm.uiState.value
            assertTrue((stale.content as MicronutrientsContent.Loaded).refreshing)
            assertNull(stale.selectedKey)

            gate.complete(daily("iron" to 18.0))
            job.join()
            val fresh = vm.uiState.value.content as MicronutrientsContent.Loaded
            assertEquals(false, fresh.refreshing)
            assertEquals(100, fresh.summary.tabs[1].rows[0].pct)
            assertEquals(listOf(1, 7), api.requestedDays)
            assertNull(vm.setRange(MicroRange.Week))
        }

    @Test
    fun selection_togglesAndClearsOnTabChange() =
        runBlocking {
            val vm = viewModel(FakeNutrientsApi { daily("iron" to 9.0) })
            vm.readyJob.join()

            vm.toggleNutrient("iron")
            assertEquals("iron", vm.uiState.value.selectedKey)
            vm.toggleNutrient("iron")
            assertNull(vm.uiState.value.selectedKey)

            vm.toggleNutrient("iron")
            vm.setTab("electrolytes")
            assertEquals("electrolytes", vm.uiState.value.tabId)
            assertNull(vm.uiState.value.selectedKey)
        }
}
