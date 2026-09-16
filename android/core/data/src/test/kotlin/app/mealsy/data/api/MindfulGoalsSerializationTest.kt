package app.mealsy.data.api

import app.mealsy.domain.Goals
import kotlinx.serialization.json.Json
import org.junit.Assert.assertFalse
import org.junit.Test

/**
 * Confirms `Goals.toGoalRequest()` serialises Assumption 3's "mindful" goal
 * (`trackingMode = "mindful"`, all three numeric goals null) the way the
 * backend expects, using the app's real [ApiModule.provideJson] config
 * (`explicitNulls = false`) rather than a default [Json].
 *
 * Checked against `src/backend/api/goals.py`'s `GoalCreate`/`GoalUpdate`:
 * `kcal_goal`/`protein_goal`/`fiber_goal` all default to `None` there, and
 * the "goals required" validator only fires when `tracking_mode == "goals"`
 * — so omitting the three keys entirely (what `explicitNulls = false`
 * does) is equivalent to sending them as explicit `null`s, and is accepted
 * for `tracking_mode == "mindful"` either way.
 */
class MindfulGoalsSerializationTest {

    private val json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
    }

    @Test
    fun `mindful goals omit the three numeric goal keys on the wire`() {
        val goals = Goals(
            trackingMode = "mindful",
            kcalGoal = null,
            proteinGoal = null,
            fiberGoal = null,
            dietaryPrefs = mapOf("vegan" to true),
        )

        val encoded = json.encodeToString(GoalRequest.serializer(), goals.toGoalRequest())

        assertFalse(encoded.contains("kcal_goal"))
        assertFalse(encoded.contains("protein_goal"))
        assertFalse(encoded.contains("fiber_goal"))
    }

    @Test
    fun `mindful goals round-trip through GoalRequest unchanged`() {
        val goals = Goals(
            trackingMode = "mindful",
            kcalGoal = null,
            proteinGoal = null,
            fiberGoal = null,
            dietaryPrefs = mapOf("vegan" to true),
        )

        val request = goals.toGoalRequest()

        assert(request.trackingMode == "mindful")
        assert(request.kcalGoal == null)
        assert(request.proteinGoal == null)
        assert(request.fiberGoal == null)
    }
}
