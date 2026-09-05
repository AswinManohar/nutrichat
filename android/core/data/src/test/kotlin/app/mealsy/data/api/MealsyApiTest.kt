package app.mealsy.data.api

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
import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory

/** MockWebServer-backed tests for [MealsyApi], [AuthInterceptor], and DTO (de)serialization. */
class MealsyApiTest {

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

    private fun buildApi(tokenProvider: TokenProvider = TokenProvider { "token" }): MealsyApi {
        val client = OkHttpClient.Builder()
            .addInterceptor(AuthInterceptor(tokenProvider))
            .build()
        val contentType = MEDIA_TYPE_JSON
        val retrofit = Retrofit.Builder()
            .baseUrl(server.url("/"))
            .client(client)
            .addConverterFactory(json.asConverterFactory(contentType))
            .build()
        return retrofit.create(MealsyApi::class.java)
    }

    @Test
    fun `logTurn serializes snake_case body`() = runBlocking {
        server.enqueue(
            MockResponse()
                .setResponseCode(200)
                .setBody(
                    """{"status":"confirm","message":"hi","paused":true,"items":[]}""",
                ),
        )
        val api = buildApi()

        api.logTurn(LogTurnRequest(userInput = "two eggs", conversationId = "abc123"))

        val recorded = server.takeRequest()
        assertTrue(recorded.body.readUtf8().contains("\"user_input\""))
    }

    @Test
    fun `paused card parses items`() = runBlocking {
        server.enqueue(
            MockResponse()
                .setResponseCode(200)
                .setBody(
                    """
                    {
                      "status": "confirm",
                      "message": "Got it — 2 eggs. Log as breakfast?",
                      "paused": true,
                      "items": [
                        {"food_name": "egg", "qty_g": 100, "kcal": 155, "protein_g": 13, "carbs_g": 1.1, "fat_g": 11, "fiber_g": 0, "fdc_id": 12345}
                      ]
                    }
                    """.trimIndent(),
                ),
        )
        val api = buildApi()

        val response = api.logTurn(LogTurnRequest(userInput = "two eggs"))

        assertEquals(true, response.paused)
        assertEquals(1, response.items.size)
        assertEquals("egg", response.items[0].foodName)

        val card = response.toCard()
        assertEquals(1, card?.items?.size)
        assertEquals(100.0, card?.items?.get(0)?.targetQtyG)
    }

    @Test
    fun `401 triggers one refresh retry`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(401))
        server.enqueue(
            MockResponse()
                .setResponseCode(200)
                .setBody("""{"kcal":1450.0,"protein_g":88.0,"fiber_g":14.0,"n_meals":3,"by_type":[]}"""),
        )
        var calls = 0
        val forceRefreshFlags = mutableListOf<Boolean>()
        val tokenProvider = TokenProvider { forceRefresh ->
            calls++
            forceRefreshFlags.add(forceRefresh)
            "token-$calls"
        }
        val api = buildApi(tokenProvider)

        val response = api.today()

        assertEquals(2, calls)
        assertEquals(listOf(false, true), forceRefreshFlags)
        assertEquals(1450.0, response.kcal, 0.0)

        server.takeRequest() // the initial, unauthenticated-refresh 401 attempt
        val retried = server.takeRequest()
        assertEquals("Bearer token-2", retried.getHeader("Authorization"))
    }

    @Test
    fun `unknown response fields ignored`() = runBlocking {
        server.enqueue(
            MockResponse()
                .setResponseCode(200)
                .setBody(
                    """{"kcal":1450.0,"protein_g":88.0,"fiber_g":14.0,"n_meals":3,"by_type":[],"totally_new_field":"surprise"}""",
                ),
        )
        val api = buildApi()

        val response = api.today()

        assertEquals(1450.0, response.kcal, 0.0)
    }

    @Test
    fun `retrofit builds when base url has no trailing slash`() {
        val retrofit = Retrofit.Builder()
            .baseUrl(normalizeBaseUrl("http://10.0.2.2:8000"))
            .addConverterFactory(json.asConverterFactory(MEDIA_TYPE_JSON))
            .build()

        val api = retrofit.create(MealsyApi::class.java)

        assertTrue(api is MealsyApi)
    }

    @Test
    fun `unknown item fields round-trip through extras on encode`() = runBlocking {
        server.enqueue(
            MockResponse()
                .setResponseCode(200)
                .setBody(
                    """
                    {
                      "status": "confirm",
                      "message": "Got it.",
                      "paused": true,
                      "items": [
                        {
                          "food_name": "egg", "qty_g": 100, "kcal": 155, "protein_g": 13,
                          "carbs_g": 1.1, "fat_g": 11, "fiber_g": 0, "fdc_id": 12345,
                          "source": "usda", "nutrients": {"vitamin_d": 1.1, "calcium": 25}
                        }
                      ]
                    }
                    """.trimIndent(),
                ),
        )
        server.enqueue(
            MockResponse()
                .setResponseCode(200)
                .setBody(
                    """{"meal_id":"m_1","meal_type":"breakfast","n_items":1,"kcal":155.0,"protein_g":13.0,"carbs_g":1.1,"fat_g":11.0,"fiber_g":0.0,"message":"Logged.","deduplicated":false}""",
                ),
        )
        val api = buildApi()

        val turnResponse = api.logTurn(LogTurnRequest(userInput = "an egg"))
        server.takeRequest() // drain the logTurn request

        api.logItems(
            LogItemsRequest(
                mealType = "breakfast",
                items = turnResponse.items,
            ),
        )
        val recorded = server.takeRequest().body.readUtf8()

        assertTrue(recorded.contains("\"source\":\"usda\""))
        assertTrue(recorded.contains("\"nutrients\":{\"vitamin_d\":1.1,\"calcium\":25}"))
        assertTrue(!recorded.contains("\"extras\""))
    }

    @Test
    fun `registerDevice always serializes platform`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(201).setBody("""{"status":"registered"}"""))
        val api = buildApi()

        api.registerDevice(RegisterDeviceRequest(token = "fcm-token-123"))

        val recorded = server.takeRequest().body.readUtf8()
        assertTrue(recorded.contains("\"platform\":\"fcm\""))
    }
}

private val MEDIA_TYPE_JSON = "application/json".toMediaType()
