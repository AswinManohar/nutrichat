package app.mealsy.android.ui.chat

import app.mealsy.android.util.ConnectivityObserver
import app.mealsy.data.repo.FoodRepository
import app.mealsy.data.repo.FoodSearchHit
import app.mealsy.data.repo.FoodSearchOutcome
import app.mealsy.domain.CandidateDetail
import app.mealsy.domain.CardItem
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** Records every query [search] was called with, so tests can assert stale-query cancellation. */
private class RecordingFoodRepository : FoodRepository(FakeApiNotUsed()) {
    val calls = mutableListOf<String>()
    val searchQtyGCalls = mutableListOf<Double>()
    val getFoodQtyGCalls = mutableListOf<Double>()
    var result: FoodSearchOutcome = FoodSearchOutcome.Empty
    var getFoodResult: CardItem? = null
    var getFoodShouldThrow = false

    override suspend fun search(
        query: String,
        qtyG: Double,
        limit: Int,
    ): FoodSearchOutcome {
        calls.add(query)
        searchQtyGCalls.add(qtyG)
        return result
    }

    override suspend fun getFood(
        fdcId: Long,
        qtyG: Double,
    ): CardItem {
        getFoodQtyGCalls.add(qtyG)
        if (getFoodShouldThrow) throw java.io.IOException("boom")
        return getFoodResult ?: sampleItem(fdcId)
    }
}

/** [FoodRepository] requires a [app.mealsy.data.api.MealsyApi]; unused by [RecordingFoodRepository]'s overrides. */
private class FakeApiNotUsed : app.mealsy.data.api.MealsyApi by UnsupportedMealsyApi()

private class UnsupportedMealsyApi : app.mealsy.data.api.MealsyApi {
    override suspend fun logTurn(body: app.mealsy.data.api.LogTurnRequest) = error("unused")

    override suspend fun pending(id: String) = error("unused")

    override suspend fun logItems(body: app.mealsy.data.api.LogItemsRequest) = error("unused")

    override suspend fun searchFoods(
        q: String,
        qtyG: Double,
        limit: Int,
    ) = error("unused")

    override suspend fun getFood(
        fdcId: Long,
        qtyG: Double,
    ) = error("unused")

    override suspend fun today() = error("unused")

    override suspend fun goals() = error("unused")

    override suspend fun createGoals(body: app.mealsy.data.api.GoalRequest) = error("unused")

    override suspend fun updateGoals(body: app.mealsy.data.api.GoalRequest) = error("unused")

    override suspend fun quota() = error("unused")

    override suspend fun registerDevice(body: app.mealsy.data.api.RegisterDeviceRequest) = error("unused")

    override suspend fun deleteDevice(token: String) = error("unused")

    override suspend fun appMeta() = error("unused")

    override suspend fun trends(days: Int) = error("unused")

    override suspend fun categories(days: Int) = error("unused")

    override suspend fun myMeals() = error("unused")

    override suspend fun myMeal(id: String) = error("unused")

    override suspend fun saveMeal(body: app.mealsy.data.api.SaveMealRequest) = error("unused")

    override suspend fun logMyMeal(
        id: String,
        body: app.mealsy.data.api.LogMyMealRequest,
    ) = error("unused")

    override suspend fun deleteMyMeal(id: String) = error("unused")

    override suspend fun listMealLogs(
        date: String?,
        mealType: String?,
    ) = error("unused")

    override suspend fun mealLog(id: String) = error("unused")

    override suspend fun deleteMealLog(id: String) = error("unused")

    override suspend fun deleteAccount() = error("unused")

    override suspend fun coachingFeedback(
        id: String,
        body: app.mealsy.data.api.CoachingFeedbackRequest,
    ) = error("unused")
}

private fun sampleItem(fdcId: Long) =
    CardItem(
        foodName = "Bread, white, toasted",
        qtyG = 28.0,
        targetQtyG = 28.0,
        kcal = 82.0,
        proteinG = 2.5,
        carbsG = 15.0,
        fatG = 1.0,
        fiberG = 0.8,
        fdcId = fdcId,
        source = "usda_local",
    )

private class FakeConnectivityObserver(initial: Boolean = true) : ConnectivityObserver {
    val flow = MutableStateFlow(initial)
    override val isOnline = flow
}

@OptIn(ExperimentalCoroutinesApi::class)
class FoodPickerViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @Before
    fun setUp() {
        kotlinx.coroutines.Dispatchers.setMain(dispatcher)
    }

    @After
    fun tearDown() {
        kotlinx.coroutines.Dispatchers.resetMain()
    }

    private fun buildViewModel(
        scope: CoroutineScope,
        repo: RecordingFoodRepository = RecordingFoodRepository(),
        connectivity: FakeConnectivityObserver = FakeConnectivityObserver(),
        initialQuery: String = "toast",
        currentFdcId: Long = 111,
        previewQtyG: Double = 28.0,
        baseQtyG: Double = 28.0,
        candidateDetails: List<CandidateDetail> = emptyList(),
    ): Triple<FoodPickerViewModel, RecordingFoodRepository, FakeConnectivityObserver> {
        val vm =
            FoodPickerViewModel(
                repository = repo,
                connectivityObserver = connectivity,
                scope = scope,
                currentFdcId = currentFdcId,
                initialQuery = initialQuery,
                previewQtyG = previewQtyG,
                baseQtyG = baseQtyG,
                candidateDetails = candidateDetails,
            )
        return Triple(vm, repo, connectivity)
    }

    @Test
    fun `suggestions preview kcal and protein at previewQtyG, not baseQtyG`() =
        runTest(dispatcher) {
            val repo = RecordingFoodRepository()
            val details =
                listOf(
                    CandidateDetail(
                        fdcId = 172687,
                        name = "Bread, white, commercially prepared, toasted",
                        dataType = "sr_legacy",
                        kcalPer100g = 293.0,
                        proteinGPer100g = 9.0,
                    ),
                )
            val (vm, _, _) =
                buildViewModel(
                    backgroundScope,
                    repo,
                    currentFdcId = 111,
                    previewQtyG = 56.0,
                    baseQtyG = 28.0,
                    candidateDetails = details,
                )

            assertEquals(1, vm.suggestions.size)
            val hit = vm.suggestions[0]
            assertEquals(172687L, hit.fdcId)
            assertEquals(293.0 * 0.56, hit.kcal, 0.001)
            assertEquals(9.0 * 0.56, hit.proteinG, 0.001)
        }

    @Test
    fun `empty candidateDetails yields no suggestions`() =
        runTest(dispatcher) {
            val repo = RecordingFoodRepository()
            val (vm, _, _) = buildViewModel(backgroundScope, repo, candidateDetails = emptyList())
            assertTrue(vm.suggestions.isEmpty())
        }

    @Test
    fun `selecting a suggestion records method suggestion`() =
        runTest(dispatcher) {
            val repo = RecordingFoodRepository()
            repo.getFoodResult = sampleItem(172687)
            val (vm, _, _) = buildViewModel(backgroundScope, repo, currentFdcId = 111)
            var event: FoodPickerEvent? = null
            val job = launch { vm.eventsFlow.collect { event = it } }
            vm.select(172687, method = "suggestion")
            advanceTimeBy(10)
            advanceUntilIdle()
            job.cancel()
            check(event is FoodPickerEvent.SwapReady)
            assertEquals("suggestion", (event as FoodPickerEvent.SwapReady).method)
        }

    @Test
    fun `picker pre-fills the user's words, not the matched FDC name (#56)`() {
        val item =
            CardItem(
                foodName = "Bread, egg, toasted",
                qtyG = 28.0,
                targetQtyG = 28.0,
                kcal = 80.0,
                proteinG = 3.0,
                carbsG = 12.0,
                fatG = 2.0,
                fiberG = 1.0,
                fdcId = 1L,
                inputPhrase = "toast",
            )

        assertEquals("toast", pickerInitialQuery(item))
        assertEquals("Bread, egg, toasted", pickerInitialQuery(item.copy(inputPhrase = null)))
    }

    @Test
    fun `initial query equals the item's original phrase and results load on open`() =
        runTest(dispatcher) {
            val repo = RecordingFoodRepository()
            repo.result = FoodSearchOutcome.Results(listOf(hit(1)))
            val (vm, _, _) = buildViewModel(backgroundScope, repo, initialQuery = "toast")
            assertEquals("toast", vm.query.value)
            advanceTimeBy(300)
            advanceUntilIdle()
            assertEquals(listOf("toast"), repo.calls)
            assertTrue(vm.searchState.value is SearchState.Loaded)
        }

    @Test
    fun `typing triggers a search only after 250ms and only for trimmed length 2 or more`() =
        runTest(dispatcher) {
            val repo = RecordingFoodRepository()
            repo.result = FoodSearchOutcome.Empty
            val (vm, _, _) = buildViewModel(backgroundScope, repo, initialQuery = "")
            advanceUntilIdle()
            repo.calls.clear()

            vm.onQueryChange("t")
            advanceTimeBy(260)
            advanceUntilIdle()
            assertTrue("single char must not search", repo.calls.isEmpty())

            vm.onQueryChange("to")
            advanceTimeBy(100)
            assertTrue("must not have fired before 250ms", repo.calls.isEmpty())
            advanceTimeBy(200)
            advanceUntilIdle()
            assertEquals(listOf("to"), repo.calls)
        }

    @Test
    fun `a newer query cancels an older in-flight one`() =
        runTest(dispatcher) {
            val repo = RecordingFoodRepository()
            repo.result = FoodSearchOutcome.Results(listOf(hit(1)))
            val (vm, _, _) = buildViewModel(backgroundScope, repo, initialQuery = "")
            advanceUntilIdle()

            vm.onQueryChange("toast")
            advanceTimeBy(260)
            advanceUntilIdle()
            vm.onQueryChange("toaster")
            advanceTimeBy(260)
            advanceUntilIdle()

            // Only the latest query's result is ever shown.
            assertEquals(listOf("toaster"), listOf(repo.calls.last()))
            assertTrue(vm.searchState.value is SearchState.Loaded)
        }

    @Test
    fun `offline state disables search`() =
        runTest(dispatcher) {
            val repo = RecordingFoodRepository()
            val connectivity = FakeConnectivityObserver(initial = false)
            val (vm, _, _) = buildViewModel(backgroundScope, repo, connectivity = connectivity, initialQuery = "toast")
            advanceTimeBy(300)
            advanceUntilIdle()
            assertTrue(repo.calls.isEmpty())
            assertEquals(SearchState.Idle, vm.searchState.value)
            assertTrue(vm.isOnline.value.not())
        }

    @Test
    fun `a 503 or network error maps to the Can't search right now state`() =
        runTest(dispatcher) {
            val repo = RecordingFoodRepository()
            repo.result = FoodSearchOutcome.Unavailable
            val (vm, _, _) = buildViewModel(backgroundScope, repo, initialQuery = "toast")
            advanceTimeBy(300)
            advanceUntilIdle()
            assertEquals(SearchState.Unavailable, vm.searchState.value)
        }

    @Test
    fun `selecting the current match is a no-op`() =
        runTest(dispatcher) {
            val repo = RecordingFoodRepository()
            val (vm, _, _) = buildViewModel(backgroundScope, repo, currentFdcId = 111)
            vm.select(111, method = "search")
            advanceUntilIdle()
            assertTrue(vm.selecting.value.not())
        }

    @Test
    fun `select resolves getFood and emits SwapReady`() =
        runTest(dispatcher) {
            val repo = RecordingFoodRepository()
            repo.getFoodResult = sampleItem(999)
            val (vm, _, _) = buildViewModel(backgroundScope, repo, currentFdcId = 111)
            var event: FoodPickerEvent? = null
            val job =
                launch { vm.eventsFlow.collect { event = it } }
            vm.select(999, method = "search", query = "white bread toasted")
            advanceTimeBy(10)
            advanceUntilIdle()
            job.cancel()
            check(event is FoodPickerEvent.SwapReady)
            assertEquals(999L, (event as FoodPickerEvent.SwapReady).item.fdcId)
        }

    @Test
    fun `select sends the base qtyG, not the preview qtyG, to getFood (U2)`() =
        runTest(dispatcher) {
            val repo = RecordingFoodRepository()
            repo.getFoodResult = sampleItem(999)
            val (vm, _, _) =
                buildViewModel(backgroundScope, repo, currentFdcId = 111, previewQtyG = 300.0, baseQtyG = 28.0)
            val job = launch { vm.eventsFlow.collect { } }
            vm.select(999, method = "search", query = "white bread toasted")
            advanceTimeBy(10)
            advanceUntilIdle()
            job.cancel()
            assertEquals(listOf(28.0), repo.getFoodQtyGCalls)

            // Search/preview rows use the preview qty, never the base one.
            vm.onQueryChange("bread")
            advanceTimeBy(260)
            advanceUntilIdle()
            assertTrue(repo.searchQtyGCalls.all { it == 300.0 })
        }

    @Test
    fun `a failed getFood emits SwapFailed`() =
        runTest(dispatcher) {
            val repo = RecordingFoodRepository()
            repo.getFoodShouldThrow = true
            val (vm, _, _) = buildViewModel(backgroundScope, repo, currentFdcId = 111)
            var event: FoodPickerEvent? = null
            val job = launch { vm.eventsFlow.collect { event = it } }
            vm.select(999, method = "search")
            advanceTimeBy(10)
            advanceUntilIdle()
            job.cancel()
            assertTrue(event is FoodPickerEvent.SwapFailed)
        }

    private fun hit(fdcId: Long) =
        FoodSearchHit(
            fdcId = fdcId,
            name = "Bread, white, toasted",
            dataType = "sr_legacy",
            kcalPer100g = 293.0,
            proteinGPer100g = 9.0,
            kcal = 82.0,
            proteinG = 2.5,
        )
}
