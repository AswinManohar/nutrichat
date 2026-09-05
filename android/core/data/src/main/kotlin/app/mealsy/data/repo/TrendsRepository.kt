package app.mealsy.data.repo

import app.mealsy.data.api.CategoryStatDto
import app.mealsy.data.api.DayTrendDto
import app.mealsy.data.api.MealsyApi
import javax.inject.Inject

/** One day's aggregate, per `GET /meals/trends` (`src/backend/api/meals.py`). */
data class DayPoint(
    val date: String,
    val kcal: Double,
    val proteinG: Double,
    val carbsG: Double,
    val fiberG: Double,
    val nMeals: Int,
    val junkMeals: Int,
)

/** All days returned for a trends window. Days with no meals are omitted by the backend. */
data class TrendData(val days: List<DayPoint>)

/** Per-category macro averages/frequency, per `GET /meals/categories`. */
data class CategorySlice(
    val mealType: String,
    val nMeals: Int,
    val daysLogged: Int,
    val avgKcal: Double,
    val avgProteinG: Double,
    val avgCarbsG: Double,
    val avgFatG: Double,
    val avgFiberG: Double,
    val totalKcal: Double,
    val shareKcalPct: Double,
)

/**
 * Thin wrapper over `GET /meals/trends` and `GET /meals/categories`
 * (`src/backend/api/meals.py`). Both endpoints return a bare JSON array —
 * there is no envelope object on the wire, so an empty list is a normal,
 * non-error "nothing logged in this window" result, not a failure.
 */
class TrendsRepository @Inject constructor(
    private val api: MealsyApi,
) {
    suspend fun trends(days: Int): TrendData = TrendData(api.trends(days).map { it.toDayPoint() })

    suspend fun categories(days: Int): List<CategorySlice> =
        api.categories(days).map { it.toCategorySlice() }
}

private fun DayTrendDto.toDayPoint(): DayPoint = DayPoint(
    date = date,
    kcal = kcal,
    proteinG = proteinG,
    carbsG = carbsG,
    fiberG = fiberG,
    nMeals = nMeals,
    junkMeals = junkMeals,
)

private fun CategoryStatDto.toCategorySlice(): CategorySlice = CategorySlice(
    mealType = mealType,
    nMeals = nMeals,
    daysLogged = daysLogged,
    avgKcal = avgKcal,
    avgProteinG = avgProteinG,
    avgCarbsG = avgCarbsG,
    avgFatG = avgFatG,
    avgFiberG = avgFiberG,
    totalKcal = totalKcal,
    shareKcalPct = shareKcalPct,
)
