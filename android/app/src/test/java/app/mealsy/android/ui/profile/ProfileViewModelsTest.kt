package app.mealsy.android.ui.profile

import app.mealsy.data.api.AuthInterceptor
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.TokenProvider
import app.mealsy.data.repo.ProfileRepository
import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import retrofit2.Retrofit
import java.util.concurrent.CopyOnWriteArrayList

/**
 * Drives the Care profile and preference ViewModels against a [MockWebServer] that answers by
 * route, so the reload that follows every write does not need to be queued by hand.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class ProfileViewModelsTest {
    private lateinit var server: MockWebServer
    private val seen = CopyOnWriteArrayList<String>()
    private val failing = mutableSetOf<String>()

    private val profileBody =
        """
        {"version":"v","pending_count":1,"care_team":[],"missing_values":[],
         "hard":[{"id":"p1","type":"allergy","label":"Sesame allergy","state":"pending","source":"inferred"},
                 {"id":"i1","type":"diagnosis","label":"Type 2 diabetes","state":"confirmed","source":"inferred"}],
         "soft":[{"id":"s1","kind":"dislike","text":"coriander","source":"stated","created_at":"2026-11-02T10:00:00Z"}]}
        """.trimIndent()

    private val historyBody = """[{"id":"o","type":"allergy","label":"Old","retired_at":"2026-11-01T10:00:00Z"}]"""

    @Before
    fun setUp() {
        Dispatchers.setMain(Dispatchers.Unconfined)
        server = MockWebServer()
        server.dispatcher =
            object : Dispatcher() {
                override fun dispatch(request: RecordedRequest): MockResponse {
                    val route = "${request.method} ${request.path}"
                    seen += route
                    return when {
                        route in failing -> MockResponse().setResponseCode(500)
                        route == "GET /profile" -> MockResponse().setBody(profileBody)
                        route == "GET /profile/limits/today" -> MockResponse().setBody("""{"on_track":0,"total":0,"limits":[]}""")
                        route == "GET /profile/history" -> MockResponse().setBody(historyBody)
                        route.startsWith("DELETE") -> MockResponse().setResponseCode(204)
                        else -> MockResponse().setBody("""{"id":"x","type":"allergy","kind":"like","text":"t"}""")
                    }
                }
            }
        server.start()
    }

    @After
    fun tearDown() {
        server.shutdown()
        Dispatchers.resetMain()
    }

    private fun repository(): ProfileRepository {
        val json =
            Json {
                ignoreUnknownKeys = true
                explicitNulls = false
            }
        val client = OkHttpClient.Builder().addInterceptor(AuthInterceptor(TokenProvider { "token" })).build()
        val retrofit =
            Retrofit.Builder()
                .baseUrl(server.url("/"))
                .client(client)
                .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
                .build()
        return ProfileRepository(retrofit.create(MealsyApi::class.java))
    }

    private suspend fun CareProfileViewModel.ready(): CareProfileViewModel = also { readyJob.join() }

    @Test
    fun `confirm posts to confirm and reloads the profile`() =
        kotlinx.coroutines.runBlocking {
            val vm = CareProfileViewModel(repository()).ready()
            seen.clear()

            vm.confirm("p1")?.join()

            assertTrue("POST /profile/entries/p1/confirm" in seen)
            assertTrue("GET /profile" in seen)
            assertFalse(vm.save.value.failed)
        }

    @Test
    fun `deny posts to deny`() =
        kotlinx.coroutines.runBlocking {
            val vm = CareProfileViewModel(repository()).ready()

            vm.deny("p1")?.join()

            assertTrue("POST /profile/entries/p1/deny" in seen)
        }

    @Test
    fun `retiring an inferred entry sends confirm true`() =
        kotlinx.coroutines.runBlocking {
            val vm = CareProfileViewModel(repository()).ready()
            var done = false

            vm.retire("i1", "req-1") { done = true }?.join()

            assertTrue(done)
            assertTrue("POST /profile/entries/i1/retire" in seen)
        }

    @Test
    fun `a failed confirm is shown and does not reload`() =
        kotlinx.coroutines.runBlocking {
            val vm = CareProfileViewModel(repository()).ready()
            failing += "POST /profile/entries/p1/confirm"
            seen.clear()

            vm.confirm("p1")?.join()

            assertTrue(vm.save.value.failed)
            assertFalse("GET /profile" in seen)
        }

    @Test
    fun `history lists retired entries`() =
        kotlinx.coroutines.runBlocking {
            val vm = EntryHistoryViewModel(repository())
            vm.readyJob.join()

            val state = vm.state.value as LoadState.Loaded
            assertEquals("2026-11-01T10:00:00Z", state.data.single().retiredAt)
        }

    @Test
    fun `preferences load soft facts and edit patches then reloads`() =
        kotlinx.coroutines.runBlocking {
            val vm = PreferencesViewModel(repository())
            vm.readyJob.join()
            assertEquals("coriander", (vm.state.value as LoadState.Loaded).data.single().text)
            seen.clear()
            var done = false

            vm.edit("s1", "cilantro", "like") { done = true }?.join()

            assertTrue(done)
            assertTrue("PATCH /profile/soft/s1" in seen)
            assertTrue("GET /profile" in seen)
        }

    @Test
    fun `preferences delete calls delete and a failure is shown`() =
        kotlinx.coroutines.runBlocking {
            val vm = PreferencesViewModel(repository())
            vm.readyJob.join()

            vm.delete("s1") {}?.join()
            assertTrue("DELETE /profile/soft/s1" in seen)

            failing += "DELETE /profile/soft/s1"
            vm.delete("s1") {}?.join()
            assertTrue(vm.save.value.failed)
        }
}
