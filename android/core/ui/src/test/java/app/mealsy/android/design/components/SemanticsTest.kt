package app.mealsy.android.design.components

import androidx.compose.material3.Surface
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.test.assertContentDescriptionEquals
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.assertIsNotSelected
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import app.mealsy.android.design.icons.MealsyIcons
import app.mealsy.android.design.theme.MealsyTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * TalkBack-facing semantics assertions for the components covered by Phase 6
 * Wave B's accessibility pass: [StatusPill], [Stepper], [SegmentedControl],
 * and [BottomNavPill]'s nav items.
 *
 * These are semantics assertions, not screenshot goldens — no Roborazzi
 * capture happens here, only [androidx.compose.ui.test] tree queries against
 * a Robolectric-hosted composition.
 */
@RunWith(RobolectricTestRunner::class)
@Config(qualifiers = "w390dp-h844dp-xhdpi")
class SemanticsTest {

    @get:Rule
    val composeRule = createAndroidComposeRule<androidx.activity.ComponentActivity>()

    @Test
    fun statusPill_mergesEatenAndStateLabelsIntoOneDescription() {
        composeRule.setContent {
            MealsyTheme {
                Surface {
                    StatusPill(
                        eatenLabel = "1,340 kcal eaten",
                        stateLabel = "560 left",
                        eatenFraction = 0.7f,
                        animate = false,
                    )
                }
            }
        }

        composeRule.onNodeWithContentDescription("1,340 kcal eaten, 560 left")
            .assertExists()
    }

    @Test
    fun stepper_announcesLabelAndValueAndSupportsSetProgress() {
        var value by mutableStateOf(120)
        composeRule.setContent {
            MealsyTheme {
                Surface {
                    Stepper(value = value, onValueChange = { value = it }, step = 5, min = 5)
                }
            }
        }

        val node = composeRule.onNodeWithContentDescription("Quantity").fetchSemanticsNode()
        val stateDescription = node.config.getOrNull(SemanticsProperties.StateDescription)
        assertEquals("120 g", stateDescription)

        val rangeInfo = node.config.getOrNull(SemanticsProperties.ProgressBarRangeInfo)
        assertNotNull(rangeInfo)
        assertEquals(120f, rangeInfo!!.current)

        val setProgressAction = node.config.getOrNull(SemanticsActions.SetProgress)
        assertNotNull(setProgressAction)
        setProgressAction!!.action?.invoke(125f)
        composeRule.waitForIdle()
        assertEquals(125, value)

        // The +/- buttons remain individually reachable with their own labels.
        composeRule.onNodeWithContentDescription("Increase").assertExists()
        composeRule.onNodeWithContentDescription("Decrease").assertExists()
    }

    @Test
    fun segmentedControl_exposesRadioGroupSemantics() {
        var selected by mutableStateOf("Lunch")
        val options = listOf("Breakfast", "Lunch", "Dinner", "Snack")
        composeRule.setContent {
            MealsyTheme {
                Surface {
                    SegmentedControl(
                        options = options,
                        selected = selected,
                        onSelect = { selected = it },
                        label = { it },
                    )
                }
            }
        }

        composeRule.onNodeWithText("Lunch").assertIsSelected()
        composeRule.onNodeWithText("Breakfast").assertIsNotSelected()
    }

    @Test
    fun bottomNavPill_itemsAreTabsWithSelectedState() {
        val items = listOf(
            MealsyNavItem(MealsyIcons.Home, "Home", "home"),
            MealsyNavItem(MealsyIcons.BowlBars, "Meals", "meals"),
        )
        composeRule.setContent {
            MealsyTheme {
                Surface {
                    BottomNavPill(items = items, selectedRoute = "home", onSelect = {})
                }
            }
        }

        val homeNode = composeRule.onNodeWithContentDescription("Home").fetchSemanticsNode()
        assertEquals(
            androidx.compose.ui.semantics.Role.Tab,
            homeNode.config.getOrNull(SemanticsProperties.Role),
        )
        composeRule.onNodeWithContentDescription("Home").assertIsSelected()
        composeRule.onNodeWithContentDescription("Meals").assertIsNotSelected()
    }
}
