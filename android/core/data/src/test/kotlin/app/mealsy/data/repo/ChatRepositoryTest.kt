package app.mealsy.data.repo

import app.mealsy.data.api.AuthInterceptor
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.TokenProvider
import app.mealsy.domain.CardEditor
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import retrofit2.Retrofit
import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory

/** MockWebServer-backed tests for [ChatRepository]. */
class ChatRepositoryTest {

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

    private fun buildRepository(): ChatRepository {
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
        return ChatRepository(api)
    }

    @Test
    fun `sendTurn maps paused response to Card`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
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
        val repository = buildRepository()

        val result = repository.sendTurn("two eggs")

        assertTrue(result is TurnResult.Card)
        val card = (result as TurnResult.Card).card
        assertEquals(1, card.items.size)
        assertEquals("egg", card.items[0].foodName)
    }

    @Test
    fun `confirmCard posts client_request_id and edited target_qty_g`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """
                {
                  "status": "confirm",
                  "message": "Got it.",
                  "paused": true,
                  "items": [
                    {"food_name": "egg", "qty_g": 100, "kcal": 155, "protein_g": 13, "carbs_g": 1.1, "fat_g": 11, "fiber_g": 0, "fdc_id": 12345}
                  ]
                }
                """.trimIndent(),
            ),
        )
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"meal_id":"m_1","meal_type":"breakfast","n_items":1,"kcal":232.5,"protein_g":19.5,"carbs_g":1.65,"fat_g":16.5,"fiber_g":0.0,"message":"Logged.","deduplicated":false}""",
            ),
        )
        val repository = buildRepository()

        val turnResult = repository.sendTurn("an egg") as TurnResult.Card
        server.takeRequest()
        val edited = CardEditor.editQty(turnResult.card, 0, 150.0)

        repository.confirmCard(edited)

        val recorded = server.takeRequest().body.readUtf8()
        assertTrue(recorded.contains("\"client_request_id\""))
        assertTrue(recorded.contains("\"target_qty_g\":150.0"))
    }

    @Test
    fun `confirmCard on replayed 200 with deduplicated=true still returns success`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"meal_id":"m_1","meal_type":"breakfast","n_items":1,"kcal":155.0,"protein_g":13.0,"carbs_g":1.1,"fat_g":11.0,"fiber_g":0.0,"message":"Already logged.","deduplicated":true}""",
            ),
        )
        val repository = buildRepository()
        val card = app.mealsy.domain.ConfirmationCard(
            message = "hi",
            items = listOf(
                app.mealsy.domain.CardItem(
                    foodName = "egg", qtyG = 100.0, targetQtyG = 100.0,
                    kcal = 155.0, proteinG = 13.0, carbsG = 1.1, fatG = 11.0, fiberG = 0.0,
                    fdcId = 12345,
                ),
            ),
            mealType = "breakfast",
        )

        val outcome = repository.confirmCard(card)

        assertEquals(true, outcome.deduplicated)
        assertEquals("m_1", outcome.mealId)
    }

    @Test
    fun `recoverPending maps paused=false to null`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"status":"success","message":"","paused":false,"items":[]}""",
            ),
        )
        val repository = buildRepository()

        val card = repository.recoverPending()

        assertNull(card)
    }

    @Test
    fun `conversationId rotates after confirm`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"meal_id":"m_1","meal_type":"breakfast","n_items":1,"kcal":155.0,"protein_g":13.0,"carbs_g":1.1,"fat_g":11.0,"fiber_g":0.0,"message":"Logged.","deduplicated":false}""",
            ),
        )
        val repository = buildRepository()
        val before = repository.conversationId
        val card = app.mealsy.domain.ConfirmationCard(
            message = "hi",
            items = listOf(
                app.mealsy.domain.CardItem(
                    foodName = "egg", qtyG = 100.0, targetQtyG = 100.0,
                    kcal = 155.0, proteinG = 13.0, carbsG = 1.1, fatG = 11.0, fiberG = 0.0,
                    fdcId = 12345,
                ),
            ),
            mealType = "breakfast",
        )

        repository.confirmCard(card)

        assertNotEquals(before, repository.conversationId)
    }
}
