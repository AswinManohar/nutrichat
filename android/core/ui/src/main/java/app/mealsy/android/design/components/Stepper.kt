package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.theme.MealsyShapes
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType

/**
 * Mealsy's gram-quantity stepper, used on food rows in the meal confirm card.
 *
 * @param value The current integer value.
 * @param onValueChange Invoked with the new value when a button is tapped.
 * @param modifier The modifier applied to the stepper's track.
 * @param step The amount to add or subtract per tap.
 * @param min The minimum allowed value; the decrease button disables here.
 * @param max The maximum allowed value; the increase button disables here.
 * @param valueLabel Formats [value] for both the visible label and the
 *   accessibility [androidx.compose.ui.semantics.stateDescription].
 */
@Composable
fun Stepper(
    value: Int,
    onValueChange: (Int) -> Unit,
    modifier: Modifier = Modifier,
    step: Int = 5,
    min: Int = 5,
    max: Int = Int.MAX_VALUE,
    valueLabel: (Int) -> String = { "$it g" },
) {
    val colors = MealsyTheme.colors
    val canDecrease = value > min
    val canIncrease = value < max

    Surface(
        modifier = modifier.semantics { stateDescription = valueLabel(value) },
        shape = MealsyShapes.pill,
        color = colors.canvas,
        border = BorderStroke(1.dp, colors.hairline),
    ) {
        Row(
            modifier = Modifier.padding(3.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            StepperButton(
                symbol = "-",
                enabled = canDecrease,
                contentDescription = "Decrease",
                onClick = { onValueChange((value - step).coerceAtLeast(min)) },
            )
            Text(
                text = valueLabel(value),
                style = MealsyType.badge.copy(fontSize = androidx.compose.ui.unit.TextUnit(
                    13f,
                    androidx.compose.ui.unit.TextUnitType.Sp,
                )),
                color = colors.ink,
                modifier = Modifier.widthIn(min = 44.dp),
                textAlign = androidx.compose.ui.text.style.TextAlign.Center,
            )
            StepperButton(
                symbol = "+",
                enabled = canIncrease,
                contentDescription = "Increase",
                onClick = { onValueChange((value + step).coerceAtMost(max)) },
            )
        }
    }
}

@Composable
private fun StepperButton(
    symbol: String,
    enabled: Boolean,
    contentDescription: String,
    onClick: () -> Unit,
) {
    val colors = MealsyTheme.colors
    val interactionSource = remember { MutableInteractionSource() }
    val pressed by interactionSource.collectIsPressedAsState()
    val background = if (pressed) colors.surfacePressed else Color.Transparent

    Box(
        modifier = Modifier
            .size(28.dp)
            .alpha(if (enabled) 1f else 0.35f)
            .background(background, androidx.compose.foundation.shape.CircleShape)
            .semantics { this.contentDescription = contentDescription }
            .clickable(
                interactionSource = interactionSource,
                indication = null,
                enabled = enabled,
                onClick = onClick,
            ),
        contentAlignment = Alignment.Center,
    ) {
        Text(text = symbol, style = MealsyType.button, color = colors.ink)
    }
}

@Preview(name = "Stepper light", widthDp = 390)
@Composable
private fun StepperLightPreview() {
    MealsyTheme {
        androidx.compose.material3.Surface(color = MealsyTheme.colors.canvas) {
            Box(modifier = Modifier.padding(20.dp)) {
                Stepper(value = 120, onValueChange = {})
            }
        }
    }
}

@Preview(
    name = "Stepper dark",
    widthDp = 390,
    uiMode = Configuration.UI_MODE_NIGHT_YES,
)
@Composable
private fun StepperDarkPreview() {
    MealsyTheme(darkTheme = true) {
        androidx.compose.material3.Surface(color = MealsyTheme.colors.canvas) {
            Box(modifier = Modifier.padding(20.dp)) {
                Stepper(value = 5, onValueChange = {}, min = 5)
            }
        }
    }
}
