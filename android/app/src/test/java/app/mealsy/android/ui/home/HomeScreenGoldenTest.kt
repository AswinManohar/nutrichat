package app.mealsy.android.ui.home

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.components.TagTone
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.ui.AppScreenshotTestBase
import org.junit.Test

/**
 * Goldens for Home's designed states, light and dark. [HomeContent] is
 * rendered directly with hand-built [HomeUiState] values — no
 * pull-to-refresh wrapper, no network, deterministic frames.
 */
class HomeScreenGoldenTest : AppScreenshotTestBase() {
    private fun mealRow(
        mealType: String,
        tone: TagTone,
        count: Int?,
    ) = HomeMealRow(mealType, tone, count)

    private val emptyMeals =
        listOf(
            mealRow("breakfast", TagTone.Butter, null),
            mealRow("lunch", TagTone.Leaf, null),
            mealRow("dinner", TagTone.Pink, null),
            mealRow("snack", TagTone.Powder, null),
        )

    private val partialMeals =
        listOf(
            mealRow("breakfast", TagTone.Butter, 2),
            mealRow("lunch", TagTone.Leaf, 1),
            mealRow("dinner", TagTone.Pink, null),
            mealRow("snack", TagTone.Powder, 1),
        )

    @Composable
    private fun render(state: HomeUiState) {
        HomeContent(
            state = state,
            onOpenSettings = {},
            onOpenMealType = {},
            onRetry = {},
            modifier = Modifier.fillMaxSize(),
        )
    }

    // --- Empty: nothing logged --------------------------------------------

    private fun emptyState() =
        HomeUiState(
            loading = false,
            dateLabel = "WEDNESDAY, SEP 16",
            dayPart = DayPart.Morning,
            firstName = "Alex",
            mindful = false,
            eatenKcal = "0",
            kcalState = HomeKcalState.Left("1,900"),
            eatenFraction = 0f,
            proteinValue = "0g",
            carbsValue = "0g",
            fatValue = "0g",
            meals = emptyMeals,
            coachNote = HomeCoachNote.KcalRemaining(kcal = 1900),
        )

    @Test
    fun homeEmpty_light() = captureMealsy("Home_empty", false) { render(emptyState()) }

    @Test
    fun homeEmpty_dark() = captureMealsy("Home_empty", true) { render(emptyState()) }

    // --- Partial: the design mock -------------------------------------------

    private fun partialState() =
        HomeUiState(
            loading = false,
            dateLabel = "WEDNESDAY, SEP 16",
            dayPart = DayPart.Afternoon,
            firstName = "Alex",
            mindful = false,
            eatenKcal = "1,340",
            kcalState = HomeKcalState.Left("560"),
            eatenFraction = 1340f / 1900f,
            proteinValue = "86g",
            carbsValue = "152g",
            fatValue = "48g",
            meals = partialMeals,
            coachNote = HomeCoachNote.ProteinGapSpread(gapG = 40),
        )

    @Test
    fun homePartial_light() = captureMealsy("Home_partial", false) { render(partialState()) }

    @Test
    fun homePartial_dark() = captureMealsy("Home_partial", true) { render(partialState()) }

    @Test
    fun homePartial_light_fontScale130() = captureMealsy("Home_partial", false, 1.3f) { render(partialState()) }

    @Test
    fun homePartial_light_fontScale200() = captureMealsy("Home_partial", false, 2.0f) { render(partialState()) }

    // --- Over goal --------------------------------------------------------

    private fun overGoalState() =
        HomeUiState(
            loading = false,
            dateLabel = "WEDNESDAY, SEP 16",
            dayPart = DayPart.Evening,
            firstName = "Alex",
            mindful = false,
            eatenKcal = "2,220",
            kcalState = HomeKcalState.Over("120"),
            eatenFraction = 1f,
            proteinValue = "150g",
            carbsValue = "210g",
            fatValue = "70g",
            meals = partialMeals,
            coachNote = HomeCoachNote.TargetReached,
        )

    @Test
    fun homeOverGoal_light() = captureMealsy("Home_over_goal", false) { render(overGoalState()) }

    @Test
    fun homeOverGoal_dark() = captureMealsy("Home_over_goal", true) { render(overGoalState()) }

    // --- Mindful ------------------------------------------------------------

    private fun mindfulState() =
        HomeUiState(
            loading = false,
            dateLabel = "WEDNESDAY, SEP 16",
            dayPart = DayPart.Afternoon,
            firstName = "Alex",
            mindful = true,
            eatenKcal = "1,340",
            kcalState = HomeKcalState.NoTarget,
            eatenFraction = 0f,
            proteinValue = "86g",
            carbsValue = "152g",
            fatValue = "48g",
            meals = partialMeals,
            coachNote = HomeCoachNote.Mindful(nMeals = 4),
        )

    @Test
    fun homeMindful_light() = captureMealsy("Home_mindful", false) { render(mindfulState()) }

    @Test
    fun homeMindful_dark() = captureMealsy("Home_mindful", true) { render(mindfulState()) }

    // --- Loading / error ------------------------------------------------------

    @Test
    fun homeLoading_light() = captureMealsy("Home_loading", false) { render(HomeUiState(loading = true)) }

    @Test
    fun homeLoading_dark() = captureMealsy("Home_loading", true) { render(HomeUiState(loading = true)) }

    @Test
    fun homeError_light() = captureMealsy("Home_error", false) { render(HomeUiState(loading = false, error = true)) }

    @Test
    fun homeError_dark() = captureMealsy("Home_error", true) { render(HomeUiState(loading = false, error = true)) }

    // --- This week grid -------------------------------------------------------

    private fun cell(
        grams: Int,
        low: Boolean = false,
    ) = HomeWeekCell(grams, low)

    private fun weekDay(
        weekday: String,
        kcal: String?,
        protein: Int,
        fiber: Int,
        carbs: Int,
        lowProtein: Boolean = false,
        lowFiber: Boolean = false,
        isToday: Boolean = false,
    ) = HomeWeekDay(
        weekday = weekday,
        isToday = isToday,
        kcal = kcal,
        kcalThousands = kcal?.let { "%.1f".format(it.replace(",", "").toInt() / 1000.0) },
        protein = kcal?.let { cell(protein, lowProtein) },
        fiber = kcal?.let { cell(fiber, lowFiber) },
        carbs = kcal?.let { cell(carbs) },
    )

    /** The design mock's week: one low-protein day, low fiber on two, one day with nothing logged. */
    private val designWeek =
        HomeWeek(
            startLabel = "Sep 10",
            days =
                listOf(
                    weekDay("Thu", "1,980", 118, 31, 214),
                    weekDay("Fri", "2,150", 104, 22, 246),
                    weekDay("Sat", "1,820", 72, 26, 198, lowProtein = true),
                    weekDay("Sun", "2,310", 96, 18, 268, lowFiber = true),
                    weekDay("Mon", null, 0, 0, 0),
                    weekDay("Tue", "1,760", 88, 28, 190),
                    weekDay("Wed", "1,440", 86, 19, 152, lowFiber = true, isToday = true),
                ),
            showsGoalLegend = true,
        )

    @Composable
    private fun renderWeek(
        week: HomeWeek?,
        unavailable: Boolean = false,
    ) {
        Box(modifier = Modifier.fillMaxSize().background(MealsyTheme.colors.canvas).padding(20.dp)) {
            HomeWeekSection(week = week, unavailable = unavailable)
        }
    }

    @Test
    fun homeWeek_light() = captureMealsy("Home_week", false) { renderWeek(designWeek) }

    @Test
    fun homeWeek_dark() = captureMealsy("Home_week", true) { renderWeek(designWeek) }

    @Test
    fun homeWeek_light_fontScale130() = captureMealsy("Home_week", false, 1.3f) { renderWeek(designWeek) }

    @Test
    fun homeWeekUnavailable_light() = captureMealsy("Home_week_unavailable", false) { renderWeek(null, unavailable = true) }
}
