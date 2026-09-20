package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.theme.MealsyTheme

/**
 * Mealsy's calorie-goal slider (design handoff onboarding step 4).
 *
 * Built on [Slider]'s track/thumb slots so drag handling, keyboard
 * navigation, and TalkBack `setProgress` semantics come from Compose's own
 * implementation rather than a hand-rolled gesture detector.
 *
 * @param value The current integer value, e.g. a daily calorie target.
 * @param onValueChange Invoked with the new value, already rounded to the
 *   nearest [step] and coerced into [valueRange].
 * @param modifier The modifier applied to the slider's row.
 * @param valueRange The inclusive range of allowed values.
 * @param step The quantization step between adjacent stops.
 * @param enabled Whether the slider responds to input. `false` renders at
 *   35% alpha with interaction disabled.
 * @param contentDescription Accessibility label read by TalkBack, e.g.
 *   "Daily calorie goal".
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MealsySlider(
    value: Int,
    onValueChange: (Int) -> Unit,
    modifier: Modifier = Modifier,
    valueRange: IntRange = 1400..3200,
    step: Int = 50,
    enabled: Boolean = true,
    contentDescription: String? = null,
) {
    val colors = MealsyTheme.colors
    val floatRange = valueRange.first.toFloat()..valueRange.last.toFloat()
    val steps =
        remember(valueRange, step) {
            ((valueRange.last - valueRange.first) / step - 1).coerceAtLeast(0)
        }

    Slider(
        value = value.toFloat(),
        onValueChange = { raw ->
            val quantized =
                (Math.round((raw - valueRange.first) / step.toFloat()) * step) +
                    valueRange.first
            onValueChange(quantized.coerceIn(valueRange.first, valueRange.last))
        },
        valueRange = floatRange,
        steps = steps,
        enabled = enabled,
        modifier =
            modifier
                .fillMaxWidth()
                .height(28.dp)
                .alpha(if (enabled) 1f else 0.35f)
                .then(
                    if (contentDescription != null) {
                        Modifier.semantics { this.contentDescription = contentDescription }
                    } else {
                        Modifier
                    },
                ),
        track = { sliderState ->
            val fraction =
                if (sliderState.valueRange.endInclusive > sliderState.valueRange.start) {
                    (sliderState.value - sliderState.valueRange.start) /
                        (sliderState.valueRange.endInclusive - sliderState.valueRange.start)
                } else {
                    0f
                }
            Box(
                modifier =
                    Modifier
                        .fillMaxWidth()
                        .height(6.dp)
                        .background(colors.divider, CircleShape),
            ) {
                Box(
                    modifier =
                        Modifier
                            .fillMaxWidth(fraction.coerceIn(0f, 1f))
                            .height(6.dp)
                            .background(colors.olive, CircleShape),
                )
            }
        },
        thumb = {
            Surface(
                modifier =
                    Modifier
                        .padding(top = 2.dp)
                        .size(24.dp),
                shape = CircleShape,
                color = colors.canvas,
                border = androidx.compose.foundation.BorderStroke(2.dp, colors.ink),
            ) {}
        },
        colors =
            SliderDefaults.colors(
                thumbColor = colors.canvas,
                activeTrackColor = colors.olive,
                inactiveTrackColor = colors.divider,
            ),
    )
}

@Preview(name = "MealsySlider light", widthDp = 390)
@Composable
private fun MealsySliderPreviewLight() {
    MealsyTheme(darkTheme = false) {
        Surface(color = MealsyTheme.colors.canvas) {
            Box(modifier = Modifier.padding(20.dp)) {
                MealsySlider(value = 2200, onValueChange = {}, contentDescription = "Daily calorie goal")
            }
        }
    }
}

@Preview(name = "MealsySlider dark", widthDp = 390, uiMode = Configuration.UI_MODE_NIGHT_YES)
@Composable
private fun MealsySliderPreviewDark() {
    MealsyTheme(darkTheme = true) {
        Surface(color = MealsyTheme.colors.canvas) {
            Box(modifier = Modifier.padding(20.dp)) {
                MealsySlider(value = 2200, onValueChange = {}, contentDescription = "Daily calorie goal")
            }
        }
    }
}
