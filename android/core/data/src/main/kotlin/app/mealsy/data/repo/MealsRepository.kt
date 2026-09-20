package app.mealsy.data.repo

import app.mealsy.data.api.ItemDto
import app.mealsy.data.api.MealLogDetailDto
import app.mealsy.data.api.MealLogSummaryDto
import app.mealsy.data.api.MealsyApi
import kotlinx.serialization.json.JsonObject
import java.time.LocalDate
import javax.inject.Inject

/** One logged meal, per `MealLogSummary` in `src/backend/api/meals.py`. */
data class LoggedMeal(
    val mealId: String,
    val mealType: String,
    val loggedAt: String,
    val label: String?,
    val kcal: Double,
    val proteinG: Double,
    val carbsG: Double,
    val fatG: Double,
    val fiberG: Double,
    val nItems: Int,
)

/** One resolved item on a logged meal, carrying any extra backend fields verbatim. */
data class LoggedMealItem(
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

/** Full detail of one logged meal, including its resolved items. */
data class LoggedMealDetail(
    val meal: LoggedMeal,
    val items: List<LoggedMealItem>,
)

/**
 * Thin wrapper over `GET /meals/log`, `GET /meals/log/{meal_id}`, and
 * `DELETE /meals/log/{meal_id}` (`src/backend/api/meals.py`). `GET
 * /meals/log` returns a bare JSON array — no envelope object — so an empty
 * list is a normal "nothing logged that day" result, not an error (same
 * contract as [TrendsRepository]/[MyMealsRepository]).
 *
 * `DELETE /meals/log/{meal_id}` is not idempotency-keyed — see the mobile
 * API contract's retry rules — so callers should not blind-retry it on
 * timeout. A successful delete notifies [todayRefreshSignal] so the Home
 * dashboard (and any other today-derived screen) refetches its totals.
 */
class MealsRepository
    @Inject
    constructor(
        private val api: MealsyApi,
        private val todayRefreshSignal: TodayRefreshSignal,
    ) {
        /**
         * Lists the caller's logged meals for [date] (defaults to today),
         * optionally filtered to [mealType].
         */
        suspend fun listForDay(
            date: LocalDate = LocalDate.now(),
            mealType: String? = null,
        ): List<LoggedMeal> =
            api.listMealLogs(date = date.toString(), mealType = mealType)
                .map { it.toLoggedMeal() }

        /** Full detail, including resolved items, for the logged meal [id]. */
        suspend fun detail(id: String): LoggedMealDetail = api.mealLog(id).toLoggedMealDetail()

        /**
         * Soft-deletes the logged meal [id] and signals that today's totals
         * changed. Not idempotency-keyed — see the mobile API contract's retry
         * rules.
         */
        suspend fun delete(id: String) {
            api.deleteMealLog(id)
            todayRefreshSignal.notifyLogged()
        }
    }

private fun MealLogSummaryDto.toLoggedMeal(): LoggedMeal =
    LoggedMeal(
        mealId = mealId,
        mealType = mealType,
        loggedAt = loggedAt,
        label = label,
        kcal = kcal,
        proteinG = proteinG,
        carbsG = carbsG,
        fatG = fatG,
        fiberG = fiberG,
        nItems = nItems,
    )

private fun MealLogDetailDto.toLoggedMealDetail(): LoggedMealDetail =
    LoggedMealDetail(
        meal =
            LoggedMeal(
                mealId = mealId,
                mealType = mealType,
                loggedAt = loggedAt,
                label = label,
                kcal = kcal,
                proteinG = proteinG,
                carbsG = carbsG,
                fatG = fatG,
                fiberG = fiberG,
                nItems = nItems,
            ),
        items = items.map { it.toLoggedMealItem() },
    )

private fun ItemDto.toLoggedMealItem(): LoggedMealItem =
    LoggedMealItem(
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
