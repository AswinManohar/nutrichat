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
import okhttp3.mockwebserver.SocketPolicy
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import retrofit2.Retrofit
import java.util.concurrent.TimeUnit

/** MockWebServer-backed tests for [FoodRepository] (spec 003, T025). */
class FoodRepositoryTest {
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

    private fun buildRepository(): FoodRepository {
        val client =
            OkHttpClient.Builder()
                .addInterceptor(AuthInterceptor(TokenProvider { "token" }))
                .readTimeout(2, TimeUnit.SECONDS)
                .build()
        val contentType = "application/json".toMediaType()
        val retrofit =
            Retrofit.Builder()
                .baseUrl(server.url("/"))
                .client(client)
                .addConverterFactory(json.asConverterFactory(contentType))
                .build()
        val api = retrofit.create(MealsyApi::class.java)
        return FoodRepository(api)
    }

    @Test
    fun `search returns results ordered as sent`() =
        runBlocking {
            server.enqueue(
                MockResponse().setResponseCode(200).setBody(
                    """
                    {
                      "query": "toast",
                      "normalized_query": "toast",
                      "results": [
                        {"fdc_id": 172687, "name": "Bread, white, toasted", "data_type": "sr_legacy",
                         "kcal_per_100g": 293.0, "protein_g_per_100g": 9.0, "kcal": 82.0, "protein_g": 2.5}
                      ]
                    }
                    """.trimIndent(),
                ),
            )
            val outcome = buildRepository().search("toast", qtyG = 28.0)
            check(outcome is FoodSearchOutcome.Results)
            assertEquals(1, outcome.hits.size)
            assertEquals(172687L, outcome.hits[0].fdcId)
            assertEquals(82.0, outcome.hits[0].kcal, 0.001)
        }

    @Test
    fun `search maps empty results to Empty`() =
        runBlocking {
            server.enqueue(
                MockResponse().setResponseCode(200).setBody(
                    """{"query": "xyzzy", "normalized_query": "xyzzy", "results": []}""",
                ),
            )
            val outcome = buildRepository().search("xyzzy", qtyG = 100.0)
            assertTrue(outcome is FoodSearchOutcome.Empty)
        }

    @Test
    fun `search maps 503 to Unavailable`() =
        runBlocking {
            server.enqueue(
                MockResponse().setResponseCode(503).setBody("""{"detail": "food_search_unavailable"}"""),
            )
            val outcome = buildRepository().search("toast", qtyG = 100.0)
            assertTrue(outcome is FoodSearchOutcome.Unavailable)
        }

    @Test
    fun `search maps a network failure to Error`() =
        runBlocking {
            server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AT_START))
            val outcome = buildRepository().search("toast", qtyG = 100.0)
            assertTrue(outcome is FoodSearchOutcome.Error)
        }

    @Test
    fun `search past 3s maps to Error, not a hang (A1)`() =
        runBlocking {
            // Longer than [FoodRepository]'s own 3s search timeout, but well
            // under this client's 2s OkHttp readTimeout so the coroutine
            // timeout — not OkHttp's — is what's under test. A slow real
            // server (not OkHttp itself timing out) is simulated by making
            // OkHttp's own read timeout longer than 3s here.
            val client =
                OkHttpClient.Builder()
                    .addInterceptor(AuthInterceptor(TokenProvider { "token" }))
                    .readTimeout(10, TimeUnit.SECONDS)
                    .build()
            val contentType = "application/json".toMediaType()
            val retrofit =
                Retrofit.Builder()
                    .baseUrl(server.url("/"))
                    .client(client)
                    .addConverterFactory(json.asConverterFactory(contentType))
                    .build()
            val api = retrofit.create(MealsyApi::class.java)
            val repository = FoodRepository(api)

            server.enqueue(
                MockResponse()
                    .setResponseCode(200)
                    .setBody("""{"query": "toast", "normalized_query": "toast", "results": []}""")
                    .setBodyDelay(5, TimeUnit.SECONDS),
            )
            val startNanos = System.nanoTime()
            val outcome = repository.search("toast", qtyG = 100.0)
            val elapsedMs = (System.nanoTime() - startNanos) / 1_000_000
            assertTrue(outcome is FoodSearchOutcome.Error)
            assertTrue("expected the 3s timeout to fire, took ${elapsedMs}ms", elapsedMs < 4_500)
        }

    @Test
    fun `getFood maps the card-item shape`() =
        runBlocking {
            server.enqueue(
                MockResponse().setResponseCode(200).setBody(
                    """
                    {
                      "food_name": "Bread, white, commercially prepared, toasted",
                      "qty_g": 28.0,
                      "kcal": 82.0, "protein_g": 2.5, "carbs_g": 15.0, "fat_g": 1.0, "fiber_g": 0.8,
                      "fdc_id": 172687, "estimated": false, "source": "usda_local",
                      "confidence": 1.0, "candidates": []
                    }
                    """.trimIndent(),
                ),
            )
            val item = buildRepository().getFood(172687, qtyG = 28.0)
            assertEquals(172687L, item.fdcId)
            assertEquals(28.0, item.qtyG, 0.001)
            assertEquals(28.0, item.targetQtyG, 0.001)
            assertEquals("usda_local", item.source)
        }
}
