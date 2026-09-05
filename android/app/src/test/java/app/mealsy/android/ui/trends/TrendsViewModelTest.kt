package app.mealsy.android.ui.trends

import app.mealsy.data.api.AuthInterceptor
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.TokenProvider
import app.mealsy.data.repo.GoalsRepository
import app.mealsy.data.repo.TrendsRepository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import retrofit2.Retrofit
import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory

private const val TRENDS_BODY = """
[
  {"date":"2026-09-01","kcal":1800.0,"protein_g":95.0,"carbs_g":200.0,"fiber_g":20.0,"n_meals":3,"junk_meals":1}
]
"""
private const val CATEGORIES_BODY = """
[
  {"meal_type":"breakfast","n_meals":12,"days_logged":10,"avg_kcal":420.5,"avg_protein_g":22.1,"avg_carbs_g":45.0,"avg_fat_g":15.2,"avg_fiber_g":5.0,"total_kcal":5046.0,"share_kcal_pct":28.4}
]
"""
private const val EMPTY_BODY = "[]"
private const val GOALS_BODY = """
{"tracking_mode":"goals","kcal_goal":2200.0,"protein_goal":140.0,"fiber_goal":30.0,"dietary_prefs":{},"first_meal_time":null,"streak_days":0}
"""

/**
 * Drives [TrendsViewModel] against a real [MockWebServer], mirroring
 * `ChatViewModelTest` — real network I/O plus [Dispatchers.Unconfined]
 * rather than a virtual-time [kotlinx.coroutines.test.TestDispatcher], since
 * mixing those races against MockWebServer's genuine async responses.
 * [TrendsViewModel.readyJob]/`setWindow`/`retry` return their [kotlinx.coroutines.Job]
 * for exactly this reason: tests `join()` it instead of guessing completion.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class TrendsViewModelTest {

    private lateinit var server: MockWebServer
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false }

    @Before
    fun setUp() {
        Dispatchers.setMain(Dispatchers.Unconfined)
        server = MockWebServer()
        server.start()
    }

    @After
    fun tearDown() {
        server.shutdown()
        Dispatchers.resetMain()
    }

    private fun buildApi(): MealsyApi {
        val client = OkHttpClient.Builder()
            .addInterceptor(AuthInterceptor(TokenProvider { "token" }))
            .build()
        val contentType = "application/json".toMediaType()
        val retrofit = Retrofit.Builder()
            .baseUrl(server.url("/"))
            .client(client)
            .addConverterFactory(json.asConverterFactory(contentType))
            .build()
        return retrofit.create(MealsyApi::class.java)
    }

    private fun buildViewModel(api: MealsyApi = buildApi()): TrendsViewModel =
        TrendsViewModel(TrendsRepository(api), GoalsRepository(api))

    private fun enqueueLoadedResponses() {
        server.enqueue(MockResponse().setResponseCode(200).setBody(TRENDS_BODY))
        server.enqueue(MockResponse().setResponseCode(200).setBody(CATEGORIES_BODY))
        server.enqueue(MockResponse().setResponseCode(200).setBody(GOALS_BODY))
    }

    private fun enqueueEmptyResponses() {
        server.enqueue(MockResponse().setResponseCode(200).setBody(EMPTY_BODY))
        server.enqueue(MockResponse().setResponseCode(200).setBody(EMPTY_BODY))
        server.enqueue(MockResponse().setResponseCode(200).setBody(GOALS_BODY))
    }

    @Test
    fun `initial load defaults to the 7-day window and lands Loaded`() = runBlocking {
        enqueueLoadedResponses()
        val viewModel = buildViewModel()

        viewModel.readyJob.join()

        assertEquals(TrendsWindow.WEEK, viewModel.window.value)
        val state = viewModel.uiState.value
        assertTrue(state is TrendsUiState.Loaded)
        state as TrendsUiState.Loaded
        assertEquals(1, state.trends.days.size)
        assertEquals(1, state.categories.size)
        assertEquals(140.0, state.proteinGoal)

        val request = server.takeRequest()
        assertTrue(request.path?.contains("days=7") == true)
    }

    @Test
    fun `empty arrays map to Empty state`() = runBlocking {
        enqueueEmptyResponses()
        val viewModel = buildViewModel()

        viewModel.readyJob.join()

        assertEquals(TrendsUiState.Empty, viewModel.uiState.value)
    }

    @Test
    fun `toggling to 30-day window refetches with the new days param`() = runBlocking {
        enqueueLoadedResponses()
        val viewModel = buildViewModel()
        viewModel.readyJob.join()
        server.takeRequest() // trends(7)
        server.takeRequest() // categories(7)
        server.takeRequest() // goals

        enqueueLoadedResponses()
        viewModel.setWindow(TrendsWindow.MONTH)?.join()

        assertEquals(TrendsWindow.MONTH, viewModel.window.value)
        val request = server.takeRequest()
        assertTrue(request.path?.contains("days=30") == true)
        assertTrue(viewModel.uiState.value is TrendsUiState.Loaded)
    }

    @Test
    fun `re-selecting the current window is a no-op`() = runBlocking {
        enqueueLoadedResponses()
        val viewModel = buildViewModel()
        viewModel.readyJob.join()

        val job = viewModel.setWindow(TrendsWindow.WEEK)

        assertEquals(null, job)
        assertEquals(0, server.requestCount - 3) // no extra requests beyond the initial 3
    }

    @Test
    fun `a network failure maps to Error state`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(500))
        val viewModel = buildViewModel()

        viewModel.readyJob.join()

        assertTrue(viewModel.uiState.value is TrendsUiState.Error)
    }

    @Test
    fun `retry after an error refetches and can land Loaded`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(500))
        val viewModel = buildViewModel()
        viewModel.readyJob.join()
        assertTrue(viewModel.uiState.value is TrendsUiState.Error)

        enqueueLoadedResponses()
        viewModel.retry().join()

        assertTrue(viewModel.uiState.value is TrendsUiState.Loaded)
    }
}
