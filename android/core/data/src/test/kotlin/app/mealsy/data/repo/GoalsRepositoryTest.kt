package app.mealsy.data.repo

import app.mealsy.data.api.AuthInterceptor
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.TokenProvider
import app.mealsy.domain.Goals
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import retrofit2.Retrofit
import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory

/** MockWebServer-backed tests for [GoalsRepository]. */
class GoalsRepositoryTest {

    private lateinit var server: MockWebServer
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false }

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    private fun buildRepository(): GoalsRepository {
        val client = OkHttpClient.Builder()
            .addInterceptor(AuthInterceptor(TokenProvider { "token" }))
            .build()
        val contentType = "application/json".toMediaType()
        val retrofit = Retrofit.Builder()
            .baseUrl(server.url("/"))
            .client(client)
            .addConverterFactory(json.asConverterFactory(contentType))
            .build()
        val api = retrofit.create(MealsyApi::class.java)
        return GoalsRepository(api)
    }

    private fun sampleGoals() = Goals(
        trackingMode = "goals",
        kcalGoal = 2200.0,
        proteinGoal = 140.0,
        fiberGoal = 30.0,
        dietaryPrefs = mapOf("vegetarian" to true),
    )

    @Test
    fun `get maps 404 to null`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(404).setBody("""{"detail":"not onboarded"}"""))

        val result = buildRepository().get()

        assertNull(result)
    }

    @Test
    fun `get maps 200 to Goals`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """
                {
                  "tracking_mode": "goals",
                  "kcal_goal": 2200.0,
                  "protein_goal": 140.0,
                  "fiber_goal": 30.0,
                  "dietary_prefs": {},
                  "first_meal_time": "08:00",
                  "streak_days": 4
                }
                """.trimIndent(),
            ),
        )

        val result = buildRepository().get()

        assertEquals("goals", result?.trackingMode)
        assertEquals(2200.0, result?.kcalGoal)
        assertEquals(4, result?.streakDays)
    }

    @Test
    fun `create posts snake_case body`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(201).setBody(
                """
                {
                  "tracking_mode": "goals",
                  "kcal_goal": 2200.0,
                  "protein_goal": 140.0,
                  "fiber_goal": 30.0,
                  "dietary_prefs": {},
                  "first_meal_time": null,
                  "streak_days": 0
                }
                """.trimIndent(),
            ),
        )

        buildRepository().create(sampleGoals())

        val request = server.takeRequest()
        assertEquals("POST", request.method)
        assertEquals("/goals", request.path)
        val body = request.body.readUtf8()
        assertTrue(body.contains("\"tracking_mode\":\"goals\""))
        assertTrue(body.contains("\"kcal_goal\":2200.0"))
        assertTrue(body.contains("\"protein_goal\":140.0"))
        assertTrue(body.contains("\"fiber_goal\":30.0"))
        assertTrue(body.contains("\"dietary_prefs\":{\"vegetarian\":true}"))
    }

    @Test
    fun `update puts snake_case body`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """
                {
                  "tracking_mode": "goals",
                  "kcal_goal": 2200.0,
                  "protein_goal": 140.0,
                  "fiber_goal": 30.0,
                  "dietary_prefs": {},
                  "first_meal_time": null,
                  "streak_days": 0
                }
                """.trimIndent(),
            ),
        )

        buildRepository().update(sampleGoals())

        val request = server.takeRequest()
        assertEquals("PUT", request.method)
        assertEquals("/goals", request.path)
    }
}
