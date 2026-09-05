package app.mealsy.android.ui.chat

import app.mealsy.android.util.ConnectivityObserver
import app.mealsy.data.api.AuthInterceptor
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.TokenProvider
import app.mealsy.data.offline.PendingLogQueue
import app.mealsy.data.repo.ChatRepository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import retrofit2.Retrofit
import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory

/** [ChatViewModel.offline] driven purely by [ConnectivityObserver], independent of any failed call. */
@OptIn(ExperimentalCoroutinesApi::class)
class ConnectivityOfflineTest {

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

    private class FakeConnectivityObserver(initial: Boolean) : ConnectivityObserver {
        val state = MutableStateFlow(initial)
        override val isOnline: Flow<Boolean> = state
    }

    private class NoopPendingLogQueue : PendingLogQueue {
        override suspend fun enqueue(clientRequestId: String, payloadJson: String) = Unit
    }

    @Test
    fun `losing connectivity sets the offline banner without any failed request`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody(EMPTY_PENDING_BODY))
        server.enqueue(MockResponse().setResponseCode(200).setBody(TODAY_BODY))
        server.enqueue(MockResponse().setResponseCode(200).setBody(GOALS_BODY))

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
        val repository = ChatRepository(api, fakeConversationIdStore(), NoopPendingLogQueue(), json)
        val connectivity = FakeConnectivityObserver(initial = true)
        val viewModel = ChatViewModel(repository, api, connectivity)
        viewModel.readyJob.join()

        assertTrue(!viewModel.offline.value)

        connectivity.state.value = false

        assertTrue(viewModel.offline.value)
    }

    @Test
    fun `connectivity restored clears the offline banner (no request needed to unstick it)`() =
        runBlocking {
            server.enqueue(MockResponse().setResponseCode(200).setBody(EMPTY_PENDING_BODY))
            server.enqueue(MockResponse().setResponseCode(200).setBody(TODAY_BODY))
            server.enqueue(MockResponse().setResponseCode(200).setBody(GOALS_BODY))

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
            val repository =
                ChatRepository(api, fakeConversationIdStore(), NoopPendingLogQueue(), json)
            val connectivity = FakeConnectivityObserver(initial = true)
            val viewModel = ChatViewModel(repository, api, connectivity)
            viewModel.readyJob.join()
            assertTrue(!viewModel.offline.value)

            // Connectivity lost — no pending card, so (before the fix) there
            // would be no other network call left that could ever clear this.
            connectivity.state.value = false
            assertTrue(viewModel.offline.value)

            // Connectivity restored — must clear on its own, without needing
            // a send/confirm/cancel to succeed first.
            connectivity.state.value = true
            assertTrue(!viewModel.offline.value)
        }

    private companion object {
        const val EMPTY_PENDING_BODY = """{"status":"success","message":"","paused":false,"items":[]}"""
        const val TODAY_BODY =
            """{"kcal":800.0,"protein_g":40.0,"fiber_g":10.0,"n_meals":1,"by_type":[]}"""
        const val GOALS_BODY =
            """{"tracking_mode":"goals","kcal_goal":2200.0,"protein_goal":140.0,"fiber_goal":30.0,"dietary_prefs":{},"streak_days":0}"""
    }
}
