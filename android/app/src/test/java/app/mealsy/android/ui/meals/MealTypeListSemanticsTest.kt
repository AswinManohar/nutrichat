package app.mealsy.android.ui.meals

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.performSemanticsAction
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.ui.TestHostActivity
import app.mealsy.data.repo.LoggedMeal
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/**
 * TalkBack-facing semantics assertions for [MealTypeListScreen]'s rows —
 * #48 follow-up: a row's tap must survive a `clickable(role = Role.Button)`
 * (not a raw `pointerInput`), and since TalkBack can't perform the swipe
 * gesture at all, delete must also be reachable as a `CustomAccessibilityAction`
 * (mirrors `MyMealsScreen`'s rows).
 */
@RunWith(RobolectricTestRunner::class)
@Config(qualifiers = "w390dp-h844dp-xhdpi")
class MealTypeListSemanticsTest {
    @get:Rule
    val composeRule = createAndroidComposeRule<TestHostActivity>()

    private val meal =
        LoggedMeal(
            mealId = "meal_1",
            mealType = "lunch",
            loggedAt = "2026-09-16T12:05:00Z",
            label = "Grilled chicken bowl",
            kcal = 520.0,
            proteinG = 24.0,
            carbsG = 40.0,
            fatG = 12.0,
            fiberG = 5.0,
            nItems = 2,
        )

    private fun setRow(
        onOpenMeal: (String) -> Unit = {},
        onSwipeDelete: (String) -> Unit = {},
    ) {
        composeRule.setContent {
            MealsyTheme {
                Surface {
                    MealTypeListContent(
                        state = MealTypeListUiState.Loaded(listOf(meal)),
                        hiddenIds = emptySet(),
                        mealType = "lunch",
                        onBack = {},
                        onOpenMeal = onOpenMeal,
                        onRetry = {},
                        onSwipeDelete = onSwipeDelete,
                        modifier = Modifier.fillMaxSize(),
                    )
                }
            }
        }
    }

    private val rowMatcher: SemanticsMatcher
        get() = hasClickAction().and(hasText("Grilled chicken bowl", substring = true))

    @Test
    fun row_clickActionOpensMeal() {
        var openedId: String? = null
        setRow(onOpenMeal = { openedId = it })

        val row = composeRule.onNode(rowMatcher)
        val clickAction = row.fetchSemanticsNode().config.getOrNull(SemanticsActions.OnClick)
        assertNotNull("row should expose an OnClick semantics action", clickAction)
        assertEquals("Open meal", clickAction?.label)

        row.performSemanticsAction(SemanticsActions.OnClick)
        assertEquals("meal_1", openedId)
    }

    @Test
    fun row_customDeleteActionSwipeDeletesWithoutAGesture() {
        var deletedId: String? = null
        setRow(onSwipeDelete = { deletedId = it })

        val row = composeRule.onNode(rowMatcher)
        val customActions = row.fetchSemanticsNode().config.getOrNull(SemanticsActions.CustomActions)
        assertNotNull("row should expose a custom Delete action for TalkBack", customActions)
        assertEquals(1, customActions?.size)
        assertEquals("Delete", customActions?.first()?.label)

        customActions!!.first().action.invoke()
        assertEquals("meal_1", deletedId)
    }
}
