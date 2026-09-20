package app.mealsy.android.ui.meals

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModelStore
import app.mealsy.data.api.AuthInterceptor
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.TokenProvider
import app.mealsy.data.repo.MealsRepository
import app.mealsy.data.repo.TodayRefreshSignal
import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
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
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import retrofit2.Retrofit

/**
 * Drives [MealTypeListViewModel] against a real [MockWebServer], mirroring
 * [app.mealsy.android.ui.mymeals.MyMealsViewModelTest]'s convention.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class MealTypeListViewModelTest {
    private lateinit var server: MockWebServer
    private lateinit var appScope: CoroutineScope
    private val json =
        Json {
            ignoreUnknownKeys = true
            explicitNulls = false
        }

    @Before
    fun setUp() {
        Dispatchers.setMain(Dispatchers.Unconfined)
        server = MockWebServer()
        server.start()
        appScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
        mealTypeUndoWindowMs = 50L
    }

    @After
    fun tearDown() {
        server.shutdown()
        Dispatchers.resetMain()
        appScope.cancel()
        mealTypeUndoWindowMs = 4_000L
    }

    private fun buildApi(): MealsyApi {
        val client =
            OkHttpClient.Builder()
                .addInterceptor(AuthInterceptor(TokenProvider { "token" }))
                .build()
        val contentType = "application/json".toMediaType()
        val retrofit =
            Retrofit.Builder()
                .baseUrl(server.url("/"))
                .client(client)
                .addConverterFactory(json.asConverterFactory(contentType))
                .build()
        return retrofit.create(MealsyApi::class.java)
    }

    private fun buildViewModel(
        mealType: String = "lunch",
        todayRefreshSignal: TodayRefreshSignal = TodayRefreshSignal(),
    ): MealTypeListViewModel =
        MealTypeListViewModel(
            savedStateHandle = SavedStateHandle(mapOf("mealType" to mealType)),
            repository = MealsRepository(buildApi(), todayRefreshSignal),
            todayRefreshSignal = todayRefreshSignal,
            appScope = appScope,
        )

    private val listGoldenJson =
        """
        [
          {
            "meal_id": "m_1",
            "meal_type": "lunch",
            "logged_at": "2026-09-16T12:40:00Z",
            "label": "Chicken salad",
            "kcal": 412.0,
            "protein_g": 28.0,
            "carbs_g": 18.0,
            "fat_g": 20.0,
            "fiber_g": 4.0,
            "n_items": 2
          }
        ]
        """.trimIndent()

    @Test
    fun `load populates the list on success`() =
        runBlocking {
            server.enqueue(MockResponse().setResponseCode(200).setBody(listGoldenJson))
            val viewModel = buildViewModel()
            viewModel.readyJob.join()

            val state = viewModel.uiState.value
            assertTrue(state is MealTypeListUiState.Loaded)
            assertEquals(1, (state as MealTypeListUiState.Loaded).meals.size)
            assertEquals("m_1", state.meals[0].mealId)
        }

    @Test
    fun `load maps an empty array to Empty`() =
        runBlocking {
            server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))
            val viewModel = buildViewModel()
            viewModel.readyJob.join()

            assertEquals(MealTypeListUiState.Empty, viewModel.uiState.value)
        }

    @Test
    fun `a server error maps to Error state`() =
        runBlocking {
            server.enqueue(MockResponse().setResponseCode(500))
            val viewModel = buildViewModel()
            viewModel.readyJob.join()

            assertTrue(viewModel.uiState.value is MealTypeListUiState.Error)
        }

    @Test
    fun `retry after an error reloads and can land Loaded`() =
        runBlocking {
            server.enqueue(MockResponse().setResponseCode(500))
            val viewModel = buildViewModel()
            viewModel.readyJob.join()
            assertTrue(viewModel.uiState.value is MealTypeListUiState.Error)

            server.enqueue(MockResponse().setResponseCode(200).setBody(listGoldenJson))
            viewModel.load().join()

            assertTrue(viewModel.uiState.value is MealTypeListUiState.Loaded)
        }

    @Test
    fun `refresh on TodayRefreshSignal reloads the list`() =
        runBlocking {
            val signal = TodayRefreshSignal()
            server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))
            val viewModel = buildViewModel(todayRefreshSignal = signal)
            viewModel.readyJob.join()
            assertEquals(MealTypeListUiState.Empty, viewModel.uiState.value)

            server.enqueue(MockResponse().setResponseCode(200).setBody(listGoldenJson))
            signal.notifyLogged()
            // Give the Unconfined-dispatched collector a moment to process the signal.
            delay(50)

            assertTrue(viewModel.uiState.value is MealTypeListUiState.Loaded)
        }

    @Test
    fun `deleteWithUndo hides the meal immediately but does not DELETE until the window elapses`() =
        runBlocking {
            server.enqueue(MockResponse().setResponseCode(200).setBody(listGoldenJson))
            val viewModel = buildViewModel()
            viewModel.readyJob.join()
            server.takeRequest() // the initial GET

            viewModel.deleteWithUndo("m_1")

            assertTrue("m_1" in viewModel.hiddenIds.value)
            assertEquals(1, server.requestCount)

            server.enqueue(MockResponse().setResponseCode(204))
            delay(mealTypeUndoWindowMs + 200)

            val deleteRequest = server.takeRequest()
            assertEquals("DELETE", deleteRequest.method)
            assertEquals("/meals/log/m_1", deleteRequest.path)
        }

    @Test
    fun `undoDelete cancels the pending delete so no DELETE ever lands`() =
        runBlocking {
            server.enqueue(MockResponse().setResponseCode(200).setBody(listGoldenJson))
            val viewModel = buildViewModel()
            viewModel.readyJob.join()

            viewModel.deleteWithUndo("m_1")
            assertTrue("m_1" in viewModel.hiddenIds.value)

            viewModel.undoDelete("m_1")
            assertFalse("m_1" in viewModel.hiddenIds.value)

            delay(mealTypeUndoWindowMs + 200)
            assertEquals(1, server.requestCount) // only the initial GET
        }

    @Test
    fun `onCleared flushes a pending delete immediately`() =
        runBlocking {
            server.enqueue(MockResponse().setResponseCode(200).setBody(listGoldenJson))
            val viewModel = buildViewModel()
            viewModel.readyJob.join()
            server.takeRequest() // the initial GET

            viewModel.deleteWithUndo("m_1")
            server.enqueue(MockResponse().setResponseCode(204))

            val store = ViewModelStore()
            store.put("meal-type-list", viewModel)
            store.clear()

            delay(200)

            val deleteRequest = server.takeRequest()
            assertEquals("DELETE", deleteRequest.method)
            assertEquals("/meals/log/m_1", deleteRequest.path)
        }
}
