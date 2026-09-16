package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.selection.toggleable
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.theme.MealsyShapes
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType

/**
 * A multi-select filter chip, used for onboarding's dietary-preference
 * picker (Vegetarian, Vegan, No dairy, etc.).
 *
 * @param text The chip's label.
 * @param selected Whether this chip is currently selected.
 * @param onClick Invoked when the chip is tapped, toggling [selected].
 * @param modifier The modifier applied to the chip.
 */
@Composable
fun FilterChipPill(
    text: String,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val colors = MealsyTheme.colors
    val backgroundColor by animateColorAsState(
        targetValue = if (selected) colors.ink else Color.Transparent,
        animationSpec = tween(150),
        label = "filter-chip-bg",
    )
    val textColor by animateColorAsState(
        targetValue = if (selected) colors.canvas else colors.ink,
        animationSpec = tween(150),
        label = "filter-chip-text",
    )

    Surface(
        modifier = modifier.toggleable(
            value = selected,
            role = Role.Checkbox,
            onValueChange = { onClick() },
        ),
        shape = MealsyShapes.pill,
        color = backgroundColor,
        border = if (selected) null else BorderStroke(1.dp, colors.hairline),
    ) {
        Text(
            text = text,
            style = MealsyType.badge.copy(fontSize = androidx.compose.ui.unit.TextUnit(
                13f,
                androidx.compose.ui.unit.TextUnitType.Sp,
            )),
            color = textColor,
            modifier = Modifier.padding(vertical = 10.dp, horizontal = 17.dp),
        )
    }
}

@Preview(name = "FilterChipPill light", widthDp = 390)
@Composable
private fun FilterChipPillLightPreview() {
    MealsyTheme {
        androidx.compose.material3.Surface(color = MealsyTheme.colors.canvas) {
            androidx.compose.foundation.layout.Row(
                modifier = Modifier.padding(20.dp),
                horizontalArrangement = androidx.compose.foundation.layout.Arrangement.spacedBy(8.dp),
            ) {
                FilterChipPill(text = "Vegetarian", selected = true, onClick = {})
                FilterChipPill(text = "No dairy", selected = false, onClick = {})
            }
        }
    }
}

@Preview(
    name = "FilterChipPill dark",
    widthDp = 390,
    uiMode = Configuration.UI_MODE_NIGHT_YES,
)
@Composable
private fun FilterChipPillDarkPreview() {
    MealsyTheme(darkTheme = true) {
        androidx.compose.material3.Surface(color = MealsyTheme.colors.canvas) {
            FilterChipPill(
                text = "No gluten",
                selected = false,
                onClick = {},
                modifier = Modifier.padding(20.dp),
            )
        }
    }
}
