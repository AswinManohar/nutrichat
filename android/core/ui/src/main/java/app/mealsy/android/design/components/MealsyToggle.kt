package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.theme.MealsyShapes
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.mealsyTween
import app.mealsy.android.design.theme.rememberMealsyHaptics

/**
 * Mealsy's on/off toggle switch, used for preference and settings rows.
 *
 * Built from scratch rather than M3's `Switch`, which does not expose the
 * exact track/thumb colors and sizing this design calls for.
 *
 * @param checked Whether the toggle is on.
 * @param onCheckedChange Invoked with the new checked state on tap.
 * @param modifier The modifier applied to the toggle's track.
 * @param enabled Whether the toggle responds to taps.
 * @param interactive When false, the toggle draws itself but takes no tap
 *   gesture and exposes no `Role.Switch` semantics of its own — for a caller
 *   (e.g. a settings row) that puts `Modifier.toggleable(role = Role.Switch)`
 *   on a *larger* container (the whole row, merged with its label) and only
 *   wants this composable as the visual thumb/track (#43).
 */
@Composable
fun MealsyToggle(
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    interactive: Boolean = true,
) {
    val colors = MealsyTheme.colors
    val haptics = rememberMealsyHaptics()
    val trackColor by animateColorAsState(
        targetValue = if (checked) colors.olive else colors.hairline,
        animationSpec = mealsyTween(150),
        label = "toggle-track",
    )
    val thumbOffset by animateDpAsState(
        targetValue = if (checked) 18.dp else 0.dp,
        animationSpec = mealsyTween(150),
        label = "toggle-thumb",
    )

    Box(
        modifier =
            modifier
                .size(width = 46.dp, height = 28.dp)
                .alpha(if (enabled) 1f else 0.35f)
                .then(
                    if (interactive) {
                        Modifier.toggleable(
                            value = checked,
                            enabled = enabled,
                            role = Role.Switch,
                            onValueChange = {
                                haptics.tick()
                                onCheckedChange(it)
                            },
                        )
                    } else {
                        Modifier.clearAndSetSemantics {}
                    },
                )
                .background(trackColor, MealsyShapes.pill)
                .padding(3.dp),
    ) {
        Surface(
            modifier =
                Modifier
                    .offset(x = thumbOffset)
                    .size(22.dp),
            shape = CircleShape,
            color = colors.canvas,
        ) {}
    }
}

@Preview(name = "MealsyToggle light", widthDp = 390)
@Composable
private fun MealsyToggleLightPreview() {
    MealsyTheme {
        androidx.compose.material3.Surface(color = MealsyTheme.colors.canvas) {
            androidx.compose.foundation.layout.Row(
                modifier = Modifier.padding(20.dp),
                horizontalArrangement = androidx.compose.foundation.layout.Arrangement.spacedBy(12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                MealsyToggle(checked = true, onCheckedChange = {})
                MealsyToggle(checked = false, onCheckedChange = {})
            }
        }
    }
}

@Preview(
    name = "MealsyToggle dark",
    widthDp = 390,
    uiMode = Configuration.UI_MODE_NIGHT_YES,
)
@Composable
private fun MealsyToggleDarkPreview() {
    MealsyTheme(darkTheme = true) {
        androidx.compose.material3.Surface(color = MealsyTheme.colors.canvas) {
            androidx.compose.foundation.layout.Row(
                modifier = Modifier.padding(20.dp),
                horizontalArrangement = androidx.compose.foundation.layout.Arrangement.spacedBy(12.dp),
            ) {
                MealsyToggle(checked = true, onCheckedChange = {})
                MealsyToggle(checked = false, onCheckedChange = {}, enabled = false)
            }
        }
    }
}
