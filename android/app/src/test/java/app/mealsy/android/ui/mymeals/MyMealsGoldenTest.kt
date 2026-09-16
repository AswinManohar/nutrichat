package app.mealsy.android.ui.mymeals

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import app.mealsy.android.ui.AppScreenshotTestBase
import app.mealsy.data.repo.SavedMeal
import kotlinx.serialization.json.JsonObject
import org.junit.Test

/**
 * Goldens for [MyMealsScreen]'s designed states (via [MyMealsContent]) and
 * [CustomizeSheet]'s content (via [CustomizeSheetContent]), light and dark.
 * All state is hand-built — no ViewModel, no network, deterministic frames.
 */
class MyMealsGoldenTest : AppScreenshotTestBase() {

    private fun meals() = listOf(
        SavedMeal(
            id = "saved_1",
            name = "Usual breakfast",
            kcal = 450.0,
            proteinG = 28.0,
            carbsG = 40.0,
            fatG = 12.0,
            fiberG = 4.0,
            nIngredients = 2,
            loggedToday = false,
        ),
        SavedMeal(
            id = "saved_2",
            name = "Chicken, broilers or fryers, breast, meat only, cooked, grilled",
            kcal = 380.0,
            proteinG = 45.0,
            carbsG = 5.0,
            fatG = 14.0,
            fiberG = 0.0,
            nIngredients = 1,
            loggedToday = true,
        ),
        SavedMeal(
            id = "saved_3",
            name = "Post-workout shake",
            kcal = 320.0,
            proteinG = 30.0,
            carbsG = 35.0,
            fatG = 6.0,
            fiberG = 2.0,
            nIngredients = 3,
            loggedToday = false,
        ),
    )

    @Composable
    private fun renderList() {
        MyMealsContent(
            uiState = MyMealsUiState.Loaded(meals()),
            hiddenIds = emptySet(),
            onOpenMeal = {},
            onRetry = {},
            onDeleteWithUndo = {},
            onUndoDelete = {},
        )
    }

    @Test
    fun myMealsList_light() = captureMealsy("MyMeals_list", false) { renderList() }

    @Test
    fun myMealsList_dark() = captureMealsy("MyMeals_list", true) { renderList() }

    @Composable
    private fun renderEmpty() {
        MyMealsContent(
            uiState = MyMealsUiState.Empty,
            hiddenIds = emptySet(),
            onOpenMeal = {},
            onRetry = {},
            onDeleteWithUndo = {},
            onUndoDelete = {},
        )
    }

    @Test
    fun myMealsEmpty_light() = captureMealsy("MyMeals_empty", false) { renderEmpty() }

    @Test
    fun myMealsEmpty_dark() = captureMealsy("MyMeals_empty", true) { renderEmpty() }

    private fun customizeIngredients() = listOf(
        CustomizeIngredient(
            index = 0,
            item = app.mealsy.domain.CardItem(
                foodName = "Chicken, broilers or fryers, breast, meat only, cooked, grilled",
                qtyG = 150.0,
                targetQtyG = 150.0,
                kcal = 250.0,
                proteinG = 40.0,
                carbsG = 0.0,
                fatG = 8.0,
                fiberG = 0.0,
                fdcId = 1L,
                estimated = false,
                extras = JsonObject(emptyMap()),
            ),
            humanizedName = "Grilled chicken breast",
            rawNameIfDifferent = "Chicken, broilers or fryers, breast, meat only, cooked, grilled",
        ),
        CustomizeIngredient(
            index = 1,
            item = app.mealsy.domain.CardItem(
                foodName = "Brown rice, cooked",
                qtyG = 120.0,
                targetQtyG = 120.0,
                kcal = 140.0,
                proteinG = 3.0,
                carbsG = 30.0,
                fatG = 1.0,
                fiberG = 2.0,
                fdcId = 2L,
                estimated = false,
                extras = JsonObject(emptyMap()),
            ),
            humanizedName = "Brown rice",
            rawNameIfDifferent = "Brown rice, cooked",
        ),
    )

    @Composable
    private fun renderCustomizeSheet() {
        CustomizeSheetContent(
            state = CustomizeSheetState.initial(customizeIngredients(), mealType = "lunch"),
            submitting = false,
            onMealTypeSelect = {},
            onPortionSelect = {},
            onQtyChange = { _, _ -> },
            onRemove = {},
            onConfirm = {},
        )
    }

    @Test
    fun myMealsCustomizeSheet_light() = captureMealsy("MyMeals_customizeSheet", false) { renderCustomizeSheet() }

    @Test
    fun myMealsCustomizeSheet_dark() = captureMealsy("MyMeals_customizeSheet", true) { renderCustomizeSheet() }
}
