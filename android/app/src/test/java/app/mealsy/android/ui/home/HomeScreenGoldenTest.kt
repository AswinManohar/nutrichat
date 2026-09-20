package app.mealsy.android.ui.home

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import app.mealsy.android.design.components.TagTone
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
            coachNote = HomeCoachNote.ProteinGap(gapG = 40, dayPart = DayPart.Afternoon),
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
}
