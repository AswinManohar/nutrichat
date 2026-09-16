package app.mealsy.android.ui.meals

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import app.mealsy.android.ui.AppScreenshotTestBase
import app.mealsy.data.repo.LoggedMeal
import org.junit.Test

/**
 * Goldens for [MealTypeListScreen]'s designed states, light and dark.
 * [MealTypeListContent] is rendered directly with hand-built state — no
 * ViewModel, no network, deterministic frames.
 */
class MealTypeListGoldenTest : AppScreenshotTestBase() {

    private fun meal(id: String, label: String, kcal: Double, loggedAt: String) = LoggedMeal(
        mealId = id,
        mealType = "lunch",
        loggedAt = loggedAt,
        label = label,
        kcal = kcal,
        proteinG = 24.0,
        carbsG = 40.0,
        fatG = 12.0,
        fiberG = 5.0,
        nItems = 2,
    )

    private val populatedMeals = listOf(
        meal("meal_1", "Grilled chicken bowl", 520.0, "2026-09-16T12:05:00Z"),
        meal("meal_2", "Turkey sandwich", 410.0, "2026-09-16T13:20:00Z"),
    )

    @Composable
    private fun render(state: MealTypeListUiState) {
        MealTypeListContent(
            state = state,
            hiddenIds = emptySet(),
            mealType = "lunch",
            onBack = {},
            onOpenMeal = {},
            onRetry = {},
            onSwipeDelete = {},
            modifier = Modifier.fillMaxSize(),
        )
    }

    @Test
    fun mealTypeListPopulated_light() =
        captureMealsy("MealTypeList_populated", false) { render(MealTypeListUiState.Loaded(populatedMeals)) }

    @Test
    fun mealTypeListPopulated_dark() =
        captureMealsy("MealTypeList_populated", true) { render(MealTypeListUiState.Loaded(populatedMeals)) }

    @Test
    fun mealTypeListEmpty_light() =
        captureMealsy("MealTypeList_empty", false) { render(MealTypeListUiState.Empty) }

    @Test
    fun mealTypeListEmpty_dark() =
        captureMealsy("MealTypeList_empty", true) { render(MealTypeListUiState.Empty) }
}
