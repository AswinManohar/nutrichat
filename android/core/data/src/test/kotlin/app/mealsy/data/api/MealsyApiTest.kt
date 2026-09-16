package app.mealsy.data.api

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonPrimitive
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

    @Test
    fun `today parses carbs_g, fat_g, and by_type n_meals when present`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """
                {
                  "kcal": 1450.0,
                  "protein_g": 88.0,
                  "carbs_g": 160.0,
                  "fat_g": 42.0,
                  "fiber_g": 14.0,
                  "n_meals": 3,
                  "by_type": [
                    {"meal_type": "breakfast", "kcal": 450.0, "summary": "eggs, toast", "n_meals": 1}
                  ]
                }
                """.trimIndent(),
            ),
        )
        val api = buildApi()

        val response = api.today()

        assertEquals(160.0, response.carbsG, 0.0)
        assertEquals(42.0, response.fatG, 0.0)
        assertEquals(1, response.byType.single().nMeals)
    }

    @Test
    fun `today defaults carbs_g, fat_g, and by_type n_meals for older servers`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """
                {
                  "kcal": 1450.0,
                  "protein_g": 88.0,
                  "fiber_g": 14.0,
                  "n_meals": 3,
                  "by_type": [
                    {"meal_type": "breakfast", "kcal": 450.0, "summary": "eggs, toast"}
                  ]
                }
                """.trimIndent(),
            ),
        )
        val api = buildApi()

        val response = api.today()

        assertEquals(0.0, response.carbsG, 0.0)
        assertEquals(0.0, response.fatG, 0.0)
        assertEquals(0, response.byType.single().nMeals)
    }

    @Test
    fun `listMealLogs sends date and meal_type query params`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))
        val api = buildApi()

        api.listMealLogs(date = "2026-09-16", mealType = "breakfast")

        val request = server.takeRequest()
        assertEquals("GET", request.method)
        assertEquals("/meals/log?date=2026-09-16&meal_type=breakfast", request.path)
    }

    @Test
    fun `listMealLogs omits null query params`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))
        val api = buildApi()

        api.listMealLogs()

        val request = server.takeRequest()
        assertEquals("/meals/log", request.path)
    }

    @Test
    fun `listMealLogs parses a summary with a null label`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """
                [
                  {
                    "meal_id": "m_789",
                    "meal_type": "breakfast",
                    "logged_at": "2026-09-16T06:12:00Z",
                    "label": null,
                    "kcal": 450.0,
                    "protein_g": 28.0,
                    "carbs_g": 38.0,
                    "fat_g": 20.0,
                    "fiber_g": 4.0,
                    "n_items": 2
                  }
                ]
                """.trimIndent(),
            ),
        )
        val api = buildApi()

        val response = api.listMealLogs()

        assertEquals(1, response.size)
        assertEquals("m_789", response[0].mealId)
        assertEquals(null, response[0].label)
        assertEquals(2, response[0].nItems)
    }

    @Test
    fun `mealLog fetches the meal_id path and parses items with extras`() = runBlocking {
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
                      "sugar_g": 1.0,
                      "sat_fat_g": 3.3,
                      "nutrients": {},
                      "source": "USDA",
                      "estimated": false,
                      "source_dish": null,
                      "is_composite": false
                    }
                  ]
                }
                """.trimIndent(),
            ),
        )
        val api = buildApi()

        val response = api.mealLog("m_789")

        val request = server.takeRequest()
        assertEquals("GET", request.method)
        assertEquals("/meals/log/m_789", request.path)

        assertEquals("m_789", response.mealId)
        assertEquals("Eggs on toast", response.label)
        assertEquals(1, response.items.size)
        val item = response.items[0]
        assertEquals("egg whole cooked scrambled", item.foodName)
        assertEquals(12345L, item.fdcId)
        assertEquals("USDA", item.extras["source"]?.jsonPrimitive?.content)
        assertTrue(item.extras.containsKey("match_confidence"))
        assertTrue(item.extras.containsKey("candidates"))
    }

    @Test
    fun `deleteMealLog sends DELETE to meals-log slash id`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(204))
        val api = buildApi()

        api.deleteMealLog("m_789")

        val request = server.takeRequest()
        assertEquals("DELETE", request.method)
        assertEquals("/meals/log/m_789", request.path)
    }
}

private val MEDIA_TYPE_JSON = "application/json".toMediaType()
