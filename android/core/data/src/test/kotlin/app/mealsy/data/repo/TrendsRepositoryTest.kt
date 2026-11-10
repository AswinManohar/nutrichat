package app.mealsy.data.repo

import app.mealsy.data.api.AuthInterceptor
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.TokenProvider
import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory
import kotlinx.coroutines.runBlocking
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

/**
 * MockWebServer-backed tests for [TrendsRepository], golden JSON hand-copied
 * from the shape of `GET /meals/trends` / `GET /meals/categories`
 * (`src/backend/api/meals.py::get_trends`/`get_categories`, documented in
 * `docs/reference/mobile-api.md`) — both bare JSON arrays, no envelope.
 */
class TrendsRepositoryTest {
    private lateinit var server: MockWebServer
    private val json =
        Json {
            ignoreUnknownKeys = true
            explicitNulls = false
        }

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    private fun buildRepository(): TrendsRepository {
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
        val api = retrofit.create(MealsyApi::class.java)
        return TrendsRepository(api)
    }

    private val trendsGoldenJson =
        """
        [
          {
            "date": "2026-09-01",
            "kcal": 1800.0,
            "protein_g": 95.0,
            "carbs_g": 200.0,
            "fat_g": 62.0,
            "fiber_g": 20.0,
            "n_meals": 3,
            "junk_meals": 1
          },
          {
            "date": "2026-09-02",
            "kcal": 2100.0,
            "protein_g": 130.0,
            "carbs_g": 220.0,
            "fiber_g": 25.0,
            "n_meals": 4,
            "junk_meals": 0
          }
        ]
        """.trimIndent()

    @Test
    fun `trends maps the backend's day array`() =
        runBlocking {
            server.enqueue(MockResponse().setResponseCode(200).setBody(trendsGoldenJson))

            val result = buildRepository().trends(30)

            assertEquals(2, result.days.size)
            assertEquals("2026-09-01", result.days[0].date)
            assertEquals(1800.0, result.days[0].kcal, 0.0)
            assertEquals(95.0, result.days[0].proteinG, 0.0)
            assertEquals(200.0, result.days[0].carbsG, 0.0)
            assertEquals(62.0, result.days[0].fatG, 0.0)
            // The second row has no fat_g, as from a server before Journey: 0, not an error.
            assertEquals(0.0, result.days[1].fatG, 0.0)
            assertEquals(1, result.days[0].junkMeals)
            assertEquals(4, result.days[1].nMeals)
        }

    @Test
    fun `trends records the days query param`() =
        runBlocking {
            server.enqueue(MockResponse().setResponseCode(200).setBody(trendsGoldenJson))

            buildRepository().trends(7)

            val request = server.takeRequest()
            assertEquals("GET", request.method)
            assertTrue(request.path?.contains("days=7") == true)
            assertTrue(request.path?.startsWith("/meals/trends") == true)
        }

    @Test
    fun `empty array maps to empty results, not an error`() =
        runBlocking {
            server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))

            val result = buildRepository().trends(7)

            assertEquals(0, result.days.size)
        }

    @Test
    fun `unknown fields on a trend row are ignored`() =
        runBlocking {
            server.enqueue(
                MockResponse().setResponseCode(200).setBody(
                    """
                    [
                      {
                        "date": "2026-09-01",
                        "kcal": 1800.0,
                        "protein_g": 95.0,
                        "carbs_g": 200.0,
                        "fiber_g": 20.0,
                        "n_meals": 3,
                        "junk_meals": 1,
                        "some_future_field": "ignored"
                      }
                    ]
                    """.trimIndent(),
                ),
            )

            val result = buildRepository().trends(7)

            assertEquals(1, result.days.size)
        }
}
