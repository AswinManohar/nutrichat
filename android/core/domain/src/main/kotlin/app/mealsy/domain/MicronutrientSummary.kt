package app.mealsy.domain

import kotlin.math.roundToInt

/** The Micronutrients screen's ranges, in nutrition days ending today. */
enum class MicroRange(val days: Int) { Today(1), Week(7), Month(30) }

/**
 * One charted nutrient, as the catalogue (`GET /meta/nutrients`) defines it.
 *
 * @param isLimit A nutrient to stay under (sodium), rather than one to reach.
 * @param dailyValue The catalogue's daily value, in [unit]; the chart is "% of" this.
 */
data class MicroNutrient(
    val key: String,
    val name: String,
    val unit: String,
    val isLimit: Boolean,
    val dailyValue: Double,
)

/** One Micronutrients tab and its nutrients, in display order. */
data class MicroTab(val id: String, val name: String, val nutrients: List<MicroNutrient>)

/** One logged food's amounts by nutrient key; a key is absent when the food's value is unknown. */
data class MicroFood(val name: String, val amounts: Map<String, Double>)

/**
 * One nutrition day from `GET /nutrients/daily`. [logged] false means no meals
 * that day ("no data"), which is excluded from averages rather than counted as 0.
 * A key absent from [totals] means every food that day was unknown for it.
 */
data class MicroDay(val logged: Boolean, val totals: Map<String, Double>, val foods: List<MicroFood>)

/**
 * One nutrient's result for the range.
 *
 * @param avgAmount Average daily amount over the days it was known, in the
 *   nutrient's unit; null when no logged day had a value for it.
 * @param pct [avgAmount] as a rounded percent of the daily value; null with it.
 * @param topFoods Up to [TOP_FOODS] food names that supplied the most, largest first.
 */
data class MicroRow(
    val nutrient: MicroNutrient,
    val avgAmount: Double?,
    val pct: Int?,
    val topFoods: List<String>,
)

data class MicroTabSummary(val tab: MicroTab, val rows: List<MicroRow>)

/**
 * The whole screen's numbers for one range.
 *
 * @param highlights Journey's short list ([buildMicroSummary]'s `highlightKeys`),
 *   in that order; keys in no tab are skipped.
 * @param heroCount Non-limit nutrients, across every tab, at or past
 *   [HERO_THRESHOLD_PCT] of their daily value.
 * @param heroTotal Non-limit nutrients that had any data.
 */
data class MicroSummary(
    val tabs: List<MicroTabSummary>,
    val highlights: List<MicroRow>,
    val daysLogged: Int,
    val heroCount: Int,
    val heroTotal: Int,
)

/** The hero pill counts nutrients at or past this share of their daily value. */
const val HERO_THRESHOLD_PCT: Int = 50

/** A target nutrient under this share of its daily value earns the coach note's tip. */
const val TIP_BELOW_PCT: Int = 50

/** How many foods the detail panel names as a nutrient's sources. */
const val TOP_FOODS: Int = 2

/**
 * Builds the Micronutrients screen's numbers from the catalogue tabs and the
 * range's days. Returns null when no day in the range has a logged meal, so
 * the screen shows its empty state rather than a chart of zeros.
 */
fun buildMicroSummary(
    tabs: List<MicroTab>,
    days: List<MicroDay>,
    highlightKeys: List<String> = emptyList(),
): MicroSummary? {
    val logged = days.filter { it.logged }
    if (logged.isEmpty()) return null

    val summaries =
        tabs.map { tab ->
            MicroTabSummary(tab = tab, rows = tab.nutrients.map { microRow(it, logged) })
        }
    val rows = summaries.flatMap { it.rows }
    val byKey = rows.associateBy { it.nutrient.key }
    val targets = rows.filter { !it.nutrient.isLimit && it.pct != null }
    return MicroSummary(
        tabs = summaries,
        highlights = highlightKeys.mapNotNull { byKey[it] },
        daysLogged = logged.size,
        heroCount = targets.count { (it.pct ?: 0) >= HERO_THRESHOLD_PCT },
        heroTotal = targets.size,
    )
}

/**
 * The tab's lowest target nutrient under [TIP_BELOW_PCT], for the coach note;
 * null when every target is past it (limits never get a "have more" tip).
 */
fun lowestTarget(tab: MicroTabSummary): MicroRow? =
    tab.rows
        .filter { !it.nutrient.isLimit && it.pct != null && it.pct < TIP_BELOW_PCT }
        .minByOrNull { it.pct ?: 0 }

private fun microRow(
    nutrient: MicroNutrient,
    logged: List<MicroDay>,
): MicroRow {
    val known = logged.mapNotNull { it.totals[nutrient.key] }
    val avg = if (known.isEmpty()) null else known.sum() / known.size
    return MicroRow(
        nutrient = nutrient,
        avgAmount = avg,
        pct = avg?.let { (it / nutrient.dailyValue * 100).roundToInt() },
        topFoods = topFoods(nutrient.key, logged),
    )
}

/**
 * Foods ranked by how much of [key] they supplied over the range. Foods are
 * merged on their base name (see [sourceName]), so "Lentils, mature seeds,
 * cooked" and "lentils" count as one source.
 */
private fun topFoods(
    key: String,
    logged: List<MicroDay>,
): List<String> {
    val amounts = LinkedHashMap<String, Double>()
    val names = HashMap<String, String>()
    for (day in logged) {
        for (food in day.foods) {
            val amount = food.amounts[key] ?: continue
            if (amount <= 0.0) continue
            val name = sourceName(food.name)
            if (name.isEmpty()) continue
            val id = name.lowercase()
            names.putIfAbsent(id, name)
            amounts[id] = (amounts[id] ?: 0.0) + amount
        }
    }
    return amounts.entries.sortedByDescending { it.value }.take(TOP_FOODS).map { names.getValue(it.key) }
}

/**
 * A food's base name for a sources line: the part before USDA's first comma,
 * sentence-cased ("Rice, white, cooked" -> "Rice"). Unlike
 * [FoodNameHumanizer.humanize] it drops the preparation, which a "from X and
 * Y" sentence doesn't need and which would split one food into several.
 */
private fun sourceName(raw: String): String {
    val base = raw.substringBefore(',').trim()
    return base.replaceFirstChar { it.uppercaseChar() }
}
