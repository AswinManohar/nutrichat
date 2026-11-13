package app.mealsy.data.repo

import app.mealsy.data.api.AuthInterceptor
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.TokenProvider
import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Retrofit

/** MockWebServer-backed tests for [ProfileRepository]. */
class ProfileRepositoryTest {
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

    private fun buildRepository(): ProfileRepository {
        val client = OkHttpClient.Builder().addInterceptor(AuthInterceptor(TokenProvider { "token" })).build()
        val retrofit =
            Retrofit.Builder()
                .baseUrl(server.url("/"))
                .client(client)
                .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
                .build()
        return ProfileRepository(retrofit.create(MealsyApi::class.java))
    }

    private fun ok(body: String) = MockResponse().setResponseCode(200).setBody(body)

    @Test
    fun `profile parses hard entries, care team and tolerates missing optional fields`() =
        runBlocking {
            server.enqueue(
                ok(
                    """
                    {"version":"v1","pending_count":1,"care_team":[{"name":"Dr Lee","role":"dietitian"}],
                     "hard":[{"id":"a","type":"allergy","label":"Peanut allergy","value":{"allergen_group":"peanut"},
                              "source":"patient","state":"pending","created_at":"2026-11-20T10:00:00Z",
                              "confirmed_at":null,"retire_requested":false},
                             {"id":"b","type":"diagnosis"}],
                     "soft":[],"missing_values":[],"future_field":1}
                    """.trimIndent(),
                ),
            )

            val profile = buildRepository().profile()

            assertEquals(2, profile.hard.size)
            assertEquals("pending", profile.hard[0].state)
            assertEquals("peanut", profile.hard[0].value["allergen_group"]?.jsonPrimitive?.content)
            assertEquals("confirmed", profile.hard[1].state)
            assertEquals("dietitian", profile.careTeam.single().role)
            assertEquals("/profile", server.takeRequest().path)
        }

    @Test
    fun `limitsToday parses progress`() =
        runBlocking {
            server.enqueue(
                ok(
                    """{"on_track":0,"total":1,"limits":[{"entry_id":"x","nutrient":"sodium",
                    "label":"Up to 1,500 mg a day","amount":1500,"min_amount":null,"unit":"mg",
                    "period":"per_day","so_far":1700,"unknown_items":1,"on_track":false}]}""",
                ),
            )

            val limits = buildRepository().limitsToday()

            assertEquals(1, limits.total)
            assertEquals(1700.0, limits.limits.single().soFar, 0.0)
            assertEquals(false, limits.limits.single().onTrack)
        }

    @Test
    fun `503 becomes ProfileUnavailableException with the server text`() {
        server.enqueue(MockResponse().setResponseCode(503).setBody("""{"detail":"Try again in a moment."}"""))

        val exc = assertThrows(ProfileUnavailableException::class.java) { runBlocking { buildRepository().profile() } }

        assertEquals("Try again in a moment.", exc.message)
    }

    @Test
    fun `other errors propagate`() {
        server.enqueue(MockResponse().setResponseCode(500))

        assertThrows(HttpException::class.java) { runBlocking { buildRepository().limitsToday() } }
    }

    @Test
    fun `saveEntry posts snake_case body with replaces_id for an edit`() =
        runBlocking {
            server.enqueue(ok("""{"id":"n","type":"medication"}"""))
            val value = buildJsonObject { put("name", JsonPrimitive("Warfarin")) }

            buildRepository().saveEntry("medication", value, null, "req-1", replacesId = "old")

            val body = Json.parseToJsonElement(server.takeRequest().body.readUtf8()).jsonObject
            assertEquals("medication", body["type"]?.jsonPrimitive?.content)
            assertEquals("req-1", body["client_request_id"]?.jsonPrimitive?.content)
            assertEquals("old", body["replaces_id"]?.jsonPrimitive?.content)
            assertEquals("Warfarin", body["value"]?.jsonObject?.get("name")?.jsonPrimitive?.content)
            assertTrue("label" !in body)
        }

    @Test
    fun `retire always sends confirm true`() =
        runBlocking {
            server.enqueue(ok("""{"id":"n","type":"allergy"}"""))

            buildRepository().retire("n", "req-2")

            val request = server.takeRequest()
            assertEquals("/profile/entries/n/retire", request.path)
            val body = Json.parseToJsonElement(request.body.readUtf8()).jsonObject
            assertEquals("true", body["confirm"]?.jsonPrimitive?.content)
        }

    @Test
    fun `soft facts parse dates and edit and delete hit the soft routes`() =
        runBlocking {
            server.enqueue(
                ok(
                    """{"soft":[{"id":"s1","kind":"dislike","text":"coriander","source":"stated",
                    "created_at":"2026-11-02T10:00:00Z","updated_at":"2026-11-03T10:00:00Z"}]}""",
                ),
            )
            server.enqueue(ok("""{"id":"s1","kind":"like","text":"cilantro"}"""))
            server.enqueue(MockResponse().setResponseCode(204))
            val repository = buildRepository()

            val fact = repository.profile().soft.single()
            repository.editSoftFact("s1", "cilantro", "like")
            repository.deleteSoftFact("s1")

            assertEquals("2026-11-02T10:00:00Z", fact.createdAt)
            server.takeRequest()
            val patch = server.takeRequest()
            assertEquals("PATCH", patch.method)
            assertEquals("/profile/soft/s1", patch.path)
            val body = Json.parseToJsonElement(patch.body.readUtf8()).jsonObject
            assertEquals("cilantro", body["text"]?.jsonPrimitive?.content)
            assertEquals("like", body["kind"]?.jsonPrimitive?.content)
            val delete = server.takeRequest()
            assertEquals("DELETE", delete.method)
            assertEquals("/profile/soft/s1", delete.path)
        }

    @Test
    fun `meals asks for 21 days and export returns the raw text`() =
        runBlocking {
            server.enqueue(
                ok(
                    """{"days":21,"recommendations":[{"recommendation_id":"r1","name":"Oat bowl","status":"rejected",
                    "rejection_reason":"too bland","created_at":"2026-11-10T10:00:00Z"}],
                    "eaten":[{"label":"Lunch: rice","logged_at":"2026-11-10T12:00:00Z"}]}""",
                ),
            )
            server.enqueue(ok("""{"hard":[],"soft":[]}"""))
            val repository = buildRepository()

            val meals = repository.meals()
            val export = repository.export()

            assertEquals("/profile/meals?days=21", server.takeRequest().path)
            assertEquals("too bland", meals.recommendations.single().rejectionReason)
            assertEquals("Lunch: rice", meals.logged.single().label)
            assertEquals("/profile/export", server.takeRequest().path)
            assertEquals("""{"hard":[],"soft":[]}""", export)
        }
}
