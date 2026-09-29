package app.mealsy.android.ui.chat

import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.ui.TestHostActivity
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

/** UI-level proof (#56, FR-006) that [ChatUndoToast] shows its copy, offers Undo, and auto-dismisses. */
@RunWith(RobolectricTestRunner::class)
@Config(qualifiers = "w390dp-h844dp-xhdpi")
class ChatUndoToastTest {
    @get:Rule
    val composeRule = createAndroidComposeRule<TestHostActivity>()

    private fun show(
        toast: UndoToast,
        onUndo: (UndoToast) -> Unit = {},
        onDismiss: () -> Unit = {},
    ) {
        composeRule.setContent { MealsyTheme { ChatUndoToast(toast, onUndo, onDismiss) } }
    }

    @Test
    fun `swapped toast shows Swapped to name and Undo calls back with the toast`() {
        val toast = UndoToast.Swapped("Bread, egg, toasted", 1)
        val undone = mutableListOf<UndoToast>()
        show(toast, onUndo = { undone.add(it) })

        composeRule.onNodeWithText("Swapped to Bread, egg, toasted").assertExists()
        composeRule.onNodeWithText("Undo").performClick()

        assertEquals(listOf<UndoToast>(toast), undone)
    }

    @Test
    fun `removed toast shows Removed name`() {
        show(UndoToast.Removed("Egg", 1))

        composeRule.onNodeWithText("Removed Egg").assertExists()
        composeRule.onNodeWithText("Undo").assertExists()
    }

    @Test
    fun `toast auto-dismisses after about 4 seconds`() {
        var dismissed = 0
        show(UndoToast.Swapped("Toast", 1), onDismiss = { dismissed++ })

        composeRule.mainClock.advanceTimeBy(UNDO_TOAST_MS - 500)
        assertEquals(0, dismissed)
        composeRule.mainClock.advanceTimeBy(1_000)
        assertEquals(1, dismissed)
    }
}
