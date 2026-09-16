package app.mealsy.android.ui.trends

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import app.mealsy.android.ui.AppScreenshotTestBase
import app.mealsy.data.repo.CategorySlice
import app.mealsy.data.repo.DayPoint
import app.mealsy.data.repo.TrendData
import java.time.LocalDate
import org.junit.Test

/**
 * Goldens for Trends' designed states, light and dark. [TrendsContent] is
 * rendered directly with hand-built [TrendsUiState] values and a fixed
 * [FIXED_TODAY] -- no network, no [LocalDate.now], deterministic frames.
 */
class TrendsGoldenTest : AppScreenshotTestBase() {

    @Composable
    private fun render(window: TrendsWindow, uiState: TrendsUiState) {
        TrendsContent(
            window = window,
            uiState = uiState,
            onSelectWindow = {},
            onRetry = {},
            modifier = Modifier.fillMaxSize(),
            today = FIXED_TODAY,
        )
    }

    private fun weekDays(): List<DayPoint> = listOf(
        DayPoint("2026-09-10", kcal = 1750.0, proteinG = 88.0, carbsG = 190.0, fiberG = 18.0, nMeals = 3, junkMeals = 0),
        DayPoint("2026-09-12", kcal = 2100.0, proteinG = 105.0, carbsG = 220.0, fiberG = 22.0, nMeals = 4, junkMeals = 1),
        DayPoint("2026-09-13", kcal = 1600.0, proteinG = 80.0, carbsG = 160.0, fiberG = 15.0, nMeals = 2, junkMeals = 0),
        DayPoint("2026-09-14", kcal = 1900.0, proteinG = 95.0, carbsG = 200.0, fiberG = 20.0, nMeals = 3, junkMeals = 0),
        DayPoint("2026-09-16", kcal = 2050.0, proteinG = 102.0, carbsG = 210.0, fiberG = 19.0, nMeals = 3, junkMeals = 0),
    )

    private fun categories(): List<CategorySlice> = listOf(
        CategorySlice("breakfast", nMeals = 12, daysLogged = 10, avgKcal = 420.0, avgProteinG = 22.0, avgCarbsG = 45.0, avgFatG = 15.0, avgFiberG = 5.0, totalKcal = 5040.0, shareKcalPct = 28.4),
        CategorySlice("lunch", nMeals = 10, daysLogged = 10, avgKcal = 620.0, avgProteinG = 34.0, avgCarbsG = 60.0, avgFatG = 20.0, avgFiberG = 7.0, totalKcal = 6200.0, shareKcalPct = 34.9),
        CategorySlice("dinner", nMeals = 8, daysLogged = 8, avgKcal = 580.0, avgProteinG = 30.0, avgCarbsG = 55.0, avgFatG = 18.0, avgFiberG = 6.0, totalKcal = 4640.0, shareKcalPct = 26.1),
        CategorySlice("snack", nMeals = 6, daysLogged = 5, avgKcal = 180.0, avgProteinG = 5.0, avgCarbsG = 22.0, avgFatG = 6.0, avgFiberG = 2.0, totalKcal = 1080.0, shareKcalPct = 6.1),
    )

    private fun loadedState(): TrendsUiState.Loaded {
        val days = weekDays()
        return TrendsUiState.Loaded(
            trends = TrendData(days),
            categories = categories(),
            proteinGoal = 140.0,
            kcalGoal = 2200.0,
            avgKcal = averageKcal(days),
            avgProteinG = averageProteinG(days),
            daysLoggedCount = days.size,
            daysInWindow = TrendsWindow.WEEK.days,
        )
    }

    private fun monthState(): TrendsUiState.Loaded {
        val days = weekDays()
        return TrendsUiState.Loaded(
            trends = TrendData(days),
            categories = categories(),
            proteinGoal = 140.0,
            kcalGoal = 2200.0,
            avgKcal = averageKcal(days),
            avgProteinG = averageProteinG(days),
            daysLoggedCount = days.size,
            daysInWindow = TrendsWindow.MONTH.days,
        )
    }

    @Test
    fun trendsWeek_light() = captureMealsy("Trends_week", false) { render(TrendsWindow.WEEK, loadedState()) }

    @Test
    fun trendsWeek_dark() = captureMealsy("Trends_week", true) { render(TrendsWindow.WEEK, loadedState()) }

    @Test
    fun trendsMonth_light() = captureMealsy("Trends_month", false) { render(TrendsWindow.MONTH, monthState()) }

    @Test
    fun trendsMonth_dark() = captureMealsy("Trends_month", true) { render(TrendsWindow.MONTH, monthState()) }

    @Test
    fun trendsEmpty_light() = captureMealsy("Trends_empty", false) { render(TrendsWindow.WEEK, TrendsUiState.Empty) }

    @Test
    fun trendsEmpty_dark() = captureMealsy("Trends_empty", true) { render(TrendsWindow.WEEK, TrendsUiState.Empty) }

    private companion object {
        val FIXED_TODAY: LocalDate = LocalDate.of(2026, 9, 16)
    }
}
