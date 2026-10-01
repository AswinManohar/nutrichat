package app.mealsy.data.repo

import app.mealsy.data.api.IngredientOverrideDto
import app.mealsy.data.api.ItemDto
import app.mealsy.data.api.LogMyMealRequest
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.MyMealDetailDto
import app.mealsy.data.api.SaveMealRequest
import app.mealsy.data.api.SavedMealDto
import app.mealsy.data.api.toSavedIngredientDto
import app.mealsy.domain.ConfirmationCard
import kotlinx.serialization.json.JsonObject
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

/** One stored ingredient on a saved meal, carrying any extra backend fields verbatim. */
data class SavedMealItem(
    val foodName: String,
    val qtyG: Double,
    val kcal: Double,
    val proteinG: Double,
    val carbsG: Double,
    val fatG: Double,
    val fiberG: Double,
    val fdcId: Long,
    val estimated: Boolean,
    val extras: JsonObject,
)

/**
 * Full detail of one saved meal, per `MyMealDetail` in
 * `src/backend/api/my_meals.py`. A dedicated type rather than reusing
 * [LoggedMealDetail]/[LoggedMealItem] from [MealsRepository] — [SavedMeal]
 * carries `name`/`nIngredients`/`loggedToday` instead of `mealType`/
 * `loggedAt`/`nItems`, so the summary shapes don't line up.
 */
data class SavedMealDetail(
    val meal: SavedMeal,
    val ingredients: List<SavedMealItem>,
    val updatedAt: String? = null,
)

/**
 * Thin wrapper over `GET/POST/DELETE /my-meals` and `POST /my-meals/{id}/log`
 * (`src/backend/api/my_meals.py`). `GET /my-meals` returns a bare JSON array
 * — no envelope object — so an empty list is a normal "nothing saved yet"
 * result, not an error (same contract as [TrendsRepository]).
 */
class MyMealsRepository
    @Inject
    constructor(
        private val api: MealsyApi,
        private val todayRefreshSignal: TodayRefreshSignal,
        private val myMealsRefreshSignal: MyMealsRefreshSignal,
    ) {
        suspend fun list(): List<SavedMeal> = api.myMeals().map { it.toSavedMeal() }

        /** Full detail, including stored ingredients, for the saved meal [id]. */
        suspend fun detail(id: String): SavedMealDetail = api.myMeal(id).toSavedMealDetail()

        /**
         * Saves [fromCard]'s current items (post-edit gram weights and portion)
         * as a new quick-log meal named [name]. Throws [retrofit2.HttpException]
         * with code 409 if a meal with that name already exists — callers decide
         * how to surface that.
         */
        suspend fun save(
            fromCard: ConfirmationCard,
            name: String,
        ) {
            api.saveMeal(
                SaveMealRequest(
                    name = name,
                    ingredients = fromCard.items.map { it.toSavedIngredientDto(fromCard.portion) },
                ),
            )
            myMealsRefreshSignal.notifyChanged()
        }

        /** Quick-logs the saved meal [id] verbatim (1x) at [mealType]. */
        suspend fun quickLog(
            id: String,
            mealType: String,
        ) {
            api.logMyMeal(id, LogMyMealRequest(mealType = mealType))
            todayRefreshSignal.notifyLogged()
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
            todayRefreshSignal.notifyLogged()
        }

        /**
         * Soft-deletes the saved meal [id]. Not idempotency-keyed — see the
         * mobile API contract's retry rules.
         *
         * Deliberately does not call [MyMealsRefreshSignal.notifyChanged]:
         * delete only ever runs from My Meals' own swipe-to-delete flow, whose
         * ViewModel already updates its list locally (see
         * [app.mealsy.android.ui.mymeals.MyMealsViewModel.commitDelete]).
         * Emitting here too would make that ViewModel redundantly refetch its
         * own delete via [MyMealsRefreshSignal]'s collector.
         */
        suspend fun delete(id: String) {
            api.deleteMyMeal(id)
        }
    }

private fun SavedMealDto.toSavedMeal(): SavedMeal =
    SavedMeal(
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

private fun MyMealDetailDto.toSavedMealDetail(): SavedMealDetail =
    SavedMealDetail(
        meal =
            SavedMeal(
                id = id,
                name = name,
                kcal = kcal,
                proteinG = proteinG,
                carbsG = carbsG,
                fatG = fatG,
                fiberG = fiberG,
                nIngredients = nIngredients,
                loggedToday = loggedToday,
            ),
        ingredients = ingredients.map { it.toSavedMealItem() },
        updatedAt = updatedAt,
    )

private fun ItemDto.toSavedMealItem(): SavedMealItem =
    SavedMealItem(
        foodName = foodName,
        qtyG = qtyG,
        kcal = kcal,
        proteinG = proteinG,
        carbsG = carbsG,
        fatG = fatG,
        fiberG = fiberG,
        fdcId = fdcId,
        estimated = estimated,
        extras = extras,
    )
