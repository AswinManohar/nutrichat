package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.mealsy.android.design.theme.MealsyShapes
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType
import app.mealsy.android.design.theme.mealsyTween

/**
 * Mealsy's segmented control, used for the meal-type selector in the confirm
 * card and the portion multiplier row.
 *
 * @param T The option type.
 * @param options The full list of segments, in display order.
 * @param selected The currently selected option.
 * @param onSelect Invoked when the user taps a different segment.
 * @param modifier The modifier applied to the control's track.
 * @param label Renders the display text for a given option.
 */
@Composable
fun <T> SegmentedControl(
    options: List<T>,
    selected: T,
    onSelect: (T) -> Unit,
    modifier: Modifier = Modifier,
    label: (T) -> String,
) {
    val colors = MealsyTheme.colors
    val density = LocalDensity.current
    var trackWidthPx by remember { mutableIntStateOf(0) }
    val selectedIndex = options.indexOf(selected).coerceAtLeast(0)
    val segmentWidthDp =
        if (trackWidthPx == 0 || options.isEmpty()) {
            0.dp
        } else {
            with(density) { (trackWidthPx / options.size).toDp() }
        }
    // A single sliding thumb, rather than per-segment background color
    // animations, so the selection reads as one control moving rather than
    // four buttons independently swapping color.
    val thumbOffset by animateDpAsState(
        targetValue = segmentWidthDp * selectedIndex,
        animationSpec = mealsyTween(200),
        label = "segment-thumb-offset",
    )

    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = MealsyShapes.pill,
        color = colors.canvas,
        border = BorderStroke(1.dp, colors.hairline),
    ) {
        Box(
            modifier =
                Modifier
                    .padding(3.dp)
                    .height(IntrinsicSize.Min)
                    .onSizeChanged { trackWidthPx = it.width },
        ) {
            if (segmentWidthDp > 0.dp) {
                Box(
                    modifier =
                        Modifier
                            .offset(x = thumbOffset)
                            .width(segmentWidthDp)
                            .fillMaxHeight()
                            .background(colors.ink, MealsyShapes.pill),
                )
            }
            Row {
                options.forEach { option ->
                    val isSelected = option == selected
                    val textColor by animateColorAsState(
                        targetValue = if (isSelected) colors.canvas else colors.muted,
                        animationSpec = mealsyTween(150),
                        label = "segment-text",
                    )
                    Box(
                        modifier =
                            Modifier
                                .weight(1f)
                                .semantics {
                                    role = Role.RadioButton
                                    this.selected = isSelected
                                }
                                .clickable { onSelect(option) }
                                .padding(vertical = 8.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(
                            text = label(option),
                            style = MealsyType.badge.copy(fontSize = 13.sp),
                            color = textColor,
                        )
                    }
                }
            }
        }
    }
}

@Preview(name = "SegmentedControl light", widthDp = 390)
@Composable
private fun SegmentedControlLightPreview() {
    MealsyTheme {
        androidx.compose.material3.Surface(color = MealsyTheme.colors.canvas) {
            var selected = "Lunch"
            androidx.compose.foundation.layout.Box(modifier = Modifier.padding(20.dp)) {
                SegmentedControl(
                    options = listOf("Breakfast", "Lunch", "Dinner", "Snack"),
                    selected = selected,
                    onSelect = { selected = it },
                    label = { it },
                )
            }
        }
    }
}

@Preview(
    name = "SegmentedControl dark",
    widthDp = 390,
    uiMode = Configuration.UI_MODE_NIGHT_YES,
)
@Composable
private fun SegmentedControlDarkPreview() {
    MealsyTheme(darkTheme = true) {
        androidx.compose.material3.Surface(color = MealsyTheme.colors.canvas) {
            androidx.compose.foundation.layout.Box(modifier = Modifier.padding(20.dp)) {
                SegmentedControl(
                    options = listOf("0.5x", "1x", "1.5x", "2x"),
                    selected = "1x",
                    onSelect = {},
                    label = { it },
                )
            }
        }
    }
}
