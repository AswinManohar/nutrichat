package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Surface
import androidx.compose.material3.minimumInteractiveComponentSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.icons.MealsyIcons
import app.mealsy.android.design.theme.MealsyTheme

/**
 * A small circular icon-only button with a hairline border, used for the
 * onboarding back button and the Home screen's settings gear.
 *
 * @param icon The stroked icon to draw at 15dp.
 * @param contentDescription The button's required accessibility label.
 * @param onClick Invoked when the button is tapped.
 * @param modifier The modifier applied to the button.
 * @param size The visible circle's diameter. The touch target is expanded
 *   to at least 48dp via [Modifier.minimumInteractiveComponentSize].
 */
@Composable
fun CircleIconButton(
    icon: ImageVector,
    contentDescription: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    size: Dp = 38.dp,
) {
    val colors = MealsyTheme.colors
    val interactionSource = remember { MutableInteractionSource() }
    val pressed by interactionSource.collectIsPressedAsState()
    val backgroundColor = if (pressed) colors.surface else Color.Transparent

    Surface(
        modifier =
            modifier
                .minimumInteractiveComponentSize()
                .size(size)
                .semantics { this.contentDescription = contentDescription }
                .clickable(
                    interactionSource = interactionSource,
                    indication = null,
                    onClick = onClick,
                ),
        shape = CircleShape,
        color = backgroundColor,
        border = BorderStroke(1.dp, colors.hairline),
    ) {
        Box(contentAlignment = Alignment.Center) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = colors.ink,
                modifier = Modifier.size(15.dp),
            )
        }
    }
}

@Preview(name = "CircleIconButton light", widthDp = 390)
@Composable
private fun CircleIconButtonLightPreview() {
    MealsyTheme {
        androidx.compose.material3.Surface(color = MealsyTheme.colors.canvas) {
            Row(
                modifier = Modifier.padding(20.dp),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                CircleIconButton(
                    icon = MealsyIcons.ChevronLeft,
                    contentDescription = "Back",
                    onClick = {},
                )
                CircleIconButton(
                    icon = MealsyIcons.Gear,
                    contentDescription = "Settings",
                    onClick = {},
                )
            }
        }
    }
}

@Preview(
    name = "CircleIconButton dark",
    widthDp = 390,
    uiMode = Configuration.UI_MODE_NIGHT_YES,
)
@Composable
private fun CircleIconButtonDarkPreview() {
    MealsyTheme(darkTheme = true) {
        androidx.compose.material3.Surface(color = MealsyTheme.colors.canvas) {
            CircleIconButton(
                icon = MealsyIcons.Gear,
                contentDescription = "Settings",
                onClick = {},
                modifier = Modifier.padding(20.dp),
            )
        }
    }
}
