package app.mealsy.android.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import app.mealsy.android.design.components.TagTone
import app.mealsy.android.ui.home.DayPart
import app.mealsy.android.ui.home.HomeCoachNote
import app.mealsy.android.ui.home.HomeContent
import app.mealsy.android.ui.home.HomeKcalState
import app.mealsy.android.ui.home.HomeMealRow
import app.mealsy.android.ui.home.HomeUiState
import org.junit.Test

/**
 * Goldens for the app shell on Home: [HomeContent] with [MealsyBottomBar]
 * overlaid exactly as [AppNav] composes it (real `BottomNavPill` + `OliveFab`,
 * not a hand-copied stand-in — that's why `MealsyBottomBar` is `internal`
 * rather than private to `AppNav.kt`).
 */
class AppShellGoldenTest : AppScreenshotTestBase() {
    private val partialMeals =
        listOf(
            HomeMealRow("breakfast", TagTone.Butter, 2),
            HomeMealRow("lunch", TagTone.Leaf, 1),
            HomeMealRow("dinner", TagTone.Pink, null),
            HomeMealRow("snack", TagTone.Powder, 1),
        )

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

    @Composable
    private fun render() {
        Box(modifier = Modifier.fillMaxSize()) {
            HomeContent(
                state = partialState(),
                onOpenSettings = {},
                onOpenMealType = {},
                onRetry = {},
                modifier = Modifier.fillMaxSize(),
            )
            MealsyBottomBar(
                selectedRoute = "home",
                onSelect = {},
                onFabClick = {},
                modifier = Modifier.align(Alignment.BottomCenter),
            )
        }
    }

    @Test
    fun appShellHomeLight() = captureMealsy("AppShell_home", false) { render() }

    @Test
    fun appShellHomeDark() = captureMealsy("AppShell_home", true) { render() }
}
