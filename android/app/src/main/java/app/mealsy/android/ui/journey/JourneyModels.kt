package app.mealsy.android.ui.journey

import app.mealsy.data.repo.DayPoint
import app.mealsy.domain.MicroRow
import app.mealsy.domain.TIP_BELOW_PCT
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.time.format.TextStyle
import java.util.Locale

/** Journey's ranges, in days ending today, and how the macros chart buckets them. */
enum class JourneyRange(val days: Int) {
    /** One column per day. */
    Week(7),

    /** One column per 7-day week, counted back from today. */
    Month(30),

    /** One column per calendar month. */
    Quarter(90),
}

/**
 * One column of the macros chart: the average day in its bucket.
 *
 * @param kcal Average kcal per logged day; sets the column's height.
 * @param hasData Whether any day in the bucket was logged; an empty bucket draws nothing.
 */
data class MacroColumn(
    val label: String,
    val kcal: Double,
    val proteinG: Double,
    val carbsG: Double,
    val fatG: Double,
    val hasData: Boolean,
)

/** Average grams per logged day across the whole range. */
data class MacroAverages(val proteinG: Int, val carbsG: Int, val fatG: Int)

/**
 * Buckets [days] (the backend omits unlogged days) into [range]'s columns,
 * oldest first, each the average of its logged days. [today] is the last day.
 */
internal fun buildMacroColumns(
    range: JourneyRange,
    days: List<DayPoint>,
    today: LocalDate,
    locale: Locale = Locale.getDefault(),
): List<MacroColumn> {
    val byDate = days.associateBy { LocalDate.parse(it.date) }
    val first = today.minusDays((range.days - 1).toLong())
    val buckets: List<Pair<String, List<LocalDate>>> =
        when (range) {
            JourneyRange.Week ->
                (0 until range.days).map { offset ->
                    val date = first.plusDays(offset.toLong())
                    date.dayOfWeek.getDisplayName(TextStyle.NARROW, locale) to listOf(date)
                }
            JourneyRange.Month -> {
                // Whole weeks back from today; the 2 days left over at the start
                // join the oldest week rather than making a 2-day column.
                val weeks = range.days / 7
                val label = DateTimeFormatter.ofPattern("MMM d", locale)
                (weeks - 1 downTo 0).map { w ->
                    val end = today.minusDays(7L * w)
                    val start = if (w == weeks - 1) first else end.minusDays(6)
                    label.format(start) to datesBetween(start, end)
                }
            }
            JourneyRange.Quarter ->
                datesBetween(first, today)
                    .groupBy { it.withDayOfMonth(1) }
                    .map { (month, dates) -> month.month.getDisplayName(TextStyle.SHORT, locale) to dates }
        }
    return buckets.map { (label, dates) -> column(label, dates.mapNotNull { byDate[it] }) }
}

/** Average protein, carbs and fat per logged day; null when nothing was logged. */
internal fun macroAverages(days: List<DayPoint>): MacroAverages? {
    if (days.isEmpty()) return null
    val n = days.size.toDouble()
    return MacroAverages(
        proteinG = Math.round(days.sumOf { it.proteinG } / n).toInt(),
        carbsG = Math.round(days.sumOf { it.carbsG } / n).toInt(),
        fatG = Math.round(days.sumOf { it.fatG } / n).toInt(),
    )
}

private fun column(
    label: String,
    logged: List<DayPoint>,
): MacroColumn {
    if (logged.isEmpty()) return MacroColumn(label, 0.0, 0.0, 0.0, 0.0, hasData = false)
    val n = logged.size.toDouble()
    return MacroColumn(
        label = label,
        kcal = logged.sumOf { it.kcal } / n,
        proteinG = logged.sumOf { it.proteinG } / n,
        carbsG = logged.sumOf { it.carbsG } / n,
        fatG = logged.sumOf { it.fatG } / n,
        hasData = true,
    )
}

private fun datesBetween(
    start: LocalDate,
    end: LocalDate,
): List<LocalDate> = generateSequence(start) { it.plusDays(1) }.takeWhile { !it.isAfter(end) }.toList()

/** A protein shortfall of at least this many grams a day leads the coach note. */
internal const val PROTEIN_GAP_NOTE_G = 10

/** What Journey's coach note talks about, resolved to copy by the screen. */
sealed interface JourneyCoach {
    data class ProteinGap(val avgG: Int, val goalG: Int) : JourneyCoach

    data class LowNutrient(val row: MicroRow) : JourneyCoach

    data object Steady : JourneyCoach
}

/**
 * The coach note's subject: a protein gap first (it is the target most users
 * set), else the lowest highlighted nutrient under [TIP_BELOW_PCT], else a
 * steady-mix note. Null when nothing was logged.
 */
internal fun journeyCoach(
    averages: MacroAverages?,
    proteinGoal: Double?,
    highlights: List<MicroRow>,
): JourneyCoach? {
    averages ?: return null
    val goal = proteinGoal?.let { Math.round(it).toInt() }
    if (goal != null && goal - averages.proteinG >= PROTEIN_GAP_NOTE_G) {
        return JourneyCoach.ProteinGap(avgG = averages.proteinG, goalG = goal)
    }
    val low =
        highlights
            .filter { row -> !row.nutrient.isLimit && (row.pct ?: TIP_BELOW_PCT) < TIP_BELOW_PCT }
            .minByOrNull { it.pct ?: 0 }
    return if (low != null) JourneyCoach.LowNutrient(low) else JourneyCoach.Steady
}
