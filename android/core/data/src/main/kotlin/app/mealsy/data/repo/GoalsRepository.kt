package app.mealsy.data.repo

import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.toGoalRequest
import app.mealsy.data.api.toGoals
import app.mealsy.domain.Goals
import javax.inject.Inject
import retrofit2.HttpException

/**
 * Thin wrapper over `GET`/`POST`/`PUT /goals` (`src/backend/api/goals.py`).
 *
 * [get] maps the backend's 404 ("User has not been onboarded") to `null`
 * rather than letting [HttpException] escape — callers (the nav gate,
 * [app.mealsy.android.ui.onboarding.OnboardingViewModel]) treat "no goals
 * yet" as ordinary control flow, not an error. Any other [HttpException]
 * (5xx, etc.) still propagates, as do [java.io.IOException]s from being
 * offline — callers decide how to handle those.
 */
class GoalsRepository @Inject constructor(
    private val api: MealsyApi,
) {
    suspend fun get(): Goals? {
        return try {
            api.goals().toGoals()
        } catch (exc: HttpException) {
            if (exc.code() == 404) null else throw exc
        }
    }

    suspend fun create(goals: Goals): Goals = api.createGoals(goals.toGoalRequest()).toGoals()

    suspend fun update(goals: Goals): Goals = api.updateGoals(goals.toGoalRequest()).toGoals()
}
