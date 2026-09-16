package app.mealsy.data.repo

import app.mealsy.data.api.AuthInterceptor
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.TokenProvider
import app.mealsy.domain.CardItem
import app.mealsy.domain.ConfirmationCard
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.coroutines.yield
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Retrofit
import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory

/**
 * MockWebServer-backed tests for [MyMealsRepository], golden JSON hand-copied
 * from `src/backend/api/my_meals.py` / `docs/reference/mobile-api.md`'s
 * `/my-meals` section.
 */
class MyMealsRepositoryTest {

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

    private fun buildRepository(
        todayRefreshSignal: TodayRefreshSignal = TodayRefreshSignal(),
    ): MyMealsRepository {
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
        return MyMealsRepository(api, todayRefreshSignal)
    }

    private val listGoldenJson = """
        [
          {
            "id": "meal_1",
            "name": "Usual breakfast",
            "kcal": 450.0,
            "protein_g": 28.0,
            "carbs_g": 40.0,
            "fat_g": 18.0,
            "fiber_g": 6.0,
            "n_ingredients": 3,
            "logged_today": false
          }
        ]
    """.trimIndent()

    @Test
    fun `list maps the backend's bare array`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody(listGoldenJson))

        val result = buildRepository().list()

        assertEquals(1, result.size)
        assertEquals("meal_1", result[0].id)
        assertEquals("Usual breakfast", result[0].name)
        assertEquals(450.0, result[0].kcal, 0.0)
        assertEquals(3, result[0].nIngredients)
        assertFalse(result[0].loggedToday)

        val request = server.takeRequest()
        assertEquals("GET", request.method)
        assertEquals("/my-meals", request.path)
    }

    @Test
    fun `empty array maps to an empty list, not an error`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(200).setBody("[]"))

        val result = buildRepository().list()

        assertTrue(result.isEmpty())
    }

    private fun sampleCard() = ConfirmationCard(
        message = "Logged",
        items = listOf(
            CardItem(
                foodName = "egg",
                qtyG = 100.0,
                targetQtyG = 150.0,
                kcal = 155.0,
                proteinG = 13.0,
                carbsG = 1.1,
                fatG = 11.0,
                fiberG = 0.0,
                fdcId = 12345,
                estimated = false,
                extras = JsonObject(emptyMap()),
            ),
        ),
        mealType = "breakfast",
        portion = 2.0,
    )

    @Test
    fun `save posts scaled ingredients and the given name`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(201).setBody(
                """
                {
                  "id": "meal_1",
                  "name": "My eggs",
                  "kcal": 465.0,
                  "protein_g": 39.0,
                  "carbs_g": 3.3,
                  "fat_g": 33.0,
                  "fiber_g": 0.0,
                  "n_ingredients": 1,
                  "logged_today": false
                }
                """.trimIndent(),
            ),
        )

        buildRepository().save(sampleCard(), "My eggs")

        val request = server.takeRequest()
        assertEquals("POST", request.method)
        assertEquals("/my-meals", request.path)
        val body = request.body.readUtf8()
        assertTrue(body.contains("\"name\":\"My eggs\""))
        assertTrue(body.contains("\"food_name\":\"egg\""))
        // factor = (150/100) * 2 = 3 -> qty_g = 150 * 2 = 300, kcal = 155 * 3 = 465
        assertTrue(body.contains("\"qty_g\":300.0"))
        assertTrue(body.contains("\"kcal\":465.0"))
        assertTrue(body.contains("\"protein_g\":39.0"))
        assertFalse(body.contains("target_qty_g"))
        assertTrue(body.contains("\"fdc_id\":12345"))
    }

    @Test(expected = HttpException::class)
    fun `save propagates a 409 duplicate-name conflict`(): Unit = runBlocking {
        server.enqueue(MockResponse().setResponseCode(409).setBody("""{"detail":"duplicate"}"""))

        buildRepository().save(sampleCard(), "My eggs")
    }

    @Test
    fun `quickLog posts meal_type with no ingredients field`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """
                {
                  "meal_id": "log_1",
                  "meal_type": "lunch",
                  "n_items": 1,
                  "kcal": 465.0,
                  "protein_g": 39.0,
                  "carbs_g": 3.3,
                  "fat_g": 33.0,
                  "fiber_g": 0.0,
                  "message": "Logged"
                }
                """.trimIndent(),
            ),
        )

        val signal = TodayRefreshSignal()
        val emitted = async { withTimeoutOrNull(1_000) { signal.events.first() } }
        yield() // let the collector above subscribe before the emit fires
        buildRepository(signal).quickLog("meal_1", "lunch")

        val request = server.takeRequest()
        assertEquals("POST", request.method)
        assertEquals("/my-meals/meal_1/log", request.path)
        val body = request.body.readUtf8()
        assertTrue(body.contains("\"meal_type\":\"lunch\""))
        assertFalse(body.contains("ingredients"))
        assertEquals(Unit, emitted.await())
    }

    @Test
    fun `logCustomized posts kept ingredient overrides by index`() = runBlocking {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """
                {
                  "meal_id": "log_1",
                  "meal_type": "dinner",
                  "n_items": 1,
                  "kcal": 200.0,
                  "protein_g": 10.0,
                  "carbs_g": 5.0,
                  "fat_g": 8.0,
                  "fiber_g": 1.0,
                  "message": "Logged"
                }
                """.trimIndent(),
            ),
        )

        val signal = TodayRefreshSignal()
        val emitted = async { withTimeoutOrNull(1_000) { signal.events.first() } }
        yield() // let the collector above subscribe before the emit fires
        buildRepository(signal).logCustomized(
            "meal_1",
            "dinner",
            overrides = listOf(SavedMealOverride(index = 0, qtyG = 120.0)),
            portion = 1.5,
        )

        val request = server.takeRequest()
        val body = request.body.readUtf8()
        assertTrue(body.contains("\"meal_type\":\"dinner\""))
        assertTrue(body.contains("\"portion\":1.5"))
        assertTrue(body.contains("\"index\":0"))
        assertTrue(body.contains("\"qty_g\":120.0"))
        assertEquals(Unit, emitted.await())
    }

    @Test
    fun `delete sends DELETE to my-meals slash id`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(204))

        buildRepository().delete("meal_1")

        val request = server.takeRequest()
        assertEquals("DELETE", request.method)
        assertEquals("/my-meals/meal_1", request.path)
    }
}
