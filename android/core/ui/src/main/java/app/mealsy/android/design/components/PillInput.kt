package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.theme.MealsyShapes
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType

/**
 * Mealsy's pill-shaped text input, used for onboarding's name field and the
 * chat composer.
 *
 * Built on [BasicTextField] rather than M3's `OutlinedTextField`, whose
 * internal padding and border logic fight the pill shape and focus-border
 * width change this design needs.
 *
 * @param value The current text value.
 * @param onValueChange Invoked with the new value as the user types.
 * @param modifier The modifier applied to the pill container.
 * @param placeholder Shown in `inactive` color when [value] is empty.
 * @param enabled Whether the field accepts input.
 * @param trailing An optional trailing slot (e.g. a mic or send button).
 * @param singleLine Whether the field restricts to a single line.
 * @param keyboardOptions Keyboard configuration passed to [BasicTextField].
 * @param keyboardActions Keyboard action callbacks passed to [BasicTextField].
 */
@Composable
fun PillInput(
    value: String,
    onValueChange: (String) -> Unit,
    modifier: Modifier = Modifier,
    placeholder: String = "",
    enabled: Boolean = true,
    trailing: @Composable (RowScope.() -> Unit)? = null,
    singleLine: Boolean = true,
    keyboardOptions: KeyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
    keyboardActions: KeyboardActions = KeyboardActions.Default,
) {
    val colors = MealsyTheme.colors
    var focused by remember { mutableStateOf(false) }
    val borderColor = if (focused) colors.ink else colors.hairline
    val borderWidth = if (focused) 1.5.dp else 1.dp

    Surface(
        modifier = modifier,
        shape = MealsyShapes.pill,
        color = Color.Transparent,
        border = BorderStroke(borderWidth, borderColor),
    ) {
        Row(
            modifier =
                Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 20.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            androidx.compose.foundation.layout.Box(modifier = Modifier.weight(1f)) {
                BasicTextField(
                    value = value,
                    onValueChange = onValueChange,
                    // The 15dp vertical padding lives inside the text field's
                    // own `decorationBox` (rather than on the outer `Row`) so
                    // it is part of the field's hit-box: a tap on the top or
                    // bottom of the visible pill focuses the field instead of
                    // landing in a dead zone outside it.
                    modifier =
                        Modifier
                            .fillMaxWidth()
                            .onFocusChanged { focused = it.isFocused }
                            .semantics { contentDescription = placeholder },
                    enabled = enabled,
                    singleLine = singleLine,
                    textStyle = MealsyType.button.copy(color = colors.ink),
                    cursorBrush = androidx.compose.ui.graphics.SolidColor(colors.ink),
                    keyboardOptions = keyboardOptions,
                    keyboardActions = keyboardActions,
                    interactionSource = remember { MutableInteractionSource() },
                    decorationBox = { innerTextField ->
                        androidx.compose.foundation.layout.Box(
                            modifier = Modifier.padding(vertical = 15.dp),
                        ) {
                            if (value.isEmpty()) {
                                Text(
                                    text = placeholder,
                                    style = MealsyType.button,
                                    color = colors.inactive,
                                    maxLines = if (singleLine) 1 else Int.MAX_VALUE,
                                    overflow = if (singleLine) TextOverflow.Ellipsis else TextOverflow.Clip,
                                )
                            }
                            innerTextField()
                        }
                    },
                )
            }
            if (trailing != null) {
                trailing()
            }
        }
    }
}

@Preview(name = "PillInput light", widthDp = 390)
@Composable
private fun PillInputLightPreview() {
    MealsyTheme {
        androidx.compose.material3.Surface(color = MealsyTheme.colors.canvas) {
            androidx.compose.foundation.layout.Column(
                modifier = Modifier.padding(20.dp),
                verticalArrangement = androidx.compose.foundation.layout.Arrangement.spacedBy(12.dp),
            ) {
                PillInput(value = "", onValueChange = {}, placeholder = "Your name")
                PillInput(value = "Sam", onValueChange = {}, placeholder = "Your name")
            }
        }
    }
}

@Preview(
    name = "PillInput dark",
    widthDp = 390,
    uiMode = Configuration.UI_MODE_NIGHT_YES,
)
@Composable
private fun PillInputDarkPreview() {
    MealsyTheme(darkTheme = true) {
        androidx.compose.material3.Surface(color = MealsyTheme.colors.canvas) {
            androidx.compose.foundation.layout.Column(modifier = Modifier.padding(20.dp)) {
                PillInput(value = "", onValueChange = {}, placeholder = "Your name")
            }
        }
    }
}
