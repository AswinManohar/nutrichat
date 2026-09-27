package app.mealsy.android.ui.mealdetail

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import app.mealsy.android.design.components.TagTone
import app.mealsy.android.ui.AppScreenshotTestBase
import org.junit.Test

/**
 * Goldens for [MealDetailScreen]'s designed states, light and dark.
 * [MealDetailContent] (and, for the sheet, [LogAgainSheet]) are rendered
 * directly with hand-built state — no ViewModel, no network, deterministic
 * frames.
 */
class MealDetailGoldenTest : AppScreenshotTestBase() {
    private fun items() =
        listOf(
            MealDetailItemRow(humanizedName = "Grilled chicken breast", rawName = null, qtyG = 150, kcal = 250),
            MealDetailItemRow(humanizedName = "Brown rice", rawName = "brown rice, cooked", qtyG = 120, kcal = 140),
        )

    private fun loggedState(
        thirdTag: MealDetailThirdTag,
        status: MealDetailStatus,
    ) = MealDetailUiState.Loaded(
        mode = MealDetailMode.Logged("meal_1"),
        title = "Grilled chicken bowl",
        mealType = "lunch",
        timeLabel = "2026-09-16T12:05:00Z",
        heroTone = TagTone.Leaf,
        kcal = 520,
        proteinG = 42,
        thirdTag = thirdTag,
        status = status,
        items = items(),
        coachNote = MealDetailCoachNote.ProteinSource(itemName = "grilled chicken breast", alsoEstimated = false),
    )

    private fun myMealState() =
        MealDetailUiState.Loaded(
            mode = MealDetailMode.MyMeal("saved_1"),
            title = "Usual breakfast",
            mealType = null,
            timeLabel = null,
            heroTone = TagTone.Powder,
            kcal = 450,
            proteinG = 28,
            thirdTag = MealDetailThirdTag.None,
            status = MealDetailStatus.Logged,
            items = items(),
            coachNote = MealDetailCoachNote.None,
        )

    @Composable
    private fun render(state: MealDetailUiState.Loaded) {
        MealDetailContent(
            state = state,
            onBack = {},
            onLogAgain = {},
            onEditPortions = {},
            onDeleteRequested = {},
            modifier = Modifier.fillMaxSize(),
        )
    }

    @Test
    fun mealDetailLoggedUsdaVerified_light() =
        captureMealsy("MealDetail_loggedUsdaVerified", false) {
            render(loggedState(MealDetailThirdTag.UsdaVerified, MealDetailStatus.FitsBudget(kcalRemaining = "380")))
        }

    @Test
    fun mealDetailLoggedUsdaVerified_dark() =
        captureMealsy("MealDetail_loggedUsdaVerified", true) {
            render(loggedState(MealDetailThirdTag.UsdaVerified, MealDetailStatus.FitsBudget(kcalRemaining = "380")))
        }

    @Test
    fun mealDetailLoggedUsdaVerified_light_fontScale130() =
        captureMealsy("MealDetail_loggedUsdaVerified", false, 1.3f) {
            render(loggedState(MealDetailThirdTag.UsdaVerified, MealDetailStatus.FitsBudget(kcalRemaining = "380")))
        }

    @Test
    fun mealDetailLoggedUsdaVerified_light_fontScale200() =
        captureMealsy("MealDetail_loggedUsdaVerified", false, 2.0f) {
            render(loggedState(MealDetailThirdTag.UsdaVerified, MealDetailStatus.FitsBudget(kcalRemaining = "380")))
        }

    @Test
    fun mealDetailLoggedWithEstimated_light() =
        captureMealsy("MealDetail_loggedWithEstimated", false) {
            render(loggedState(MealDetailThirdTag.Estimated, MealDetailStatus.FitsBudget(kcalRemaining = "380")))
        }

    @Test
    fun mealDetailLoggedWithEstimated_dark() =
        captureMealsy("MealDetail_loggedWithEstimated", true) {
            render(loggedState(MealDetailThirdTag.Estimated, MealDetailStatus.FitsBudget(kcalRemaining = "380")))
        }

    @Test
    fun mealDetailOverTarget_light() =
        captureMealsy("MealDetail_overTarget", false) {
            render(loggedState(MealDetailThirdTag.UsdaVerified, MealDetailStatus.OverBudget(kcalOver = "220")))
        }

    @Test
    fun mealDetailOverTarget_dark() =
        captureMealsy("MealDetail_overTarget", true) {
            render(loggedState(MealDetailThirdTag.UsdaVerified, MealDetailStatus.OverBudget(kcalOver = "220")))
        }

    @Test
    fun mealDetailMyMeal_light() = captureMealsy("MealDetail_myMeal", false) { render(myMealState()) }

    @Test
    fun mealDetailMyMeal_dark() = captureMealsy("MealDetail_myMeal", true) { render(myMealState()) }

    // --- Log-again sheet (rendered as its own Popup root) --------------------

    @Composable
    private fun renderSheet() {
        LogAgainSheet(
            sheet = LogAgainSheetState(visible = true, mealType = "lunch", portion = 1.0),
            isMyMeal = false,
            onSelectMealType = {},
            onSelectPortion = {},
            onConfirm = {},
            onDismiss = {},
        )
    }

    @Test
    fun mealDetailLogAgainSheet_light() = captureMealsyDialog("MealDetail_logAgainSheet", false) { renderSheet() }

    @Test
    fun mealDetailLogAgainSheet_dark() = captureMealsyDialog("MealDetail_logAgainSheet", true) { renderSheet() }
}
