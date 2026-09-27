package app.mealsy.domain

/** Which third of the day a coach note is being generated for (mirrors Home's `DayPart`). */
enum class ProteinGapDayPart { Morning, Afternoon, Evening }

/** A protein-gap food suggestion, mapped to `strings.xml` by the UI layer. */
enum class ProteinFood { Egg, GreekYogurt, Milk, Tofu, Lentils }

/** A protein gap of at least this many grams is worth a coach note at all. */
const val PROTEIN_GAP_THRESHOLD_G: Int = 15

/**
 * Above this gap, naming one food would be misleading (no single everyday
 * food closes a 100g+ gap), so the note says to spread protein across meals
 * instead. See GitHub issue #36.
 */
const val PROTEIN_GAP_SINGLE_FOOD_MAX_G: Int = 20

/** Resolved shape of Home's protein-gap coach note, once a gap is worth mentioning. */
sealed interface ProteinGapSuggestion {
    /** The gap is small enough that naming [food] as a single suggestion is honest. */
    data class SingleFood(val gapG: Int, val food: ProteinFood) : ProteinGapSuggestion

    /** The gap is too large for one food to close; suggest spreading protein across meals. */
    data class Spread(val gapG: Int) : ProteinGapSuggestion
}

/** Ordered, dietary-pref-filtered food candidates for each day part; last resort is always allowed. */
private val CANDIDATES_BY_DAY_PART: Map<ProteinGapDayPart, List<ProteinFood>> =
    mapOf(
        ProteinGapDayPart.Morning to listOf(ProteinFood.Egg, ProteinFood.GreekYogurt, ProteinFood.Tofu, ProteinFood.Lentils),
        ProteinGapDayPart.Afternoon to listOf(ProteinFood.GreekYogurt, ProteinFood.Egg, ProteinFood.Tofu, ProteinFood.Lentils),
        ProteinGapDayPart.Evening to listOf(ProteinFood.Milk, ProteinFood.Egg, ProteinFood.Tofu, ProteinFood.Lentils),
    )

/**
 * Whether [food] is compatible with a user's dietary prefs.
 *
 * [dietaryPrefs] mirrors [Goals.dietaryPrefs] — a name -> selected map using
 * the onboarding/settings vocabulary (`"vegan"`, `"vegetarian"`,
 * `"pescatarian"`, `"no_dairy"`). [ProteinFood.Tofu] and [ProteinFood.Lentils]
 * are compatible with every combination, so a candidate is always found.
 */
private fun isAllowed(
    food: ProteinFood,
    dietaryPrefs: Map<String, Boolean>,
): Boolean {
    val vegan = dietaryPrefs["vegan"] == true
    val noDairy = dietaryPrefs["no_dairy"] == true
    return when (food) {
        ProteinFood.Egg -> !vegan
        ProteinFood.GreekYogurt, ProteinFood.Milk -> !vegan && !noDairy
        ProteinFood.Tofu, ProteinFood.Lentils -> true
    }
}

/**
 * Picks Home's protein-gap coach note, or `null` if none is worth showing.
 *
 * Pure function (see GitHub issue #36): a single-food suggestion is only
 * offered when [gapG] is small enough (`<= `[PROTEIN_GAP_SINGLE_FOOD_MAX_G])
 * that one everyday food plausibly closes it, larger gaps get a "spread
 * across meals" note instead, the suggested food always respects
 * [dietaryPrefs], and no nudge is shown before the day's first meal
 * ([mealsLoggedToday] `== 0`) since the "gap" at zero eaten is just the
 * whole target.
 *
 * @param gapG Remaining protein target minus protein eaten so far today, in grams.
 * @param mealsLoggedToday How many meals have been logged today (`TodayResponse.nMeals`).
 * @param dayPart Which third of the day it is, used to pick a food that fits the moment.
 * @param dietaryPrefs The user's `Goals.dietaryPrefs` (name -> selected).
 */
fun proteinGapSuggestion(
    gapG: Int,
    mealsLoggedToday: Int,
    dayPart: ProteinGapDayPart,
    dietaryPrefs: Map<String, Boolean>,
): ProteinGapSuggestion? {
    if (gapG < PROTEIN_GAP_THRESHOLD_G) return null
    if (mealsLoggedToday <= 0) return null

    return if (gapG <= PROTEIN_GAP_SINGLE_FOOD_MAX_G) {
        val food =
            CANDIDATES_BY_DAY_PART.getValue(dayPart).first { isAllowed(it, dietaryPrefs) }
        ProteinGapSuggestion.SingleFood(gapG = gapG, food = food)
    } else {
        ProteinGapSuggestion.Spread(gapG = gapG)
    }
}
