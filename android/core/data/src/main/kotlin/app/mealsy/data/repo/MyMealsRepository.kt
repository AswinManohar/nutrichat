package app.mealsy.data.repo

import app.mealsy.data.api.IngredientOverrideDto
import app.mealsy.data.api.LogMyMealRequest
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.SaveMealRequest
import app.mealsy.data.api.SavedMealDto
import app.mealsy.data.api.toSavedIngredientDto
import app.mealsy.domain.ConfirmationCard
import javax.inject.Inject

/** One saved "quick log" meal, per `MyMealSummary` in `src/backend/api/my_meals.py`. */
data class SavedMeal(
    val id: String,
    val name: String,
    val kcal: Double,
    val proteinG: Double,
    val carbsG: Double,
    val fatG: Double,
    val fiberG: Double,
    val nIngredients: Int,
    val loggedToday: Boolean,
)

/** One kept ingredient (by stored index) with its edited gram weight, for a customized quick-log. */
data class SavedMealOverride(val index: Int, val qtyG: Double)

/**
 * Thin wrapper over `GET/POST/DELETE /my-meals` and `POST /my-meals/{id}/log`
 * (`src/backend/api/my_meals.py`). `GET /my-meals` returns a bare JSON array
 * — no envelope object — so an empty list is a normal "nothing saved yet"
 * result, not an error (same contract as [TrendsRepository]).
 */
class MyMealsRepository @Inject constructor(
    private val api: MealsyApi,
) {
    suspend fun list(): List<SavedMeal> = api.myMeals().map { it.toSavedMeal() }

    /**
     * Saves [fromCard]'s current items (post-edit gram weights and portion)
     * as a new quick-log meal named [name]. Throws [retrofit2.HttpException]
     * with code 409 if a meal with that name already exists — callers decide
     * how to surface that.
     */
    suspend fun save(fromCard: ConfirmationCard, name: String) {
        api.saveMeal(
            SaveMealRequest(
                name = name,
                ingredients = fromCard.items.map { it.toSavedIngredientDto(fromCard.portion) },
            ),
        )
    }

    /** Quick-logs the saved meal [id] verbatim (1x) at [mealType]. */
    suspend fun quickLog(id: String, mealType: String) {
        api.logMyMeal(id, LogMyMealRequest(mealType = mealType))
    }

    /**
     * Logs saved meal [id] at [mealType], keeping only [overrides] (by stored
     * index) at their edited gram weights, scaled by [portion]. The rest of
     * the meal's ingredients are dropped, per the backend's "customize"
     * contract.
     */
    suspend fun logCustomized(
        id: String,
        mealType: String,
        overrides: List<SavedMealOverride>,
        portion: Double = 1.0,
    ) {
        api.logMyMeal(
            id,
            LogMyMealRequest(
                mealType = mealType,
                portion = portion,
                ingredients = overrides.map { IngredientOverrideDto(index = it.index, qtyG = it.qtyG) },
            ),
        )
    }

    /** Soft-deletes the saved meal [id]. Not idempotency-keyed — see the mobile API contract's retry rules. */
    suspend fun delete(id: String) {
        api.deleteMyMeal(id)
    }
}

private fun SavedMealDto.toSavedMeal(): SavedMeal = SavedMeal(
    id = id,
    name = name,
    kcal = kcal,
    proteinG = proteinG,
    carbsG = carbsG,
    fatG = fatG,
    fiberG = fiberG,
    nIngredients = nIngredients,
    loggedToday = loggedToday,
)
