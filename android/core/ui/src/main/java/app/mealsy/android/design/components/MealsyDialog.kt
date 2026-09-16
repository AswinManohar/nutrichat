package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import app.mealsy.android.design.theme.MealsyShapes
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType

/**
 * Mealsy's themed replacement for M3's `AlertDialog`.
 *
 * Built directly on [Dialog] rather than `AlertDialog`, since M3's dialog
 * hardcodes an elevated `Surface` with a shadow this design never allows —
 * every element here is flat except the app's FAB.
 *
 * @param onDismissRequest Invoked when the user taps outside the dialog or
 *   presses back.
 * @param title The dialog's heading, rendered in [MealsyType.section].
 * @param modifier The modifier applied to the dialog's surface.
 * @param body Optional supporting copy, rendered in [MealsyType.body] /
 *   `muted`, below [title].
 * @param content An optional arbitrary slot below [body] (e.g. a
 *   [PillInput] for a rename/confirm dialog).
 * @param buttons The dialog's action row, stacked vertically full-width
 *   (e.g. a [MealsyButton] pair) — callers control order and count.
 */
@Composable
fun MealsyDialog(
    onDismissRequest: () -> Unit,
    title: String,
    modifier: Modifier = Modifier,
    body: String? = null,
    content: (@Composable ColumnScope.() -> Unit)? = null,
    buttons: @Composable ColumnScope.() -> Unit,
) {
    val colors = MealsyTheme.colors
    Dialog(onDismissRequest = onDismissRequest) {
        Surface(
            modifier = modifier
                .fillMaxWidth()
                .semantics { contentDescription = title },
            shape = MealsyShapes.card,
            color = colors.surface,
            tonalElevation = 0.dp,
            shadowElevation = 0.dp,
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(24.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Text(text = title, style = MealsyType.section, color = colors.ink)
                if (body != null) {
                    Text(text = body, style = MealsyType.body, color = colors.muted)
                }
                content?.invoke(this)
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = 6.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                    content = buttons,
                )
            }
        }
    }
}

@Preview(name = "MealsyDialog light", widthDp = 390, heightDp = 600)
@Composable
private fun MealsyDialogLightPreview() {
    MealsyTheme {
        Surface(color = MealsyTheme.colors.canvas) {
            MealsyDialog(
                onDismissRequest = {},
                title = "Delete this meal",
                body = "This removes it from today's log. This can't be undone.",
                buttons = {
                    MealsyButton(text = "Delete", onClick = {}, style = MealsyButtonStyle.Destructive)
                    MealsyButton(
                        text = "Cancel",
                        onClick = {},
                        style = MealsyButtonStyle.Secondary,
                    )
                },
            )
        }
    }
}

@Preview(
    name = "MealsyDialog dark",
    widthDp = 390,
    heightDp = 600,
    uiMode = Configuration.UI_MODE_NIGHT_YES,
)
@Composable
private fun MealsyDialogDarkPreview() {
    MealsyTheme(darkTheme = true) {
        Surface(color = MealsyTheme.colors.canvas) {
            MealsyDialog(
                onDismissRequest = {},
                title = "Rename meal",
                content = {
                    PillInput(value = "Lunch", onValueChange = {}, placeholder = "Meal name")
                },
                buttons = {
                    MealsyButton(text = "Save", onClick = {}, style = MealsyButtonStyle.Primary)
                },
            )
        }
    }
}
