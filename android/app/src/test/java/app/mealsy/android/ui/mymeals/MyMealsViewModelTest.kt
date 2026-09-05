package app.mealsy.android.ui.mymeals

import app.mealsy.data.api.AuthInterceptor
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.TokenProvider
import app.mealsy.data.repo.MyMealsRepository
import androidx.lifecycle.ViewModelStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
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
import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory

/**
 * Drives [MyMealsViewModel] against a real [MockWebServer], mirroring
 * [app.mealsy.android.ui.chat.ChatViewModelTest]'s convention (a genuine
 * async OkHttp response races a virtual-time `TestDispatcher`, so
 * `Dispatchers.Unconfined` is used instead — see that file's doc comment).
 */
@OptIn(ExperimentalCoroutinesApi::class)
class MyMealsViewModelTest {

    private lateinit var server: MockWebServer
    private lateinit var appScope: CoroutineScope
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false }

    @Before
    fun setUp() {
        Dispatchers.setMain(Dispatchers.Unconfined)
        server = MockWebServer()
        server.start()
        // A real scope (not Dispatchers.Unconfined/Main) — deleteWithUndo's
        // delayed delete must survive independently of the ViewModel's own
        // (test) Main-backed viewModelScope, same as production's injected
        // `@ApplicationScope`.
        appScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
        // Fast enough to actually elapse within a JVM unit test's timeout.
        undoWindowMs = 50L
    }

    @After
    fun tearDown() {
        server.shutdown()
        Dispatchers.resetMain()
        appScope.cancel()
        undoWindowMs = 4_000L
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

    private fun buildViewModel(): MyMealsViewModel =
        MyMealsViewModel(MyMealsRepository(buildApi()), appScope)

    private val listGoldenJson = """
        [
          {
            "id": "meal_1",
            "name": "Usual breakfast",
            "kcal": 450.0,
            "protein_g": 28.0,
            "carbs_g": 40.0,
            "fat_g": 18.0,
            "fiber_g": 6.0,
            "n_ingredients": 3,
            "logged_today": false
          }
        ]
    """.trimIndent()

    private val logResponseJson = """
        {
          "meal_id": "log_1",
          "meal_type": "breakfast",
          "n_items": 3,
          "kcal": 450.0,
          "protein_g": 28.0,
          "carbs_g": 40.0,
          "fat_g": 18.0,
          "fiber_g": 6.0,
          "message": "Logged breakfast"
        }
    """.trimIndent()

    @Test
    fun `load populates the list on success`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody(listGoldenJson))
        val viewModel = buildViewModel()
        viewModel.readyJob.join()

        val state = viewModel.uiState.value
        assertTrue(state is MyMealsUiState.Loaded)
        assertEquals(1, (state as MyMealsUiState.Loaded).meals.size)
        assertEquals("Usual breakfast", state.meals[0].name)
    }

    @Test
    fun `load maps an empty array to Empty`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))
        val viewModel = buildViewModel()
        viewModel.readyJob.join()

        assertEquals(MyMealsUiState.Empty, viewModel.uiState.value)
    }

    @Test
    fun `quickLog calls POST log and reports success`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody(listGoldenJson))
        val viewModel = buildViewModel()
        viewModel.readyJob.join()
        server.enqueue(MockResponse().setResponseCode(200).setBody(logResponseJson))

        val ok = viewModel.quickLog("meal_1", "breakfast").await()

        assertTrue(ok)
        server.takeRequest() // the GET from load()
        val logRequest = server.takeRequest()
        assertEquals("POST", logRequest.method)
        assertEquals("/my-meals/meal_1/log", logRequest.path)
        assertTrue(logRequest.body.readUtf8().contains("\"meal_type\":\"breakfast\""))
    }

    @Test
    fun `quickLog reports failure on a server error without throwing`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody(listGoldenJson))
        val viewModel = buildViewModel()
        viewModel.readyJob.join()
        server.enqueue(MockResponse().setResponseCode(500))

        val ok = viewModel.quickLog("meal_1", "breakfast").await()

        assertFalse(ok)
    }

    @Test
    fun `deleteWithUndo hides the meal immediately but does not call DELETE until the window elapses`() =
        runBlocking {
            server.enqueue(MockResponse().setResponseCode(200).setBody(listGoldenJson))
            val viewModel = buildViewModel()
            viewModel.readyJob.join()

            server.takeRequest() // the initial GET

            viewModel.deleteWithUndo("meal_1")

            assertTrue("meal_1" in viewModel.hiddenIds.value)
            assertEquals(1, server.requestCount) // only the initial GET so far — no DELETE yet

            server.enqueue(MockResponse().setResponseCode(204))
            kotlinx.coroutines.delay(undoWindowMs + 200)

            val deleteRequest = server.takeRequest()
            assertEquals("DELETE", deleteRequest.method)
            assertEquals("/my-meals/meal_1", deleteRequest.path)
        }

    @Test
    fun `onCleared flushes a pending delete immediately instead of losing it`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody(listGoldenJson))
        val viewModel = buildViewModel()
        viewModel.readyJob.join()
        server.takeRequest() // the initial GET

        viewModel.deleteWithUndo("meal_1")
        server.enqueue(MockResponse().setResponseCode(204))

        // Simulate leaving the screen (popping the back-stack entry) well
        // before the undo window elapses — this is exactly the scenario fix
        // round 1 addresses: viewModelScope is cancelled here, so if the
        // delayed delete were still running on it, it would never fire.
        val store = ViewModelStore()
        store.put("my-meals", viewModel)
        store.clear()

        // The delete now runs on appScope, independent of the (cleared)
        // viewModelScope — give it a moment to land without waiting out the
        // full undo window.
        kotlinx.coroutines.delay(200)

        val deleteRequest = server.takeRequest()
        assertEquals("DELETE", deleteRequest.method)
        assertEquals("/my-meals/meal_1", deleteRequest.path)
    }

    @Test
    fun `deleteWithUndo called twice for the same id only fires one DELETE`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody(listGoldenJson))
        val viewModel = buildViewModel()
        viewModel.readyJob.join()
        server.takeRequest() // the initial GET

        viewModel.deleteWithUndo("meal_1")
        kotlinx.coroutines.delay(undoWindowMs / 2)
        viewModel.deleteWithUndo("meal_1") // re-swipe before the first delete fires

        server.enqueue(MockResponse().setResponseCode(204))
        kotlinx.coroutines.delay(undoWindowMs + 200)

        assertEquals(2, server.requestCount) // the initial GET plus exactly one DELETE, not two
        val deleteRequest = server.takeRequest()
        assertEquals("DELETE", deleteRequest.method)
    }

    @Test
    fun `undoDelete cancels the pending delete and un-hides the meal`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody(listGoldenJson))
        val viewModel = buildViewModel()
        viewModel.readyJob.join()

        viewModel.deleteWithUndo("meal_1")
        assertTrue("meal_1" in viewModel.hiddenIds.value)

        viewModel.undoDelete("meal_1")
        assertFalse("meal_1" in viewModel.hiddenIds.value)

        // No DELETE should ever land, even after the window would have elapsed.
        kotlinx.coroutines.delay(undoWindowMs + 200)
        assertEquals(1, server.requestCount) // only the initial GET
    }
}
