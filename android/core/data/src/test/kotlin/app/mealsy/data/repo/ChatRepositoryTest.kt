package app.mealsy.data.repo

import app.mealsy.data.api.AuthInterceptor
import app.mealsy.data.api.LogItemsRequest
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.TokenProvider
import app.mealsy.data.offline.PendingLogQueue
import app.mealsy.domain.CardEditor
import app.mealsy.domain.CardItem
import app.mealsy.domain.ConfirmationCard
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
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Retrofit

/** In-memory [PendingLogQueue] fake — records what was enqueued, does nothing else. */
class FakePendingLogQueue : PendingLogQueue {
    data class Entry(val clientRequestId: String, val payloadJson: String)

    val enqueued = mutableListOf<Entry>()

    override suspend fun enqueue(
        clientRequestId: String,
        payloadJson: String,
    ) {
        enqueued += Entry(clientRequestId, payloadJson)
    }
}

/** MockWebServer-backed tests for [ChatRepository]. */
class ChatRepositoryTest {
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

    private fun buildRepository(
        store: ConversationIdStore = FakeConversationIdStore(),
        pendingLogQueue: PendingLogQueue = FakePendingLogQueue(),
        todayRefreshSignal: TodayRefreshSignal = TodayRefreshSignal(),
    ): ChatRepository {
        val client =
            OkHttpClient.Builder()
                .addInterceptor(AuthInterceptor(TokenProvider { "token" }))
                // No keep-alive connection reuse: a SocketPolicy.DISCONNECT_AT_START
                // response behaves inconsistently on a warm, reused connection
                // (OkHttp can silently open a fresh connection and retry against
                // the *next* queued response instead of surfacing an IOException).
                // A fresh connection per request keeps the dropped-connection
                // tests deterministic.
                .connectionPool(okhttp3.ConnectionPool(0, 1, java.util.concurrent.TimeUnit.NANOSECONDS))
                .build()
        val contentType = "application/json".toMediaType()
        val retrofit =
            Retrofit.Builder()
                .baseUrl(server.url("/"))
                .client(client)
                .addConverterFactory(json.asConverterFactory(contentType))
                .build()
        val api = retrofit.create(MealsyApi::class.java)
        return ChatRepository(api, store, pendingLogQueue, json, todayRefreshSignal)
    }

    private fun sampleCard(mealType: String = "breakfast") =
        ConfirmationCard(
            message = "hi",
            items =
                listOf(
                    CardItem(
                        foodName = "egg", qtyG = 100.0, targetQtyG = 100.0,
                        kcal = 155.0, proteinG = 13.0, carbsG = 1.1, fatG = 11.0, fiberG = 0.0,
                        fdcId = 12345,
                    ),
                ),
            mealType = mealType,
        )

    private fun clientRequestIdOf(body: String): String? = Regex("\"client_request_id\":\"([^\"]+)\"").find(body)?.groupValues?.get(1)

    @Test
    fun `sendTurn maps paused response to Card`() =
        runBlocking {
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
    @Suppress("ktlint:standard:max-line-length")
    fun `confirmCard posts client_request_id and edited target_qty_g`() =
        runBlocking {
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
    @Suppress("ktlint:standard:max-line-length")
    fun `confirmCard on replayed 200 with deduplicated=true still returns success`() =
        runBlocking {
            server.enqueue(
                MockResponse().setResponseCode(200).setBody(
                    """{"meal_id":"m_1","meal_type":"breakfast","n_items":1,"kcal":155.0,"protein_g":13.0,"carbs_g":1.1,"fat_g":11.0,"fiber_g":0.0,"message":"Already logged.","deduplicated":true}""",
                ),
            )
            val signal = TodayRefreshSignal()
            val repository = buildRepository(todayRefreshSignal = signal)
            val emitted = async { withTimeoutOrNull(1_000) { signal.events.first() } }
            yield() // let the collector above subscribe before confirmCard emits

            val outcome = repository.confirmCard(sampleCard()) as LogOutcome.Logged

            assertEquals(true, outcome.deduplicated)
            assertEquals("m_1", outcome.mealId)
            assertEquals(Unit, emitted.await())
        }

    // --- Offline replay queue (Task 7) ------------------------------------

    @Test
    fun `confirmCard on IOException persists the same client_request_id and returns Queued`() =
        runBlocking {
            server.enqueue(
                MockResponse().setSocketPolicy(okhttp3.mockwebserver.SocketPolicy.DISCONNECT_AT_START),
            )
            val queue = FakePendingLogQueue()
            val repository = buildRepository(pendingLogQueue = queue)

            val outcome = repository.confirmCard(sampleCard())

            assertEquals(LogOutcome.Queued, outcome)
            assertEquals(1, queue.enqueued.size)
            val entry = queue.enqueued.single()
            assertTrue(entry.payloadJson.contains("\"client_request_id\":\"${entry.clientRequestId}\""))
            val decoded = json.decodeFromString(LogItemsRequest.serializer(), entry.payloadJson)
            assertEquals(entry.clientRequestId, decoded.clientRequestId)
            assertEquals("breakfast", decoded.mealType)
            assertEquals(1, decoded.items.size)
        }

    @Test
    fun `confirmCard on HttpException does not queue`() =
        runBlocking {
            server.enqueue(MockResponse().setResponseCode(422))
            val queue = FakePendingLogQueue()
            val repository = buildRepository(pendingLogQueue = queue)

            try {
                repository.confirmCard(sampleCard())
                org.junit.Assert.fail("expected HttpException")
            } catch (exc: HttpException) {
                // expected — a rejected payload must never be queued for replay.
            }

            assertTrue(queue.enqueued.isEmpty())
        }

    @Test
    fun `recoverPending maps paused=false to null`() =
        runBlocking {
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
    @Suppress("ktlint:standard:max-line-length")
    fun `conversationId rotates after confirm`() =
        runBlocking {
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
    @Suppress("ktlint:standard:max-line-length")
    fun `retry of the same card after a failed confirm reuses the client_request_id`() =
        runBlocking {
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
    @Suppress("ktlint:standard:max-line-length")
    fun `a new card after a failed confirm gets a different client_request_id`() =
        runBlocking {
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
    @Suppress("ktlint:standard:max-line-length")
    fun `cancelCard clears any pending confirmation id`() =
        runBlocking {
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
            val idBeforeCancel = repository.conversationId()

            repository.cancelCard()
            server.takeRequest() // drain cancel's sendTurn("cancel") request
            server.takeRequest() // drain the resulting quota() check

            // A cancel that actually lands (Reply/UpgradeRequired) rotates the
            // conversation id — see `cancelCard on a dropped connection ...`
            // below for the contrasting case where it must NOT rotate.
            assertNotEquals(idBeforeCancel, repository.conversationId())

            val cardB = (repository.sendTurn("two eggs again") as TurnResult.Card).card
            server.takeRequest()
            repository.confirmCard(cardB)
            val secondAttemptId = clientRequestIdOf(server.takeRequest().body.readUtf8())

            assertNotEquals(firstAttemptId, secondAttemptId)
        }

    @Test
    @Suppress("ktlint:standard:max-line-length")
    fun `cancelCard on a dropped connection keeps the conversation id and pending confirmation`() =
        runBlocking {
            server.enqueue(MockResponse().setResponseCode(200).setBody(pausedCardBody()))
            server.enqueue(MockResponse().setResponseCode(500))
            server.enqueue(
                MockResponse().setSocketPolicy(okhttp3.mockwebserver.SocketPolicy.DISCONNECT_AT_START),
            )
            server.enqueue(MockResponse().setResponseCode(200).setBody(pausedCardBody()))
            server.enqueue(
                MockResponse().setResponseCode(200).setBody(
                    """{"meal_id":"m_4","meal_type":"breakfast","n_items":1,"kcal":155.0,"protein_g":13.0,"carbs_g":1.1,"fat_g":11.0,"fiber_g":0.0,"message":"Logged.","deduplicated":false}""",
                ),
            )
            val repository = buildRepository()
            val cardA = (repository.sendTurn("an egg") as TurnResult.Card).card
            server.takeRequest() // drain the turn request

            try {
                repository.confirmCard(cardA)
            } catch (exc: HttpException) {
                // expected — the confirm attempt fails, but the id it used
                // must survive: the server may have committed it anyway.
            }
            val originalAttemptId = clientRequestIdOf(server.takeRequest().body.readUtf8())
            val idBeforeCancel = repository.conversationId()

            val cancelResult = repository.cancelCard()

            assertTrue(cancelResult is TurnResult.Card)
            val recovered = (cancelResult as TurnResult.Card).card
            assertEquals(cardA, recovered)
            server.takeRequest() // the dropped-connection attempt itself (recorded with a null path)
            // The dropped cancel never actually landed: the conversation id
            // must be untouched, or a later recoverPending() (e.g. after
            // process death) would target a conversation the server never
            // saw, orphaning this still-paused card.
            val pendingRequest = server.takeRequest() // the recovery GET /meals/pending call
            assertEquals(idBeforeCancel, pendingRequest.requestUrl?.queryParameter("conversation_id"))
            assertEquals(idBeforeCancel, repository.conversationId())

            // Re-confirming the same (still-pending) card must reuse the
            // ORIGINAL client_request_id — pendingConfirmation must not have
            // been cleared by the failed cancel, or this would double-log a
            // confirm that may have already committed server-side.
            repository.confirmCard(recovered)
            val retryAttemptId = clientRequestIdOf(server.takeRequest().body.readUtf8())
            assertEquals(originalAttemptId, retryAttemptId)
        }

    @Test
    fun `recoverPending recovers the same conversation id across repository instances`() =
        runBlocking {
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
    fun `sendTurn recovers the pending card after a dropped connection`() =
        runBlocking {
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
    fun `sendTurn rethrows when a dropped connection has nothing pending to recover`() =
        runBlocking {
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
    fun `unpaused empty-item turn without the marker falls back to a quota check`() =
        runBlocking {
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
    fun `reply text is stripped of urls`() =
        runBlocking {
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

    @Test
    fun `reply text without urls survives stripUrls unchanged`() =
        runBlocking {
            val original = "1.5 g of protein, e.g. eggs"
            server.enqueue(
                MockResponse().setResponseCode(200).setBody(
                    """
                    {
                      "status": "success",
                      "message": "$original",
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
            assertEquals(original, (result as TurnResult.Reply).message)
        }

    // --- Correct/decompose/combine turn helpers ---------------------------

    @Test
    fun `correctCandidate sends the same wording the web client sends`() =
        runBlocking {
            server.enqueue(
                MockResponse().setResponseCode(200).setBody(
                    """{"status":"success","message":"Updated.","paused":false,"items":[]}""",
                ),
            )
            val repository = buildRepository()
            val idBefore = repository.conversationId()

            repository.correctCandidate("chicken breast", "chicken thigh")

            val body = server.takeRequest().body.readUtf8()
            assertTrue(body.contains("\"user_input\":\"use chicken thigh instead of chicken breast\""))
            assertTrue(body.contains("\"conversation_id\":\"$idBefore\""))
            assertEquals(idBefore, repository.conversationId())
        }

    @Test
    fun `decompose sends action=decompose with empty user_input and returns Card`() =
        runBlocking {
            server.enqueue(MockResponse().setResponseCode(200).setBody(pausedCardBody()))
            val repository = buildRepository()
            val idBefore = repository.conversationId()

            val result = repository.decompose()

            assertTrue(result is TurnResult.Card)
            val request = server.takeRequest()
            val body = request.body.readUtf8()
            assertTrue(body.contains("\"user_input\":\"\""))
            assertTrue(body.contains("\"action\":\"decompose\""))
            assertTrue(body.contains("\"conversation_id\":\"$idBefore\""))
            assertEquals(idBefore, repository.conversationId())
        }

    @Test
    fun `combine sends action=combine with empty user_input and returns Card`() =
        runBlocking {
            server.enqueue(MockResponse().setResponseCode(200).setBody(pausedCardBody()))
            val repository = buildRepository()
            val idBefore = repository.conversationId()

            val result = repository.combine()

            assertTrue(result is TurnResult.Card)
            val body = server.takeRequest().body.readUtf8()
            assertTrue(body.contains("\"user_input\":\"\""))
            assertTrue(body.contains("\"action\":\"combine\""))
            assertEquals(idBefore, repository.conversationId())
        }

    @Test
    fun `correctCandidate recovers via GET meals-pending on IOException`() =
        runBlocking {
            server.enqueue(
                MockResponse().setSocketPolicy(okhttp3.mockwebserver.SocketPolicy.DISCONNECT_AT_START),
            )
            server.enqueue(MockResponse().setResponseCode(200).setBody(pausedCardBody()))
            val repository = buildRepository()
            val idBefore = repository.conversationId()

            val result = repository.correctCandidate("chicken breast", "chicken thigh")

            assertTrue(result is TurnResult.Card)
            server.takeRequest() // the dropped POST
            val pendingRequest = server.takeRequest()
            assertEquals(idBefore, pendingRequest.requestUrl?.queryParameter("conversation_id"))
            assertEquals(idBefore, repository.conversationId())
        }

    @Test
    fun `decompose recovers via GET meals-pending on IOException`() =
        runBlocking {
            server.enqueue(
                MockResponse().setSocketPolicy(okhttp3.mockwebserver.SocketPolicy.DISCONNECT_AT_START),
            )
            server.enqueue(MockResponse().setResponseCode(200).setBody(pausedCardBody()))
            val repository = buildRepository()

            val result = repository.decompose()

            assertTrue(result is TurnResult.Card)
        }

    @Test
    fun `combine recovers via GET meals-pending on IOException`() =
        runBlocking {
            server.enqueue(
                MockResponse().setSocketPolicy(okhttp3.mockwebserver.SocketPolicy.DISCONNECT_AT_START),
            )
            server.enqueue(MockResponse().setResponseCode(200).setBody(pausedCardBody()))
            val repository = buildRepository()

            val result = repository.combine()

            assertTrue(result is TurnResult.Card)
        }

    @Test
    fun `decompose rethrows when a dropped connection has nothing pending to recover`() =
        runBlocking {
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
                repository.decompose()
            } catch (exc: java.io.IOException) {
                threw = true
            }

            assertTrue(threw)
        }

    @Test
    fun `combine rethrows when a dropped connection has nothing pending to recover`() =
        runBlocking {
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
                repository.combine()
            } catch (exc: java.io.IOException) {
                threw = true
            }

            assertTrue(threw)
        }

    // --- response_id / coaching feedback -----------------------------------

    @Test
    fun `Reply responseId is populated when response_id is present`() =
        runBlocking {
            server.enqueue(
                MockResponse().setResponseCode(200).setBody(
                    """{"status":"success","message":"Great job!","paused":false,"items":[],"response_id":"resp_1"}""",
                ),
            )
            val repository = buildRepository()

            val result = repository.sendTurn("how am I doing?")

            assertTrue(result is TurnResult.Reply)
            assertEquals("resp_1", (result as TurnResult.Reply).responseId)
        }

    @Test
    fun `Reply responseId is null when response_id is absent and does not throw`() =
        runBlocking {
            server.enqueue(
                MockResponse().setResponseCode(200).setBody(
                    """{"status":"success","message":"Great job!","paused":false,"items":[]}""",
                ),
            )
            val repository = buildRepository()

            val result = repository.sendTurn("how am I doing?")

            assertTrue(result is TurnResult.Reply)
            assertNull((result as TurnResult.Reply).responseId)
        }

    @Test
    fun `submitCoachingFeedback posts rating and comment to the right path`() =
        runBlocking {
            server.enqueue(MockResponse().setResponseCode(200))
            val repository = buildRepository()

            repository.submitCoachingFeedback("resp_1", rating = 1, comment = "helpful")

            val request = server.takeRequest()
            assertTrue(request.path?.contains("coaching/resp_1/feedback") == true)
            val body = request.body.readUtf8()
            assertTrue(body.contains("\"rating\":1"))
            assertTrue(body.contains("\"comment\":\"helpful\""))
        }

    @Test
    @Suppress("ktlint:standard:max-line-length")
    fun `submitCoachingFeedback omits a null comment from the wire`() =
        runBlocking {
            server.enqueue(MockResponse().setResponseCode(200))
            val repository = buildRepository()

            repository.submitCoachingFeedback("resp_1", rating = 5)

            val body = server.takeRequest().body.readUtf8()
            assertFalse(body.contains("comment"))
        }

    private fun pausedCardBody(foodName: String = "egg"): String =
        """
        {
          "status": "confirm",
          "message": "Got it.",
          "paused": true,
          "items": [
            {"food_name": "$foodName", "qty_g": 100, "kcal": 155, "protein_g": 13, "carbs_g": 1.1, "fat_g": 11, "fiber_g": 0, "fdc_id": 12345}
          ]
        }
    """

    @Suppress("ktlint:standard:max-line-length")
    private fun emptyTurnBody(): String =
        """{"status":"success","message":"OK.","paused":false,"items":[{"food_name":"x","qty_g":1,"kcal":1,"protein_g":1,"carbs_g":1,"fat_g":1,"fiber_g":1,"fdc_id":1}]}"""
}
