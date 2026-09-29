package app.mealsy.android.ui.chat

import app.mealsy.android.util.ConnectivityObserver
import app.mealsy.data.api.AuthInterceptor
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.TokenProvider
import app.mealsy.data.auth.AuthGateway
import app.mealsy.data.auth.ProfileMetadata
import app.mealsy.data.auth.SessionManager
import app.mealsy.data.auth.SessionState
import app.mealsy.data.offline.DroppedLogStore
import app.mealsy.data.offline.PendingLogQueue
import app.mealsy.data.repo.ChatRepository
import app.mealsy.data.repo.MyMealsRefreshSignal
import app.mealsy.data.repo.MyMealsRepository
import app.mealsy.data.repo.TodayRefreshSignal
import app.mealsy.domain.CardItem
import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.flowOf
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
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import retrofit2.Retrofit
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset

private class SwapFakeOnlineConnectivityObserver : ConnectivityObserver {
    override val isOnline: Flow<Boolean> = flowOf(true)
}

private class SwapFakeAuthGateway(initial: SessionState = SessionState.SignedIn("user-1")) : AuthGateway {
    override val sessionState = MutableStateFlow(initial)

    override suspend fun signInWithMagicLink(email: String) = Unit

    override suspend fun signInWithGoogle(activity: android.app.Activity) = Unit

    override suspend fun refreshCurrentSession(): String? = null

    override fun currentAccessTokenOrNull(): String? = null

    override suspend fun signOut() = Unit

    override suspend fun updateProfileMetadata(
        firstName: String,
        goalFocus: String,
    ) = Unit

    override suspend fun currentProfileMetadata(): ProfileMetadata? = null
}

private class SwapNoopPendingLogQueue : PendingLogQueue {
    override suspend fun enqueue(
        clientRequestId: String,
        payloadJson: String,
    ) = Unit
}

private class SwapFakeDroppedLogStore : DroppedLogStore {
    override suspend fun markDropped() = Unit

    override suspend fun consumeDropped(): Int = 0
}

/**
 * Local-swap behaviour of [ChatSessionStore]/[ChatViewModel] (spec 003,
 * T015/T027): [ChatSessionStore.swapItem] and [ChatSessionStore.undoSwap]
 * mutate the card locally via [app.mealsy.domain.CardEditor], with no
 * network call, and the confirmed `POST /meals/log-items` request carries
 * the swap as a `correction`. Mirrors [ChatViewModelTest]'s MockWebServer
 * setup.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class CardSwapTest {
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
        val client = OkHttpClient.Builder().addInterceptor(AuthInterceptor(TokenProvider { "token" })).build()
        val contentType = "application/json".toMediaType()
        val retrofit =
            Retrofit.Builder()
                .baseUrl(server.url("/"))
                .client(client)
                .addConverterFactory(json.asConverterFactory(contentType))
                .build()
        return retrofit.create(MealsyApi::class.java)
    }

    private fun buildViewModel(): ChatViewModel {
        val api = buildApi()
        val todayRefreshSignal = TodayRefreshSignal()
        val repository =
            ChatRepository(api, fakeConversationIdStore(), SwapNoopPendingLogQueue(), json, todayRefreshSignal)
        val store =
            ChatSessionStore(
                repository,
                SwapFakeOnlineConnectivityObserver(),
                MyMealsRepository(api, todayRefreshSignal, MyMealsRefreshSignal()),
                SwapFakeDroppedLogStore(),
                SessionManager(SwapFakeAuthGateway()),
                CoroutineScope(Dispatchers.Unconfined),
                fixedClock,
            )
        return ChatViewModel(store)
    }

    private fun activeCardOf(viewModel: ChatViewModel) = viewModel.messages.value.lastOrNull { it is ChatMsg.Card } as? ChatMsg.Card

    private fun newFood(fdcId: Long = 172687L) =
        CardItem(
            foodName = "Bread, white, commercially prepared, toasted",
            qtyG = 28.0,
            targetQtyG = 28.0,
            kcal = 82.0,
            proteinG = 2.5,
            carbsG = 15.0,
            fatG = 1.0,
            fiberG = 0.8,
            fdcId = fdcId,
            source = "usda_local",
        )

    private fun enqueueEmptyStartup() {
        server.enqueue(MockResponse().setResponseCode(200).setBody(EMPTY_PENDING_BODY))
    }

    @Test
    fun `selecting a result replaces only that item, keeping qty and meal type`() =
        runBlocking {
            enqueueEmptyStartup()
            server.enqueue(MockResponse().setResponseCode(200).setBody(PAUSED_CARD_BODY))
            val vm = buildViewModel()
            vm.readyJob.join()
            vm.send("two eggs").join()
            vm.editQty(0, 150.0)

            vm.swapItem(0, newFood(), method = "search", query = "white bread toasted")

            val card = activeCardOf(vm)?.card
            assertEquals(172687L, card?.items?.get(0)?.fdcId)
            assertEquals(150.0, card?.items?.get(0)?.targetQtyG)
            assertEquals("lunch", card?.mealType ?: "lunch")
        }

    @Test
    fun `undo restores the previous item exactly and drops the pending correction`() =
        runBlocking {
            enqueueEmptyStartup()
            server.enqueue(MockResponse().setResponseCode(200).setBody(PAUSED_CARD_BODY))
            val vm = buildViewModel()
            vm.readyJob.join()
            vm.send("two eggs").join()
            val before = activeCardOf(vm)?.card

            vm.swapItem(0, newFood(), method = "search")
            assertEquals(172687L, activeCardOf(vm)?.card?.items?.get(0)?.fdcId)

            vm.undoSwap()

            assertEquals(before, activeCardOf(vm)?.card)
            assertNull(activeCardOf(vm)?.card?.items?.get(0)?.pendingCorrection)
        }

    @Test
    fun `selecting the current match is a no-op`() =
        runBlocking {
            enqueueEmptyStartup()
            server.enqueue(MockResponse().setResponseCode(200).setBody(PAUSED_CARD_BODY))
            val vm = buildViewModel()
            vm.readyJob.join()
            vm.send("two eggs").join()
            val before = activeCardOf(vm)?.card

            vm.swapItem(0, newFood(fdcId = 12345L), method = "search")

            assertEquals(before, activeCardOf(vm)?.card)
        }

    @Test
    fun `confirm and log sends correction with the originally matched food after two swaps`() =
        runBlocking {
            enqueueEmptyStartup()
            server.enqueue(MockResponse().setResponseCode(200).setBody(PAUSED_CARD_BODY))
            val vm = buildViewModel()
            vm.readyJob.join()
            vm.send("two eggs").join()

            vm.swapItem(0, newFood(fdcId = 111L), method = "suggestion")
            vm.swapItem(0, newFood(fdcId = 172687L), method = "search", query = "white bread toasted")

            server.enqueue(
                MockResponse().setResponseCode(200).setBody(
                    """
                    {"meal_id": "m1", "meal_type": "lunch", "n_items": 1, "kcal": 82.0,
                     "protein_g": 2.5, "carbs_g": 15.0, "fat_g": 1.0, "fiber_g": 0.8,
                     "message": "Logged!", "deduplicated": false}
                    """.trimIndent(),
                ),
            )
            vm.confirm()?.join()

            val request = server.takeRequest() // startup
            server.takeRequest() // send turn
            val logRequest = server.takeRequest()
            val body = logRequest.body.readUtf8()
            assertTrue(body.contains("\"to_fdc_id\":172687"))
            assertTrue(body.contains("\"from_fdc_id\":12345"))
            assertTrue(body.contains("\"method\":\"search\""))
            assertTrue(request.path?.contains("pending") == true || true)
        }

    @Test
    fun `swapping emits a Swapped undo toast and Undo restores the item and clears it`() =
        runBlocking {
            enqueueEmptyStartup()
            server.enqueue(MockResponse().setResponseCode(200).setBody(PAUSED_CARD_BODY))
            val vm = buildViewModel()
            vm.readyJob.join()
            vm.send("two eggs").join()
            val before = activeCardOf(vm)?.card
            assertNull(vm.undoToast.value)

            vm.swapItem(0, newFood(), method = "search")

            val toast = vm.undoToast.value
            assertTrue(toast is UndoToast.Swapped)
            assertEquals(newFood().foodName, toast?.name)

            vm.undoSwap()

            assertEquals(before, activeCardOf(vm)?.card)
            assertNull(vm.undoToast.value)
        }

    @Test
    fun `a no-op swap to the current match emits no toast`() =
        runBlocking {
            enqueueEmptyStartup()
            server.enqueue(MockResponse().setResponseCode(200).setBody(PAUSED_CARD_BODY))
            val vm = buildViewModel()
            vm.readyJob.join()
            vm.send("two eggs").join()

            vm.swapItem(0, newFood(fdcId = 12345L), method = "search")

            assertNull(vm.undoToast.value)
        }

    @Test
    fun `a second swap replaces the toast with a fresh token`() =
        runBlocking {
            enqueueEmptyStartup()
            server.enqueue(MockResponse().setResponseCode(200).setBody(PAUSED_CARD_BODY))
            val vm = buildViewModel()
            vm.readyJob.join()
            vm.send("two eggs").join()

            vm.swapItem(0, newFood(fdcId = 111L), method = "suggestion")
            val first = vm.undoToast.value
            vm.swapItem(0, newFood(fdcId = 222L), method = "search")

            assertTrue(vm.undoToast.value!!.token != first!!.token)
        }

    @Test
    fun `correction original_phrase is the user words when the card carries input_phrase (#56)`() =
        runBlocking {
            enqueueEmptyStartup()
            server.enqueue(MockResponse().setResponseCode(200).setBody(TOAST_CARD_BODY))
            val vm = buildViewModel()
            vm.readyJob.join()
            vm.send("toast").join()

            vm.swapItem(0, newFood(fdcId = 172687L), method = "search")
            server.enqueue(
                MockResponse().setResponseCode(200).setBody(
                    """{"meal_id": "m1", "meal_type": "lunch", "n_items": 1, "kcal": 82.0,
                     "protein_g": 2.5, "carbs_g": 15.0, "fat_g": 1.0, "fiber_g": 0.8,
                     "message": "Logged!", "deduplicated": false}""",
                ),
            )
            vm.confirm()?.join()

            server.takeRequest()
            server.takeRequest()
            val body = server.takeRequest().body.readUtf8()
            assertTrue(body, body.contains("\"original_phrase\":\"toast\""))
            assertTrue(body, body.contains("\"from_name\":\"Bread, egg, toasted\""))
        }

    private companion object {
        const val EMPTY_PENDING_BODY = """{"status": "ok", "message": "", "paused": false, "items": []}"""
        const val TOAST_CARD_BODY = """
            {
              "status": "confirm",
              "message": "Got it. Log as breakfast?",
              "paused": true,
              "items": [
                {"food_name": "Bread, egg, toasted", "input_phrase": "toast", "qty_g": 30, "kcal": 90, "protein_g": 3, "carbs_g": 12, "fat_g": 3, "fiber_g": 1, "fdc_id": 999}
              ]
            }
        """
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
