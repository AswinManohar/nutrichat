package app.mealsy.data.repo

import app.mealsy.data.api.MealsyApi
import app.mealsy.domain.MicroRange
import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test
import retrofit2.Retrofit

/** [NutrientsRepository] against MockWebServer, with bodies shaped like spec 008's contracts. */
class NutrientsRepositoryTest {
    private lateinit var server: MockWebServer
    private val requests = mutableListOf<String>()

    private val catalog =
        """
        {"version": 1,
         "groups": [{"id": "other", "name": "Other", "order": 3}],
         "micronutrient_tabs": [
           {"id": "electrolytes", "name": "Electrolytes", "keys": ["sodium", "potassium"]},
           {"id": "minerals", "name": "Minerals", "keys": ["iron", "retired_key"]}
         ],
         "nutrients": [
           {"key": "sodium", "name": "Sodium", "unit": "mg", "group": "other", "order": 4,
            "direction": "limit", "daily_value": 2300, "usda_only": false, "derived": null, "status": "active"},
           {"key": "potassium", "name": "Potassium", "unit": "mg", "group": "minerals", "order": 9,
            "direction": "target", "daily_value": 4700, "usda_only": false, "derived": null, "status": "active"},
           {"key": "iron", "name": "Iron", "unit": "mg", "group": "minerals", "order": 5,
            "direction": "target", "daily_value": 18, "usda_only": false, "derived": null, "status": "active"},
           {"key": "retired_key", "name": "Old", "unit": "mg", "group": "minerals", "order": 6,
            "direction": "target", "daily_value": 1, "usda_only": false, "derived": null, "status": "retired"}
         ]}
        """.trimIndent()

    private val daily =
        """
        {"from": "2026-11-04", "to": "2026-11-10", "days": [
          {"date": "2026-11-09", "logged": false, "n_meals": 0, "items": 0, "values": {}},
          {"date": "2026-11-10", "logged": true, "n_meals": 1, "items": 2,
           "values": {"sodium": {"total": 1150.0, "est": 0.0, "known": 2},
                      "iron": {"total": 9.0, "est": 3.0, "known": 2}},
           "meals": [{"meal_id": "m1", "meal_type": "lunch", "label": "Dal",
             "values": {"iron": {"total": 9.0, "est": 3.0, "known": 2}},
             "foods": [
               {"food_name": "Lentils, mature seeds, cooked", "values": {"iron": {"total": 6.0, "est": 0.0, "known": 1}}},
               {"food_name": "spinach", "values": {"iron": {"total": 3.0, "est": 3.0, "known": 1}}}
             ]}]}
        ]}
        """.trimIndent()

    @Before
    fun setUp() {
        server = MockWebServer()
        server.dispatcher =
            object : Dispatcher() {
                override fun dispatch(request: RecordedRequest): MockResponse {
                    val path = request.path.orEmpty()
                    synchronized(requests) { requests += path }
                    val body = if (path.startsWith("/meta/nutrients")) catalog else daily
                    return MockResponse().setResponseCode(200).setBody(body)
                }
            }
        server.start()
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    private fun repository(): NutrientsRepository {
        val json =
            Json {
                ignoreUnknownKeys = true
                explicitNulls = false
            }
        val api =
            Retrofit.Builder()
                .baseUrl(server.url("/"))
                .client(OkHttpClient())
                .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
                .build()
                .create(MealsyApi::class.java)
        return NutrientsRepository(api)
    }

    @Test
    fun summary_asksForTheRangeInDaysWithFoods_andMapsTheCatalogueTabs() =
        runBlocking {
            val summary = repository().summary(MicroRange.Week)!!

            assertEquals(listOf("/nutrients/daily?days=7&meals=true"), requests.filter { it.startsWith("/nutrients") })
            assertEquals(listOf("electrolytes", "minerals"), summary.tabs.map { it.tab.id })
            // The retired key is dropped; sodium is a limit.
            assertEquals(listOf("iron"), summary.tabs[1].rows.map { it.nutrient.key })
            assertEquals(true, summary.tabs[0].rows[0].nutrient.isLimit)
            assertEquals(50, summary.tabs[1].rows[0].pct)
            assertEquals(listOf("Lentils", "Spinach"), summary.tabs[1].rows[0].topFoods)
            // Potassium had no value on the logged day: no data, not 0%.
            assertNull(summary.tabs[0].rows.first { it.nutrient.key == "potassium" }.pct)
            assertEquals(1, summary.daysLogged)
        }

    @Test
    fun catalogue_isFetchedOncePerRepository() =
        runBlocking {
            val repo = repository()
            repo.summary(MicroRange.Today)
            repo.summary(MicroRange.Month)
            assertEquals(1, requests.count { it.startsWith("/meta/nutrients") })
            assertEquals(2, requests.count { it.startsWith("/nutrients/daily") })
        }
}
