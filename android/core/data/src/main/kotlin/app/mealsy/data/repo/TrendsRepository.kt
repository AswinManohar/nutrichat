package app.mealsy.data.repo

import app.mealsy.data.api.DayTrendDto
import app.mealsy.data.api.MealsyApi
import javax.inject.Inject

/** One day's aggregate, per `GET /meals/trends` (`src/backend/api/meals.py`). */
data class DayPoint(
    val date: String,
    val kcal: Double,
    val proteinG: Double,
    val carbsG: Double,
    val fatG: Double,
    val fiberG: Double,
    val nMeals: Int,
    val junkMeals: Int,
)

/** All days returned for a trends window. Days with no meals are omitted by the backend. */
data class TrendData(val days: List<DayPoint>)

/**
 * Thin wrapper over `GET /meals/trends` (`src/backend/api/meals.py`). The
 * endpoint returns a bare JSON array, so an empty list is a normal "nothing
 * logged in this window" result, not a failure.
 */
class TrendsRepository
    @Inject
    constructor(
        private val api: MealsyApi,
    ) {
        suspend fun trends(days: Int): TrendData = TrendData(api.trends(days).map { it.toDayPoint() })
    }

private fun DayTrendDto.toDayPoint(): DayPoint =
    DayPoint(
        date = date,
        kcal = kcal,
        proteinG = proteinG,
        carbsG = carbsG,
        fatG = fatG,
        fiberG = fiberG,
        nMeals = nMeals,
        junkMeals = junkMeals,
    )
