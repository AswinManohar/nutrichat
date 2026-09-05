package app.mealsy.android.ui.chat

import app.mealsy.data.api.AuthInterceptor
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.TokenProvider
import app.mealsy.data.repo.ChatRepository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
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
import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory

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
 */
@OptIn(ExperimentalCoroutinesApi::class)
class ChatViewModelTest {

    private lateinit var server: MockWebServer
    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false }

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
        val client = OkHttpClient.Builder()
            .addInterceptor(AuthInterceptor(TokenProvider { "token" }))
            .build()
        val contentType = "application/json".toMediaType()
        val retrofit = Retrofit.Builder()
            .baseUrl(server.url("/"))
            .client(client)
            .addConverterFactory(json.asConverterFactory(contentType))
            .build()
        return retrofit.create(MealsyApi::class.java)
    }

    private fun buildViewModel(): ChatViewModel {
        val api = buildApi()
        return ChatViewModel(ChatRepository(api, fakeConversationIdStore()), api)
    }

    /** No pending card, empty today/goals — the common "nothing to restore" startup. */
    private fun enqueueEmptyStartup() {
        server.enqueue(MockResponse().setResponseCode(200).setBody(EMPTY_PENDING_BODY))
        server.enqueue(MockResponse().setResponseCode(200).setBody(TODAY_BODY))
        server.enqueue(MockResponse().setResponseCode(200).setBody(GOALS_BODY))
    }

    @Test
    fun `send appends user bubble then card`() = runBlocking {
        enqueueEmptyStartup()
        server.enqueue(MockResponse().setResponseCode(200).setBody(PAUSED_CARD_BODY))
        val viewModel = buildViewModel()
        viewModel.readyJob.join()

        assertEquals(emptyList<ChatMsg>(), viewModel.messages.value)

        viewModel.send("two eggs").join()

        val messages = viewModel.messages.value
        assertEquals(1, messages.size)
        assertTrue(messages[0] is ChatMsg.User)
        assertEquals("two eggs", (messages[0] as ChatMsg.User).text)
        assertTrue(viewModel.pendingCard.value != null)
        assertEquals(1, viewModel.pendingCard.value?.items?.size)
    }

    @Test
    fun `edit qty updates totals via CardEditor`() = runBlocking {
        enqueueEmptyStartup()
        server.enqueue(MockResponse().setResponseCode(200).setBody(PAUSED_CARD_BODY))
        val viewModel = buildViewModel()
        viewModel.readyJob.join()
        viewModel.send("two eggs").join()

        viewModel.editQty(0, 150.0)

        val card = viewModel.pendingCard.value
        assertEquals(150.0, card?.items?.get(0)?.targetQtyG)
    }

    @Test
    fun `confirm disables card and appends success message`() = runBlocking {
        enqueueEmptyStartup()
        server.enqueue(MockResponse().setResponseCode(200).setBody(PAUSED_CARD_BODY))
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"meal_id":"m_1","meal_type":"breakfast","n_items":1,"kcal":155.0,"protein_g":13.0,"carbs_g":1.1,"fat_g":11.0,"fiber_g":0.0,"message":"Logged breakfast.","deduplicated":false}""",
            ),
        )
        server.enqueue(MockResponse().setResponseCode(200).setBody(TODAY_BODY))
        server.enqueue(MockResponse().setResponseCode(200).setBody(GOALS_BODY))
        val viewModel = buildViewModel()
        viewModel.readyJob.join()
        viewModel.send("an egg").join()

        viewModel.confirm()?.join()

        assertNull(viewModel.pendingCard.value)
        assertFalse(viewModel.sending.value)
        val messages = viewModel.messages.value
        assertTrue(messages.any { it is ChatMsg.Assistant && it.text == "Logged breakfast." })
    }

    @Test
    fun `429 error appends a slow-down message and does not mark offline`() = runBlocking {
        enqueueEmptyStartup()
        server.enqueue(MockResponse().setResponseCode(429))
        val viewModel = buildViewModel()
        viewModel.readyJob.join()

        viewModel.send("two eggs").join()

        assertFalse(viewModel.offline.value)
        val messages = viewModel.messages.value
        assertTrue(messages.any { it is ChatMsg.Assistant && it.text.contains("Slow down") })
    }

    @Test
    fun `cancel keeps the card in place when the network call fails`() = runBlocking {
        enqueueEmptyStartup()
        server.enqueue(MockResponse().setResponseCode(200).setBody(PAUSED_CARD_BODY))
        server.enqueue(MockResponse().setResponseCode(500))
        val viewModel = buildViewModel()
        viewModel.readyJob.join()
        viewModel.send("an egg").join()
        assertTrue(viewModel.pendingCard.value != null)

        viewModel.cancel()?.join()

        assertTrue(viewModel.pendingCard.value != null)
        assertFalse(viewModel.sending.value)
    }

    @Test
    fun `init restores pending card`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody(PAUSED_CARD_BODY))
        server.enqueue(MockResponse().setResponseCode(200).setBody(TODAY_BODY))
        server.enqueue(MockResponse().setResponseCode(200).setBody(GOALS_BODY))

        val viewModel = buildViewModel()
        viewModel.readyJob.join()

        assertTrue(viewModel.pendingCard.value != null)
        assertEquals(1, viewModel.pendingCard.value?.items?.size)
    }

    private companion object {
        const val EMPTY_PENDING_BODY = """{"status":"success","message":"","paused":false,"items":[]}"""
        const val TODAY_BODY =
            """{"kcal":800.0,"protein_g":40.0,"fiber_g":10.0,"n_meals":1,"by_type":[]}"""
        const val GOALS_BODY =
            """{"tracking_mode":"goals","kcal_goal":2200.0,"protein_goal":140.0,"fiber_goal":30.0,"dietary_prefs":{},"streak_days":0}"""
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
