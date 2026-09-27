package app.mealsy.android.ui.trends

import app.mealsy.data.repo.DayPoint
import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.LocalDate

/** Unit tests for [buildTrendsDayBars]/[trendsDayLabels], the Trends chart's pure date logic. */
class TrendsChartHelpersTest {
    private val today = LocalDate.of(2026, 9, 16) // a Wednesday

    @Test
    fun `week bars span exactly 7 days ending today, oldest first`() {
        val bars = buildTrendsDayBars(TrendsWindow.WEEK, emptyList(), today)

        assertEquals(7, bars.size)
        assertEquals(LocalDate.of(2026, 9, 10), bars.first().date)
        assertEquals(today, bars.last().date)
    }

    @Test
    fun `missing days render as zero-value bars rather than being skipped`() {
        val days =
            listOf(
                DayPoint("2026-09-16", kcal = 2000.0, proteinG = 100.0, carbsG = 0.0, fiberG = 0.0, nMeals = 2, junkMeals = 0),
            )
        val bars = buildTrendsDayBars(TrendsWindow.WEEK, days, today)

        assertEquals(7, bars.size)
        assertEquals(6, bars.count { !it.hasData })
        val todayBar = bars.last()
        assertEquals(true, todayBar.hasData)
        assertEquals(2000.0, todayBar.kcal, 0.0)
    }

    @Test
    fun `week labels are the full M T W T F S S sequence`() {
        val bars = buildTrendsDayBars(TrendsWindow.WEEK, emptyList(), today)
        val labels = trendsDayLabels(TrendsWindow.WEEK, bars)

        assertEquals(listOf("T", "F", "S", "S", "M", "T", "W"), labels)
    }

    @Test
    fun `month labels thin to first, last and every 6th day`() {
        val bars = buildTrendsDayBars(TrendsWindow.MONTH, emptyList(), today)
        val labels = trendsDayLabels(TrendsWindow.MONTH, bars)

        assertEquals(30, labels.size)
        assertEquals("", labels[1])
        assertEquals(bars.first().date.dayOfMonth.toString(), labels.first())
        assertEquals(bars.last().date.dayOfMonth.toString(), labels.last())
        assertEquals(bars[6].date.dayOfMonth.toString(), labels[6])
    }

    @Test
    fun `month labels never wrap two-digit days onto two lines`() {
        // Every rendered (non-empty) month label must be a single unbroken
        // token with no embedded whitespace/newline for maxLines=1 + softWrap
        // = false to keep it on one line, e.g. never "2\n9" or "2 9" for day 29.
        val bars = buildTrendsDayBars(TrendsWindow.MONTH, emptyList(), today)
        val labels = trendsDayLabels(TrendsWindow.MONTH, bars)

        labels.filter { it.isNotEmpty() }.forEach { label ->
            assertEquals(false, label.contains(" "))
            assertEquals(false, label.contains("\n"))
            assertEquals(true, label.toIntOrNull() != null)
        }
    }

    @Test
    fun `protein line segments group only consecutive logged days`() {
        val days =
            listOf(
                DayPoint("2026-09-11", kcal = 1900.0, proteinG = 90.0, carbsG = 0.0, fiberG = 0.0, nMeals = 2, junkMeals = 0),
                DayPoint("2026-09-12", kcal = 2000.0, proteinG = 100.0, carbsG = 0.0, fiberG = 0.0, nMeals = 2, junkMeals = 0),
                DayPoint("2026-09-15", kcal = 1800.0, proteinG = 80.0, carbsG = 0.0, fiberG = 0.0, nMeals = 1, junkMeals = 0),
            )
        val bars = buildTrendsDayBars(TrendsWindow.WEEK, days, today) // 2026-09-10..09-16
        // Logged: index 1 (09-11), 2 (09-12), 5 (09-15). Day 0, 3, 4, 6 unlogged.

        val segments = proteinLineSegments(bars)

        assertEquals(listOf(listOf(1, 2), listOf(5)), segments)
    }

    @Test
    fun `protein line segments is empty when nothing is logged`() {
        val bars = buildTrendsDayBars(TrendsWindow.WEEK, emptyList(), today)

        assertEquals(emptyList<List<Int>>(), proteinLineSegments(bars))
    }

    @Test
    fun `protein line segments is one run when every day is logged`() {
        val days =
            (0 until 7).map { offset ->
                val date = today.minusDays((6 - offset).toLong())
                DayPoint(date.toString(), kcal = 2000.0, proteinG = 100.0, carbsG = 0.0, fiberG = 0.0, nMeals = 1, junkMeals = 0)
            }
        val bars = buildTrendsDayBars(TrendsWindow.WEEK, days, today)

        assertEquals(listOf((0..6).toList()), proteinLineSegments(bars))
    }
}
