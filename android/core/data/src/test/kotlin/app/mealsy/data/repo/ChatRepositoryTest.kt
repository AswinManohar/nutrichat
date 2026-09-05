package app.mealsy.data.repo

import app.mealsy.data.api.AuthInterceptor
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.TokenProvider
import app.mealsy.domain.CardEditor
import app.mealsy.domain.CardItem
import app.mealsy.domain.ConfirmationCard
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import retrofit2.HttpException
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

    private fun buildRepository(store: ConversationIdStore = FakeConversationIdStore()): ChatRepository {
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
        return ChatRepository(api, store)
    }

    private fun sampleCard(mealType: String = "breakfast") = ConfirmationCard(
        message = "hi",
        items = listOf(
            CardItem(
                foodName = "egg", qtyG = 100.0, targetQtyG = 100.0,
                kcal = 155.0, proteinG = 13.0, carbsG = 1.1, fatG = 11.0, fiberG = 0.0,
                fdcId = 12345,
            ),
        ),
        mealType = mealType,
    )

    private fun clientRequestIdOf(body: String): String? =
        Regex("\"client_request_id\":\"([^\"]+)\"").find(body)?.groupValues?.get(1)

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
        val turnRequest = server.takeRequest()
        assertTrue(turnRequest.body.readUtf8().contains("\"conversation_id\""))
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

        val outcome = repository.confirmCard(sampleCard())

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
        val before = repository.conversationId()

        repository.confirmCard(sampleCard())

        assertNotEquals(before, repository.conversationId())
    }

    // --- Fix round 1 -----------------------------------------------------

    @Test
    fun `retry of the same card after a failed confirm reuses the client_request_id`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody(pausedCardBody()))
        server.enqueue(MockResponse().setResponseCode(500))
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"meal_id":"m_1","meal_type":"breakfast","n_items":1,"kcal":155.0,"protein_g":13.0,"carbs_g":1.1,"fat_g":11.0,"fiber_g":0.0,"message":"Logged.","deduplicated":false}""",
            ),
        )
        val repository = buildRepository()
        val card = (repository.sendTurn("an egg") as TurnResult.Card).card
        server.takeRequest() // drain the turn request

        try {
            repository.confirmCard(card)
        } catch (exc: HttpException) {
            // expected — the first attempt fails
        }
        repository.confirmCard(card)

        val firstAttemptId = clientRequestIdOf(server.takeRequest().body.readUtf8())
        val retryId = clientRequestIdOf(server.takeRequest().body.readUtf8())
        assertNotNull(firstAttemptId)
        assertEquals(firstAttemptId, retryId)
    }

    @Test
    fun `a new card after a failed confirm gets a different client_request_id`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody(pausedCardBody(foodName = "egg")))
        server.enqueue(MockResponse().setResponseCode(500))
        server.enqueue(MockResponse().setResponseCode(200).setBody(pausedCardBody(foodName = "toast")))
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"meal_id":"m_2","meal_type":"breakfast","n_items":1,"kcal":155.0,"protein_g":13.0,"carbs_g":1.1,"fat_g":11.0,"fiber_g":0.0,"message":"Logged.","deduplicated":false}""",
            ),
        )
        val repository = buildRepository()
        val cardA = (repository.sendTurn("two eggs") as TurnResult.Card).card
        server.takeRequest() // drain turn A

        try {
            repository.confirmCard(cardA)
        } catch (exc: HttpException) {
            // expected — card A's confirm fails
        }
        val firstAttemptId = clientRequestIdOf(server.takeRequest().body.readUtf8())

        val cardB = (repository.sendTurn("actually just toast") as TurnResult.Card).card
        server.takeRequest() // drain turn B
        repository.confirmCard(cardB)
        val secondAttemptId = clientRequestIdOf(server.takeRequest().body.readUtf8())

        assertNotEquals(cardA, cardB)
        assertNotNull(firstAttemptId)
        assertNotNull(secondAttemptId)
        assertNotEquals(firstAttemptId, secondAttemptId)
    }

    @Test
    fun `cancelCard clears any pending confirmation id`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody(pausedCardBody(foodName = "egg")))
        server.enqueue(MockResponse().setResponseCode(500))
        server.enqueue(
            MockResponse().setResponseCode(200)
                .setBody("""{"status":"success","message":"Cancelled.","paused":false,"items":[]}"""),
        )
        // cancelCard's "Cancelled." reply is unpaused with no items and no
        // upgrade marker, so it falls through to the quota-check gate
        // (fix #3) — one more response to satisfy that GET /quota call.
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"used":1,"limit":50,"remaining":49,"exhausted":false,"tier":"free"}""",
            ),
        )
        server.enqueue(MockResponse().setResponseCode(200).setBody(pausedCardBody(foodName = "toast")))
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"meal_id":"m_3","meal_type":"breakfast","n_items":1,"kcal":155.0,"protein_g":13.0,"carbs_g":1.1,"fat_g":11.0,"fiber_g":0.0,"message":"Logged.","deduplicated":false}""",
            ),
        )
        val repository = buildRepository()
        val cardA = (repository.sendTurn("two eggs") as TurnResult.Card).card
        server.takeRequest()
        try {
            repository.confirmCard(cardA)
        } catch (exc: HttpException) {
            // expected
        }
        val firstAttemptBody = server.takeRequest().body.readUtf8()
        val firstAttemptId = clientRequestIdOf(firstAttemptBody)

        repository.cancelCard()
        server.takeRequest() // drain cancel's sendTurn("cancel") request
        server.takeRequest() // drain the resulting quota() check

        val cardB = (repository.sendTurn("two eggs again") as TurnResult.Card).card
        server.takeRequest()
        repository.confirmCard(cardB)
        val secondAttemptId = clientRequestIdOf(server.takeRequest().body.readUtf8())

        assertNotEquals(firstAttemptId, secondAttemptId)
    }

    @Test
    fun `recoverPending recovers the same conversation id across repository instances`() = runBlocking {
        val store = FakeConversationIdStore()
        server.enqueue(MockResponse().setResponseCode(200).setBody(emptyTurnBody()))
        val repo1 = buildRepository(store)
        repo1.sendTurn("two eggs")
        val turnBody = server.takeRequest().body.readUtf8()
        val persistedId = Regex("\"conversation_id\":\"([^\"]+)\"").find(turnBody)?.groupValues?.get(1)
        assertNotNull(persistedId)

        server.enqueue(MockResponse().setResponseCode(200).setBody(emptyTurnBody()))
        val repo2 = buildRepository(store)
        repo2.recoverPending()
        val pendingRequest = server.takeRequest()

        assertEquals(persistedId, pendingRequest.requestUrl?.queryParameter("conversation_id"))
    }

    @Test
    fun `sendTurn recovers the pending card after a dropped connection`() = runBlocking {
        server.enqueue(
            MockResponse().setSocketPolicy(okhttp3.mockwebserver.SocketPolicy.DISCONNECT_AT_START),
        )
        server.enqueue(MockResponse().setResponseCode(200).setBody(pausedCardBody()))
        val repository = buildRepository()

        val result = repository.sendTurn("two eggs")

        assertTrue(result is TurnResult.Card)
        assertEquals(1, (result as TurnResult.Card).card.items.size)
    }

    @Test
    fun `sendTurn rethrows when a dropped connection has nothing pending to recover`() = runBlocking {
        server.enqueue(
            MockResponse().setSocketPolicy(okhttp3.mockwebserver.SocketPolicy.DISCONNECT_AT_START),
        )
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"status":"success","message":"","paused":false,"items":[]}""",
            ),
        )
        val repository = buildRepository()

        var threw = false
        try {
            repository.sendTurn("two eggs")
        } catch (exc: java.io.IOException) {
            threw = true
        }

        assertTrue(threw)
    }

    @Test
    fun `unpaused empty-item turn without the marker falls back to a quota check`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"status":"success","message":"Please visit mealsy.app/upgrade soon.","paused":false,"items":[]}""",
            ),
        )
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"used":50,"limit":50,"remaining":0,"exhausted":true,"tier":"free"}""",
            ),
        )
        val repository = buildRepository()

        val result = repository.sendTurn("anything")

        assertTrue(result is TurnResult.UpgradeRequired)
        assertFalse((result as TurnResult.UpgradeRequired).message.contains("mealsy.app"))
    }

    @Test
    fun `reply text is stripped of urls`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """
                {
                  "status": "success",
                  "message": "See mealsy.app/faq for details.",
                  "paused": false,
                  "items": [
                    {"food_name": "egg", "qty_g": 1, "kcal": 1, "protein_g": 1, "carbs_g": 1, "fat_g": 1, "fiber_g": 1, "fdc_id": 1}
                  ]
                }
                """.trimIndent(),
            ),
        )
        val repository = buildRepository()

        val result = repository.sendTurn("anything")

        assertTrue(result is TurnResult.Reply)
        assertFalse((result as TurnResult.Reply).message.contains("mealsy.app"))
    }

    private fun pausedCardBody(foodName: String = "egg"): String = """
        {
          "status": "confirm",
          "message": "Got it.",
          "paused": true,
          "items": [
            {"food_name": "$foodName", "qty_g": 100, "kcal": 155, "protein_g": 13, "carbs_g": 1.1, "fat_g": 11, "fiber_g": 0, "fdc_id": 12345}
          ]
        }
    """

    private fun emptyTurnBody(): String =
        """{"status":"success","message":"OK.","paused":false,"items":[{"food_name":"x","qty_g":1,"kcal":1,"protein_g":1,"carbs_g":1,"fat_g":1,"fiber_g":1,"fdc_id":1}]}"""
}
