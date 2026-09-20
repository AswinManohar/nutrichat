package app.mealsy.android.ui.chat

import app.mealsy.android.util.ConnectivityObserver
import app.mealsy.data.api.AuthInterceptor
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.TokenProvider
import app.mealsy.data.offline.DroppedLogStore
import app.mealsy.data.offline.PendingLogQueue
import app.mealsy.data.repo.ChatRepository
import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import retrofit2.Retrofit
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset

/** Always-online fake — connectivity-driven offline handling is exercised in [ConnectivityOfflineTest]. */
private class FakeOnlineConnectivityObserver : ConnectivityObserver {
    override val isOnline: Flow<Boolean> = flowOf(true)
}

/** No-op fake — queueing itself is covered by `ChatRepositoryTest`. */
private class NoopPendingLogQueue : PendingLogQueue {
    override suspend fun enqueue(
        clientRequestId: String,
        payloadJson: String,
    ) = Unit
}

/** In-memory [DroppedLogStore] fake, defaulting to "nothing dropped". */
private class FakeDroppedLogStore(private var count: Int = 0) : DroppedLogStore {
    override suspend fun markDropped() {
        count++
    }

    override suspend fun consumeDropped(): Int {
        val was = count
        count = 0
        return was
    }
}

/**
 * These drive [ChatViewModel] against a real [MockWebServer] rather than a
 * fake repository, mirroring [app.mealsy.data.repo.ChatRepositoryTest] and
 * [app.mealsy.data.api.MealsyApiTest]. `viewModelScope` is backed by
 * [Dispatchers.Unconfined] (a real dispatcher, not a virtual-time
 * [kotlinx.coroutines.test.TestDispatcher]) — mixing MockWebServer's genuine
 * async I/O with a `StandardTestDispatcher`'s `advanceUntilIdle()` races,
 * since the network response arrives on a real OkHttp thread the virtual
 * scheduler doesn't know to wait for. [ChatViewModel.send]/`confirm`/`cancel`
 * return their launched [kotlinx.coroutines.Job] for exactly this reason:
 * tests `join()` it instead of guessing when the coroutine is done.
 *
 * The card is now an inline [ChatMsg.Card] in [ChatViewModel.messages]
 * rather than a separate `pendingCard` flow — `activeCardOf` pulls the
 * newest one back out for assertions.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class ChatViewModelTest {
    private lateinit var server: MockWebServer
    private val json =
        Json {
            ignoreUnknownKeys = true
            explicitNulls = false
        }
    private val fixedClock = Clock.fixed(Instant.parse("2026-09-16T12:00:00Z"), ZoneOffset.UTC)

    @Before
    fun setUp() {
        Dispatchers.setMain(Dispatchers.Unconfined)
        server = MockWebServer()
        server.start()
    }

    @After
    fun tearDown() {
        server.shutdown()
        Dispatchers.resetMain()
    }

    private fun buildApi(): MealsyApi {
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
        return retrofit.create(MealsyApi::class.java)
    }

    private fun buildViewModel(droppedLogStore: DroppedLogStore = FakeDroppedLogStore()): ChatViewModel {
        val api = buildApi()
        val todayRefreshSignal = app.mealsy.data.repo.TodayRefreshSignal()
        val repository =
            ChatRepository(
                api,
                fakeConversationIdStore(),
                NoopPendingLogQueue(),
                json,
                todayRefreshSignal,
            )
        return ChatViewModel(
            repository,
            FakeOnlineConnectivityObserver(),
            app.mealsy.data.repo.MyMealsRepository(api, todayRefreshSignal),
            droppedLogStore,
            fixedClock,
        )
    }

    private fun activeCardOf(viewModel: ChatViewModel): ChatMsg.Card? =
        viewModel.messages.value.lastOrNull { it is ChatMsg.Card } as? ChatMsg.Card

    /** No pending card — the common "nothing to restore" startup. */
    private fun enqueueEmptyStartup() {
        server.enqueue(MockResponse().setResponseCode(200).setBody(EMPTY_PENDING_BODY))
    }

    @Test
    fun `send appends user bubble then card`() =
        runBlocking {
            enqueueEmptyStartup()
            server.enqueue(MockResponse().setResponseCode(200).setBody(PAUSED_CARD_BODY))
            val viewModel = buildViewModel()
            viewModel.readyJob.join()

            assertEquals(emptyList<ChatMsg>(), viewModel.messages.value)

            viewModel.send("two eggs").join()

            val messages = viewModel.messages.value
            assertEquals(2, messages.size)
            assertTrue(messages[0] is ChatMsg.User)
            assertEquals("two eggs", (messages[0] as ChatMsg.User).text)
            val card = activeCardOf(viewModel)
            assertTrue(card != null)
            assertTrue(card?.state is CardState.Active)
            assertEquals(1, card?.card?.items?.size)
        }

    @Test
    fun `edit qty updates totals via CardEditor`() =
        runBlocking {
            enqueueEmptyStartup()
            server.enqueue(MockResponse().setResponseCode(200).setBody(PAUSED_CARD_BODY))
            val viewModel = buildViewModel()
            viewModel.readyJob.join()
            viewModel.send("two eggs").join()

            viewModel.editQty(0, 150.0)

            val card = activeCardOf(viewModel)?.card
            assertEquals(150.0, card?.items?.get(0)?.targetQtyG)
        }

    @Test
    fun `removing the last item drops the card locally with no repository call`() =
        runBlocking {
            enqueueEmptyStartup()
            server.enqueue(MockResponse().setResponseCode(200).setBody(PAUSED_CARD_BODY))
            val viewModel = buildViewModel()
            viewModel.readyJob.join()
            viewModel.send("an egg").join()
            assertEquals(1, activeCardOf(viewModel)?.card?.items?.size)

            // Only two responses were ever enqueued (startup + the card turn) —
            // a third request here would throw from an empty MockWebServer queue,
            // proving no network call was made.
            viewModel.removeItem(0)

            assertNull(activeCardOf(viewModel))
        }

    @Test
    @Suppress("ktlint:standard:max-line-length")
    fun `confirm collapses the card to Logged with label and kcal, and appends a coach reply`() =
        runBlocking {
            enqueueEmptyStartup()
            server.enqueue(MockResponse().setResponseCode(200).setBody(PAUSED_CARD_BODY))
            server.enqueue(
                MockResponse().setResponseCode(200).setBody(
                    """{"meal_id":"m_1","meal_type":"breakfast","n_items":1,"kcal":155.0,"protein_g":13.0,"carbs_g":1.1,"fat_g":11.0,"fiber_g":0.0,"message":"Logged breakfast.","deduplicated":false}""",
                ),
            )
            val viewModel = buildViewModel()
            viewModel.readyJob.join()
            viewModel.send("an egg").join()

            viewModel.confirm()?.join()

            val card = activeCardOf(viewModel)
            assertTrue(card?.state is CardState.Logged)
            val logged = card?.state as CardState.Logged
            assertEquals("Egg", logged.label)
            assertEquals(155, logged.kcal)
            assertFalse(viewModel.sending.value)
            val messages = viewModel.messages.value
            assertTrue(messages.any { it is ChatMsg.Coach && it.text == "Logged breakfast." })
            val coachMsg = messages.first { it is ChatMsg.Coach } as ChatMsg.Coach
            assertEquals(2, coachMsg.tags.size)
        }

    @Test
    fun `cancel stamps the card Discarded on success`() =
        runBlocking {
            enqueueEmptyStartup()
            server.enqueue(MockResponse().setResponseCode(200).setBody(PAUSED_CARD_BODY))
            server.enqueue(MockResponse().setResponseCode(200).setBody(EMPTY_PENDING_BODY))
            val viewModel = buildViewModel()
            viewModel.readyJob.join()
            viewModel.send("an egg").join()

            viewModel.cancel()?.join()

            val card = activeCardOf(viewModel)
            assertTrue(card?.state is CardState.Discarded)
        }

    @Test
    fun `a new card supersedes the previous still-active one as NotLogged`() =
        runBlocking {
            enqueueEmptyStartup()
            server.enqueue(MockResponse().setResponseCode(200).setBody(PAUSED_CARD_BODY))
            server.enqueue(MockResponse().setResponseCode(200).setBody(PAUSED_CARD_BODY))
            val viewModel = buildViewModel()
            viewModel.readyJob.join()
            viewModel.send("an egg").join()
            viewModel.send("another egg").join()

            val cards = viewModel.messages.value.filterIsInstance<ChatMsg.Card>()
            assertEquals(2, cards.size)
            assertTrue(cards[0].state is CardState.NotLogged)
            assertTrue(cards[1].state is CardState.Active)
        }

    @Test
    @Suppress("ktlint:standard:max-line-length")
    fun `saveAsMyMeal posts to my-meals and emits a success toast`() =
        runBlocking {
            enqueueEmptyStartup()
            server.enqueue(MockResponse().setResponseCode(200).setBody(PAUSED_CARD_BODY))
            server.enqueue(
                MockResponse().setResponseCode(201).setBody(
                    """{"id":"meal_1","name":"My eggs","kcal":155.0,"protein_g":13.0,"carbs_g":1.1,"fat_g":11.0,"fiber_g":0.0,"n_ingredients":1,"logged_today":false}""",
                ),
            )
            val viewModel = buildViewModel()
            viewModel.readyJob.join()
            viewModel.send("an egg").join()

            // Started UNDISPATCHED (not GlobalScope+Unconfined): this runs
            // synchronously on the calling thread up to its first suspension
            // point, which is `collect`'s subscription itself — so the
            // collector is guaranteed registered before onSaveAsMyMeal's
            // tryEmit below, rather than racing a merely-scheduled launch
            // against it. `_toasts` is a `replay = 0` SharedFlow: tryEmit
            // silently drops the value for any collector not yet subscribed.
            val toasts = mutableListOf<String>()
            val collectJob =
                launch(start = CoroutineStart.UNDISPATCHED) {
                    viewModel.toasts.collect { toasts.add(it) }
                }
            viewModel.onSaveAsMyMeal("My eggs")?.join()
            collectJob.cancel()

            assertFalse(viewModel.savingMeal.value)
            assertTrue(toasts.any { it.contains("Saved") })
        }

    @Test
    fun `saveAsMyMeal emits a duplicate-name toast on 409`() =
        runBlocking {
            enqueueEmptyStartup()
            server.enqueue(MockResponse().setResponseCode(200).setBody(PAUSED_CARD_BODY))
            server.enqueue(MockResponse().setResponseCode(409))
            val viewModel = buildViewModel()
            viewModel.readyJob.join()
            viewModel.send("an egg").join()

            // See the UNDISPATCHED comment above — same subscription-race fix.
            val toasts = mutableListOf<String>()
            val collectJob =
                launch(start = CoroutineStart.UNDISPATCHED) {
                    viewModel.toasts.collect { toasts.add(it) }
                }
            viewModel.onSaveAsMyMeal("My eggs")?.join()
            collectJob.cancel()

            assertTrue(toasts.any { it == "You already have a meal with that name." })
        }

    @Test
    fun `submitFeedback is a no-op when the message has no responseId`() =
        runBlocking {
            enqueueEmptyStartup()
            val viewModel = buildViewModel()
            viewModel.readyJob.join()
            // No coach message exists yet, but the no-op check happens before any
            // lookup could matter — this documents that a message with a null
            // responseId is never round-tripped to the repository.
            val job = viewModel.submitFeedback("nonexistent", 1)
            assertNull(job)
        }

    @Test
    fun `429 error appends a slow-down message and does not mark offline`() =
        runBlocking {
            enqueueEmptyStartup()
            server.enqueue(MockResponse().setResponseCode(429))
            val viewModel = buildViewModel()
            viewModel.readyJob.join()

            viewModel.send("two eggs").join()

            assertFalse(viewModel.offline.value)
            val messages = viewModel.messages.value
            assertTrue(messages.any { it is ChatMsg.Coach && it.text.contains("Slow down") })
        }

    @Test
    fun `cancel keeps the card in place when the network call fails`() =
        runBlocking {
            enqueueEmptyStartup()
            server.enqueue(MockResponse().setResponseCode(200).setBody(PAUSED_CARD_BODY))
            server.enqueue(MockResponse().setResponseCode(500))
            val viewModel = buildViewModel()
            viewModel.readyJob.join()
            viewModel.send("an egg").join()
            assertTrue(activeCardOf(viewModel) != null)

            viewModel.cancel()?.join()

            val card = activeCardOf(viewModel)
            assertTrue(card?.state is CardState.Active)
            assertFalse(viewModel.sending.value)
        }

    @Test
    fun `init restores a pending card inline as Active`() =
        runBlocking {
            server.enqueue(MockResponse().setResponseCode(200).setBody(PAUSED_CARD_BODY))

            val viewModel = buildViewModel()
            viewModel.readyJob.join()

            val card = activeCardOf(viewModel)
            assertTrue(card != null)
            assertTrue(card?.state is CardState.Active)
            assertEquals(1, card?.card?.items?.size)
        }

    @Test
    fun `a dropped queued log surfaces a one-time notice on init`() =
        runBlocking {
            enqueueEmptyStartup()
            val droppedLogStore = FakeDroppedLogStore(count = 1)
            val viewModel = buildViewModel(droppedLogStore)

            viewModel.readyJob.join()

            val messages = viewModel.messages.value
            assertTrue(
                messages.any {
                    it is ChatMsg.Coach &&
                        it.text == "A queued meal from earlier couldn't be synced and was dropped."
                },
            )
            // consumeDropped clears the counter — a second ChatViewModel (e.g. a
            // later process start) must not re-surface the same notice.
            assertEquals(0, droppedLogStore.consumeDropped())
        }

    @Test
    fun `multiple dropped queued logs surface a pluralized notice`() =
        runBlocking {
            enqueueEmptyStartup()
            val viewModel = buildViewModel(FakeDroppedLogStore(count = 2))

            viewModel.readyJob.join()

            val messages = viewModel.messages.value
            assertTrue(
                messages.any {
                    it is ChatMsg.Coach &&
                        it.text == "2 queued meals couldn't be synced and were dropped."
                },
            )
        }

    @Test
    fun `nothing dropped means no notice on init`() =
        runBlocking {
            enqueueEmptyStartup()
            val viewModel = buildViewModel(FakeDroppedLogStore(count = 0))

            viewModel.readyJob.join()

            assertTrue(viewModel.messages.value.none { it is ChatMsg.Coach })
        }

    private companion object {
        const val EMPTY_PENDING_BODY = """{"status":"success","message":"","paused":false,"items":[]}"""
        const val PAUSED_CARD_BODY = """
            {
              "status": "confirm",
              "message": "Got it — 1 egg. Log as breakfast?",
              "paused": true,
              "items": [
                {"food_name": "egg", "qty_g": 100, "kcal": 155, "protein_g": 13, "carbs_g": 1.1, "fat_g": 11, "fiber_g": 0, "fdc_id": 12345}
              ]
            }
        """
    }
}
