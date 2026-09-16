package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Icon
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.icons.MealsyIcons
import app.mealsy.android.design.theme.MealsyShapes
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType
import app.mealsy.android.design.theme.motionDurationMs

/**
 * A short-lived confirmation toast, e.g. `Quick log opened` after tapping
 * the Home FAB.
 *
 * The caller is responsible for positioning this above the bottom nav pill
 * (e.g. via a `Box` overlay with bottom padding) and for driving [visible]
 * off after a delay.
 *
 * @param text The toast's message.
 * @param modifier The modifier applied to the toast's pill.
 * @param visible Whether the toast is shown; toggling animates a
 *   slide-up + fade over 250ms.
 */
@Composable
fun InkToast(text: String, modifier: Modifier = Modifier, visible: Boolean = true) {
    val colors = MealsyTheme.colors
    val durationMs = motionDurationMs(250)
    AnimatedVisibility(
        visible = visible,
        enter = slideInVertically(animationSpec = tween(durationMs)) { it / 2 } + fadeIn(tween(durationMs)),
        exit = slideOutVertically(animationSpec = tween(durationMs)) { it / 2 } + fadeOut(tween(durationMs)),
        modifier = modifier,
    ) {
        Surface(
            shape = MealsyShapes.pill,
            color = colors.ink,
            modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
        ) {
            Row(
                modifier = Modifier.padding(vertical = 12.dp, horizontal = 18.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = androidx.compose.foundation.layout.Arrangement.spacedBy(8.dp),
            ) {
                Icon(
                    imageVector = MealsyIcons.Check,
                    contentDescription = null,
                    tint = colors.olive,
                    modifier = Modifier.size(15.dp),
                )
                Text(text = text, style = MealsyType.badge, color = colors.canvas)
            }
        }
    }
}

@Preview(name = "InkToast light", widthDp = 390)
@Composable
private fun InkToastLightPreview() {
    MealsyTheme {
        androidx.compose.material3.Surface(color = MealsyTheme.colors.canvas) {
            InkToast(text = "Quick log opened", modifier = Modifier.padding(20.dp))
        }
    }
}

@Preview(
    name = "InkToast dark",
    widthDp = 390,
    uiMode = Configuration.UI_MODE_NIGHT_YES,
)
@Composable
private fun InkToastDarkPreview() {
    MealsyTheme(darkTheme = true) {
        androidx.compose.material3.Surface(color = MealsyTheme.colors.canvas) {
            InkToast(text = "Quick log opened", modifier = Modifier.padding(20.dp))
        }
    }
}
