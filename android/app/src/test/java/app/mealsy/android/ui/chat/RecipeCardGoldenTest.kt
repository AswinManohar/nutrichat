package app.mealsy.android.ui.chat

import androidx.compose.runtime.Composable
import app.mealsy.android.ui.AppScreenshotTestBase
import app.mealsy.data.api.IngredientDto
import app.mealsy.data.api.RecipeDto
import org.junit.Test

/** Goldens for [RecipeCardView] and [SafetyBubble], light and dark. */
class RecipeCardGoldenTest : AppScreenshotTestBase() {
    private val recipe =
        RecipeDto(
            name = "Soft oat bowl with banana",
            intro = "A warm, easy-to-chew breakfast.",
            ingredients =
                listOf(
                    IngredientDto("rolled oats", 40.0),
                    IngredientDto("banana", 60.5),
                    IngredientDto("milk", 120.0),
                ),
            steps = listOf("Simmer the oats in the milk for 5 minutes.", "Mash the banana and stir it in."),
            activeMinutes = 5,
            totalMinutes = 10,
        )
    private val note = "Kept this soft and low in sodium because of your chewing difficulty and your sodium limit."

    @Composable
    private fun card(
        note: String?,
        choice: RecipeChoice = RecipeChoice.None,
    ) = RecipeCardView(recipe = recipe, constraintNote = note, choice = choice, onFeedback = { _, _ -> }, timestamp = "07:39 PM")

    @Test
    fun recipeCard_light() = captureMealsy("RecipeCard", false) { card(note) }

    @Test
    fun recipeCard_dark() = captureMealsy("RecipeCard", true) { card(note) }

    @Test
    fun recipeCardNoConstraint_light() = captureMealsy("RecipeCard_noConstraint", false) { card(null) }

    @Test
    fun recipeCardNoConstraint_dark() = captureMealsy("RecipeCard_noConstraint", true) { card(null) }

    @Test
    fun recipeCardAccepted_light() = captureMealsy("RecipeCard_accepted", false) { card(note, RecipeChoice.Accepted) }

    @Test
    fun recipeCardAccepted_dark() = captureMealsy("RecipeCard_accepted", true) { card(note, RecipeChoice.Accepted) }

    @Test
    fun safetyBubble_light() = captureMealsy("SafetyBubble", false) { SafetyBubble(SAFETY_TEXT, timestamp = "07:39 PM") }

    @Test
    fun safetyBubble_dark() = captureMealsy("SafetyBubble", true) { SafetyBubble(SAFETY_TEXT, timestamp = "07:39 PM") }

    private companion object {
        const val SAFETY_TEXT =
            "Chest pain can be serious. Please call your local emergency number now, " +
                "or ask someone to take you to urgent care."
    }
}
