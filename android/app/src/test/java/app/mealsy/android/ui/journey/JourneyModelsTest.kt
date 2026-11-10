package app.mealsy.android.ui.journey

import app.mealsy.data.repo.DayPoint
import app.mealsy.domain.MicroNutrient
import app.mealsy.domain.MicroRow
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Test
import java.time.LocalDate
import java.util.Locale

class JourneyModelsTest {
    private val today = LocalDate.of(2026, 11, 10) // a Tuesday

    private fun day(
        date: String,
        kcal: Double,
        p: Double = 0.0,
        c: Double = 0.0,
        f: Double = 0.0,
    ) = DayPoint(date, kcal = kcal, proteinG = p, carbsG = c, fatG = f, fiberG = 0.0, nMeals = 1, junkMeals = 0)

    @Test
    fun week_isOneColumnPerDayEndingToday() {
        val cols = buildMacroColumns(JourneyRange.Week, listOf(day("2026-11-10", 1800.0, p = 90.0)), today, Locale.US)
        assertEquals(7, cols.size)
        assertEquals(listOf("W", "T", "F", "S", "S", "M", "T"), cols.map { it.label })
        assertEquals(1800.0, cols.last().kcal, 1e-9)
        assertFalse(cols.first().hasData)
    }

    @Test
    fun month_isFourWeeksBackFromToday_withLeftoverDaysInTheOldest() {
        val days =
            listOf(
                day("2026-10-12", 1000.0), // first day of the range: oldest bucket
                day("2026-10-13", 2000.0),
                day("2026-11-10", 1800.0),
            )
        val cols = buildMacroColumns(JourneyRange.Month, days, today, Locale.US)
        assertEquals(listOf("Oct 12", "Oct 21", "Oct 28", "Nov 4"), cols.map { it.label })
        // The oldest bucket averages its two logged days, not its nine calendar days.
        assertEquals(1500.0, cols[0].kcal, 1e-9)
        assertFalse(cols[1].hasData)
        assertEquals(1800.0, cols[3].kcal, 1e-9)
    }

    @Test
    fun quarter_isOneColumnPerCalendarMonth() {
        val cols = buildMacroColumns(JourneyRange.Quarter, listOf(day("2026-09-01", 2000.0)), today, Locale.US)
        assertEquals(listOf("Aug", "Sep", "Oct", "Nov"), cols.map { it.label })
        assertEquals(2000.0, cols[1].kcal, 1e-9)
    }

    @Test
    fun averages_areOverLoggedDays() {
        val avg =
            macroAverages(
                listOf(day("2026-11-09", 0.0, p = 80.0, c = 200.0, f = 50.0), day("2026-11-10", 0.0, p = 100.0, c = 220.0, f = 70.0)),
            )!!
        assertEquals(MacroAverages(proteinG = 90, carbsG = 210, fatG = 60), avg)
        assertNull(macroAverages(emptyList()))
    }

    private fun row(
        key: String,
        pct: Int?,
        limit: Boolean = false,
    ) = MicroRow(MicroNutrient(key, key, "mg", limit, 100.0), pct?.toDouble(), pct, emptyList())

    @Test
    fun coach_leadsWithAProteinGap() {
        val note = journeyCoach(MacroAverages(86, 200, 60), proteinGoal = 110.0, highlights = listOf(row("iron", 10)))
        assertEquals(JourneyCoach.ProteinGap(avgG = 86, goalG = 110), note)
    }

    @Test
    fun coach_thenTheLowestTargetUnderHalf_neverALimit() {
        val note =
            journeyCoach(
                MacroAverages(105, 200, 60),
                proteinGoal = 110.0,
                highlights = listOf(row("sodium", 5, limit = true), row("iron", 30), row("vitamin_d", 12), row("zinc", null)),
            )
        assertEquals("vitamin_d", (note as JourneyCoach.LowNutrient).row.nutrient.key)
    }

    @Test
    fun coach_isSteadyWhenNothingStandsOut_andAbsentWithNoLogs() {
        assertEquals(
            JourneyCoach.Steady,
            journeyCoach(MacroAverages(100, 200, 60), proteinGoal = null, highlights = listOf(row("iron", 80))),
        )
        assertNull(journeyCoach(null, proteinGoal = 110.0, highlights = emptyList()))
    }
}
