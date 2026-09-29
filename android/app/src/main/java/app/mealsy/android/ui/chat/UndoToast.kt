package app.mealsy.android.ui.chat

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import app.mealsy.android.R
import app.mealsy.android.design.theme.MealsyShapes
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType
import app.mealsy.android.design.theme.rememberMealsyHaptics
import kotlinx.coroutines.delay

/**
 * An undoable card edit the chat screen offers a toast for. [token] is unique
 * per edit so two edits of the same food still restart the toast timer.
 */
sealed interface UndoToast {
    val name: String
    val token: Long

    /** "Swapped to [name]" — Undo calls [ChatSessionStore.undoSwap]. */
    data class Swapped(override val name: String, override val token: Long) : UndoToast

    /** "Removed [name]" — Undo calls [ChatSessionStore.undoRemove]. */
    data class Removed(override val name: String, override val token: Long) : UndoToast
}

/** How long the swap/remove undo toast stays visible before it auto-dismisses. */
internal const val UNDO_TOAST_MS = 4_000L

/**
 * The chat-level "Swapped to X" / "Removed X" toast with an **Undo** action
 * (spec 003 FR-006; #46). Rendered by the chat screen from
 * [ChatSessionStore.undoToast] so it survives the confirm card recomposing
 * or being dropped (removing a card's last item). A new toast (different
 * `token`) restarts the [UNDO_TOAST_MS] timer; a swap also fires the confirm
 * haptic.
 *
 * @param toast The toast to show.
 * @param onUndo Called when Undo is tapped (the toast is dismissed by the
 *   store's undo call).
 * @param onDismiss Called when the timer elapses.
 */
@Composable
internal fun ChatUndoToast(
    toast: UndoToast,
    onUndo: (UndoToast) -> Unit,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val colors = MealsyTheme.colors
    val haptics = rememberMealsyHaptics()
    LaunchedEffect(toast.token) {
        if (toast is UndoToast.Swapped) haptics.confirm()
        delay(UNDO_TOAST_MS)
        onDismiss()
    }
    val text =
        when (toast) {
            is UndoToast.Swapped -> stringResource(R.string.confirm_card_swapped_to, toast.name)
            is UndoToast.Removed -> stringResource(R.string.confirm_card_removed, toast.name)
        }
    Surface(shape = MealsyShapes.pill, color = colors.ink, modifier = modifier) {
        Row(
            modifier = Modifier.padding(vertical = 12.dp, horizontal = 18.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(text = text, style = MealsyType.badge, color = colors.canvas)
            Text(
                text = stringResource(R.string.confirm_card_undo),
                style = MealsyType.badge.copy(textDecoration = TextDecoration.Underline),
                color = colors.olive,
                modifier = Modifier.clickable { onUndo(toast) },
            )
        }
    }
}
