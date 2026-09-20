package app.mealsy.data.repo

import app.mealsy.data.api.AuthInterceptor
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.TokenProvider
import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.coroutines.yield
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
import retrofit2.HttpException
import retrofit2.Retrofit
import java.time.LocalDate

/**
 * MockWebServer-backed tests for [MealsRepository], golden JSON hand-copied
 * from `src/backend/api/meals.py` / `docs/reference/mobile-api.md`'s
 * `/meals/log` section.
 */
class MealsRepositoryTest {
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

    private fun buildRepository(todayRefreshSignal: TodayRefreshSignal = TodayRefreshSignal()): MealsRepository {
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
        return MealsRepository(api, todayRefreshSignal)
    }

    private val summaryGoldenJson =
        """
        [
          {
            "meal_id": "m_789",
            "meal_type": "breakfast",
            "logged_at": "2026-09-16T06:12:00Z",
            "label": "Eggs on toast",
            "kcal": 450.0,
            "protein_g": 28.0,
            "carbs_g": 38.0,
            "fat_g": 20.0,
            "fiber_g": 4.0,
            "n_items": 2
          }
        ]
        """.trimIndent()

    @Test
    fun `listForDay defaults to today and maps the backend's bare array`() =
        runBlocking {
            server.enqueue(MockResponse().setResponseCode(200).setBody(summaryGoldenJson))

            val result = buildRepository().listForDay()

            assertEquals(1, result.size)
            assertEquals("m_789", result[0].mealId)
            assertEquals("Eggs on toast", result[0].label)
            assertEquals(2, result[0].nItems)

            val request = server.takeRequest()
            assertEquals("GET", request.method)
            assertEquals("/meals/log?date=${LocalDate.now()}", request.path)
        }

    @Test
    fun `listForDay filters by meal type`() =
        runBlocking {
            server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))

            val date = LocalDate.of(2026, 9, 1)
            val result = buildRepository().listForDay(date = date, mealType = "lunch")

            assertTrue(result.isEmpty())

            val request = server.takeRequest()
            assertEquals("/meals/log?date=2026-09-01&meal_type=lunch", request.path)
        }

    @Test
    fun `detail parses meal fields plus items`() =
        runBlocking {
            server.enqueue(
                MockResponse().setResponseCode(200).setBody(
                    """
                    {
                      "meal_id": "m_789",
                      "meal_type": "breakfast",
                      "logged_at": "2026-09-16T06:12:00Z",
                      "label": "Eggs on toast",
                      "kcal": 450.0,
                      "protein_g": 28.0,
                      "carbs_g": 38.0,
                      "fat_g": 20.0,
                      "fiber_g": 4.0,
                      "n_items": 1,
                      "items": [
                        {
                          "fdc_id": 12345,
                          "food_name": "egg whole cooked scrambled",
                          "qty_g": 100.0,
                          "match_confidence": 0.92,
                          "candidates": [],
                          "kcal": 156.0,
                          "protein_g": 12.4,
                          "carbs_g": 1.2,
                          "fat_g": 10.8,
                          "fiber_g": 0.0,
                          "source": "USDA",
                          "estimated": false
                        }
                      ]
                    }
                    """.trimIndent(),
                ),
            )

            val result = buildRepository().detail("m_789")

            assertEquals("m_789", result.meal.mealId)
            assertEquals("Eggs on toast", result.meal.label)
            assertEquals(1, result.items.size)
            assertEquals("egg whole cooked scrambled", result.items[0].foodName)
            assertEquals(12345L, result.items[0].fdcId)
            // "source" is now a modeled ItemDto field (T1 wave), so it no longer
            // flows into LoggedMealItem.extras.
            assertTrue(!result.items[0].extras.containsKey("source"))

            val request = server.takeRequest()
            assertEquals("GET", request.method)
            assertEquals("/meals/log/m_789", request.path)
        }

    @Test
    fun `delete sends DELETE and emits TodayRefreshSignal`() =
        runBlocking {
            server.enqueue(MockResponse().setResponseCode(204))

            val signal = TodayRefreshSignal()
            val emitted = async { withTimeoutOrNull(1_000) { signal.events.first() } }
            yield() // let the collector above subscribe before the emit fires
            buildRepository(signal).delete("m_789")

            val request = server.takeRequest()
            assertEquals("DELETE", request.method)
            assertEquals("/meals/log/m_789", request.path)
            assertEquals(Unit, emitted.await())
        }

    @Test(expected = HttpException::class)
    fun `delete propagates a 404 for an unknown or foreign meal`(): Unit =
        runBlocking {
            server.enqueue(MockResponse().setResponseCode(404).setBody("""{"detail":"Meal not found"}"""))

            buildRepository().delete("missing")
        }
}
