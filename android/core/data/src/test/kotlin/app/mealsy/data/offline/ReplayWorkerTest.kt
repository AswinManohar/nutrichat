package app.mealsy.data.offline

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.work.ListenableWorker
import androidx.work.WorkerFactory
import androidx.work.WorkerParameters
import androidx.work.testing.TestListenableWorkerBuilder
import app.mealsy.data.api.AuthInterceptor
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.TokenProvider
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
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import retrofit2.Retrofit
import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory

/**
 * [ReplayWorker] against a real [MockWebServer] response and a [FakePendingLogDao]
 * — Robolectric supplies the [Context] TestListenableWorkerBuilder needs.
 */
@RunWith(RobolectricTestRunner::class)
class ReplayWorkerTest {

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

    private fun buildWorker(dao: PendingLogDao, api: MealsyApi): ReplayWorker {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val worker = TestListenableWorkerBuilder<ReplayWorker>(context)
            .setWorkerFactory(
                object : WorkerFactory() {
                    override fun createWorker(
                        appContext: Context,
                        workerClassName: String,
                        workerParameters: WorkerParameters,
                    ): ListenableWorker = ReplayWorker(appContext, workerParameters, dao, api, json)
                },
            )
            .build()
        return worker as ReplayWorker
    }

    private fun sampleRow(clientRequestId: String = "req-1"): PendingLogEntity = PendingLogEntity(
        clientRequestId = clientRequestId,
        payloadJson = json.encodeToString(
            app.mealsy.data.api.LogItemsRequest.serializer(),
            app.mealsy.data.api.LogItemsRequest(
                mealType = "breakfast",
                portion = 1.0,
                items = listOf(
                    app.mealsy.data.api.ItemDto(
                        foodName = "egg", qtyG = 100.0, kcal = 155.0, proteinG = 13.0,
                        carbsG = 1.1, fatG = 11.0, fiberG = 0.0, fdcId = 12345,
                    ),
                ),
                clientRequestId = clientRequestId,
            ),
        ),
        createdAt = System.currentTimeMillis(),
    )

    @Test
    fun `success deletes row`() {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"meal_id":"m_1","meal_type":"breakfast","n_items":1,"kcal":155.0,"protein_g":13.0,"carbs_g":1.1,"fat_g":11.0,"fiber_g":0.0,"message":"Logged.","deduplicated":false}""",
            ),
        )
        val dao = FakePendingLogDao().apply { seed(sampleRow()) }
        val worker = buildWorker(dao, buildApi())

        val result = worker.startWork().get()

        assertEquals(ListenableWorker.Result.success(), result)
        assertTrue(runBlockingGetAll(dao).isEmpty())
    }

    @Test
    fun `deduplicated response deletes row`() {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"meal_id":"m_1","meal_type":"breakfast","n_items":1,"kcal":155.0,"protein_g":13.0,"carbs_g":1.1,"fat_g":11.0,"fiber_g":0.0,"message":"Already logged.","deduplicated":true}""",
            ),
        )
        val dao = FakePendingLogDao().apply { seed(sampleRow()) }
        val worker = buildWorker(dao, buildApi())

        val result = worker.startWork().get()

        assertEquals(ListenableWorker.Result.success(), result)
        assertTrue(runBlockingGetAll(dao).isEmpty())
    }

    @Test
    fun `HTTP 500 keeps row (Result retry)`() {
        server.enqueue(MockResponse().setResponseCode(500))
        val dao = FakePendingLogDao().apply { seed(sampleRow()) }
        val worker = buildWorker(dao, buildApi())

        val result = worker.startWork().get()

        assertEquals(ListenableWorker.Result.retry(), result)
        assertEquals(1, runBlockingGetAll(dao).size)
        assertEquals(1, runBlockingGetAll(dao).single().attempts)
    }

    @Test
    fun `422 deletes row and does not retry`() {
        server.enqueue(MockResponse().setResponseCode(422))
        val dao = FakePendingLogDao().apply { seed(sampleRow()) }
        val worker = buildWorker(dao, buildApi())

        val result = worker.startWork().get()

        assertEquals(ListenableWorker.Result.success(), result)
        assertTrue(runBlockingGetAll(dao).isEmpty())
    }

    @Test
    fun `row past max attempts is given up on without another network call`() {
        val dao = FakePendingLogDao().apply {
            seed(sampleRow().copy(attempts = ReplayWorker.MAX_ATTEMPTS))
        }
        val worker = buildWorker(dao, buildApi())

        val result = worker.startWork().get()

        assertEquals(ListenableWorker.Result.success(), result)
        assertTrue(runBlockingGetAll(dao).isEmpty())
        assertEquals(0, server.requestCount)
    }

    @Test
    fun `row older than max age is given up on without another network call`() {
        val dao = FakePendingLogDao().apply {
            seed(
                sampleRow().copy(
                    createdAt = System.currentTimeMillis() - ReplayWorker.MAX_AGE_MS - 1_000,
                ),
            )
        }
        val worker = buildWorker(dao, buildApi())

        val result = worker.startWork().get()

        assertEquals(ListenableWorker.Result.success(), result)
        assertTrue(runBlockingGetAll(dao).isEmpty())
        assertEquals(0, server.requestCount)
    }

    /**
     * A [PendingLogDao] wrapper that inserts a second row into [underlying]
     * right after its first [getAll] snapshot is taken (but before that
     * snapshot is returned to the caller) — modeling a `confirmCard()` that
     * queues a new row while a replay run is already past its first
     * `dao.getAll()`. With `ExistingWorkPolicy.KEEP`, that race means no
     * follow-up run is guaranteed, so [ReplayWorker.doWork] must re-query
     * and pick the new row up within the SAME run.
     */
    private class RacyPendingLogDao(
        private val underlying: FakePendingLogDao,
        private val onFirstSnapshot: () -> Unit,
    ) : PendingLogDao {
        private var getAllCalls = 0

        override suspend fun insert(entity: PendingLogEntity) = underlying.insert(entity)
        override suspend fun delete(clientRequestId: String) = underlying.delete(clientRequestId)
        override suspend fun incrementAttempts(clientRequestId: String) =
            underlying.incrementAttempts(clientRequestId)

        override suspend fun getAll(): List<PendingLogEntity> {
            getAllCalls++
            val snapshot = underlying.getAll()
            if (getAllCalls == 1) onFirstSnapshot()
            return snapshot
        }
    }

    @Test
    fun `row queued mid-run (past the first getAll) is still processed in the same run`() {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"meal_id":"m_1","meal_type":"breakfast","n_items":1,"kcal":155.0,"protein_g":13.0,"carbs_g":1.1,"fat_g":11.0,"fiber_g":0.0,"message":"Logged.","deduplicated":false}""",
            ),
        )
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"meal_id":"m_2","meal_type":"breakfast","n_items":1,"kcal":155.0,"protein_g":13.0,"carbs_g":1.1,"fat_g":11.0,"fiber_g":0.0,"message":"Logged.","deduplicated":false}""",
            ),
        )
        val underlying = FakePendingLogDao().apply { seed(sampleRow("req-1")) }
        val dao = RacyPendingLogDao(underlying) { underlying.seed(sampleRow("req-2")) }
        val worker = buildWorker(dao, buildApi())

        val result = worker.startWork().get()

        assertEquals(ListenableWorker.Result.success(), result)
        assertTrue(runBlockingGetAll(underlying).isEmpty())
        assertEquals(2, server.requestCount)
    }

    private fun runBlockingGetAll(dao: FakePendingLogDao): List<PendingLogEntity> =
        kotlinx.coroutines.runBlocking { dao.getAll() }
}
