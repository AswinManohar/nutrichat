package app.mealsy.android.design.components

import androidx.compose.material3.Surface
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.performClick
import app.mealsy.android.design.theme.MealsyTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * The Settings stepper flickered on every tap: the old and new values slid
 * past each other inside a one-line clip, so for ~120ms both showed, each cut
 * in half. The value must change in a single frame, with only one value ever
 * on screen.
 */
@RunWith(RobolectricTestRunner::class)
@Config(qualifiers = "w390dp-h844dp-xhdpi")
class StepperValueTest {
    @get:Rule
    val composeRule = createAndroidComposeRule<androidx.activity.ComponentActivity>()

    @Test
    fun tappingPlus_showsOnlyTheNewValue_evenMidFrame() {
        var value by mutableStateOf(2950)
        composeRule.setContent {
            MealsyTheme {
                Surface {
                    Stepper(
                        value = value,
                        onValueChange = { value = it },
                        step = 50,
                        min = 1000,
                        label = "Calories target",
                        valueLabel = { "$it kcal" },
                    )
                }
            }
        }
        composeRule.mainClock.autoAdvance = false

        composeRule.onNodeWithContentDescription("Increase Calories target", useUnmergedTree = true).performClick()
        // Halfway through what used to be the 120ms slide.
        composeRule.mainClock.advanceTimeBy(60)

        assertEquals(3000, value)
        assertEquals(0, composeRule.onAllNodesWithText("2950 kcal", useUnmergedTree = true).fetchSemanticsNodes().size)
        assertEquals(1, composeRule.onAllNodesWithText("3000 kcal", useUnmergedTree = true).fetchSemanticsNodes().size)
    }
}
