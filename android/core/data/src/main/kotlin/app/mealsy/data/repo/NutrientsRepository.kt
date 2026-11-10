package app.mealsy.data.repo

import app.mealsy.data.api.DailyNutrientsDto
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.api.NutrientCatalogDto
import app.mealsy.domain.MicroDay
import app.mealsy.domain.MicroFood
import app.mealsy.domain.MicroNutrient
import app.mealsy.domain.MicroRange
import app.mealsy.domain.MicroSummary
import app.mealsy.domain.MicroTab
import app.mealsy.domain.buildMicroSummary
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import javax.inject.Inject
import javax.inject.Singleton

/**
 * The Micronutrients screen's data: the catalogue's tabs (`GET
 * /meta/nutrients`) joined with the range's per-day totals (`GET
 * /nutrients/daily?days=N&meals=true`), reduced by [buildMicroSummary].
 *
 * The catalogue only changes when the server adds or retires a nutrient, so
 * it is fetched once per process; the first load requests it in parallel
 * with the day totals rather than before them.
 */
@Singleton
class NutrientsRepository
    @Inject
    constructor(
        private val api: MealsyApi,
    ) {
        private val catalogLock = Mutex()
        private var catalog: NutrientCatalogDto? = null

        /**
         * The summary for [range], or null when nothing was logged in it.
         *
         * @throws Exception Whatever the API call throws (network, HTTP); the
         *   caller maps it to an error state.
         */
        suspend fun summary(range: MicroRange): MicroSummary? =
            coroutineScope {
                val days = async { api.dailyNutrients(days = range.days, meals = true) }
                val tabs = tabsFrom(cachedCatalog())
                buildMicroSummary(tabs, days.await().toMicroDays())
            }

        private suspend fun cachedCatalog(): NutrientCatalogDto =
            catalogLock.withLock {
                catalog ?: api.nutrientCatalog().also { catalog = it }
            }
    }

/**
 * The catalogue's tabs as domain [MicroTab]s. A key the catalogue doesn't
 * list as active with a daily value is dropped (the server already rejects
 * that at startup; this only guards an older app against a newer catalogue).
 */
internal fun tabsFrom(catalog: NutrientCatalogDto): List<MicroTab> {
    val defs = catalog.nutrients.filter { it.status == "active" }.associateBy { it.key }
    return catalog.micronutrientTabs.map { tab ->
        MicroTab(
            id = tab.id,
            name = tab.name,
            nutrients =
                tab.keys.mapNotNull { key ->
                    val def = defs[key] ?: return@mapNotNull null
                    val dv = def.dailyValue ?: return@mapNotNull null
                    MicroNutrient(
                        key = def.key,
                        name = def.name,
                        unit = def.unit,
                        isLimit = def.direction == "limit",
                        dailyValue = dv,
                    )
                },
        )
    }
}

internal fun DailyNutrientsDto.toMicroDays(): List<MicroDay> =
    days.map { day ->
        MicroDay(
            logged = day.logged,
            totals = day.values.mapValues { it.value.total },
            foods =
                day.meals.flatMap { meal ->
                    meal.foods.map { food -> MicroFood(food.foodName, food.values.mapValues { it.value.total }) }
                },
        )
    }
