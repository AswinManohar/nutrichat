package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.theme.MealsyShapes
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType

/**
 * The visual style variants for [MealsyButton], mirroring the "Buttons"
 * section of the Mealsy component library.
 */
enum class MealsyButtonStyle {
    /** Ink background, cream text. The default call-to-action style. */
    Primary,

    /** Transparent background with a hairline border, ink text. */
    Secondary,

    /** Terracotta background, terracotta text, for destructive actions. */
    Destructive,

    /** Transparent background with a border, terracotta outline text. */
    DestructiveOutline,
}

/**
 * Mealsy's pill-shaped call-to-action button, used across onboarding, the
 * meal confirm card, and meal detail screens.
 *
 * Pressed-state colors are implemented manually via
 * [MutableInteractionSource] rather than M3's `Button`, since M3 does not
 * expose the pressed-background colors this design requires.
 *
 * @param text The button label.
 * @param onClick Invoked when the button is tapped, while [enabled].
 * @param modifier The modifier to apply to the button's root container.
 * @param style Which visual variant to render.
 * @param enabled Whether the button responds to taps. Disabled buttons
 *   render at 0.35 alpha.
 * @param leadingIcon An optional icon shown before the text.
 * @param contentDescription An optional override for the button's
 *   accessibility label. Defaults to [text].
 */
@Composable
fun MealsyButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    style: MealsyButtonStyle = MealsyButtonStyle.Primary,
    enabled: Boolean = true,
    leadingIcon: ImageVector? = null,
    contentDescription: String? = null,
) {
    val colors = MealsyTheme.colors
    val interactionSource = remember { MutableInteractionSource() }
    val pressed by interactionSource.collectIsPressedAsState()

    val backgroundColor =
        when (style) {
            MealsyButtonStyle.Primary -> if (pressed) colors.inkPressed else colors.ink
            MealsyButtonStyle.Secondary -> if (pressed) colors.surface else Color.Transparent
            MealsyButtonStyle.Destructive -> colors.terracotta
            MealsyButtonStyle.DestructiveOutline -> Color.Transparent
        }
    val textColor =
        when (style) {
            MealsyButtonStyle.Primary -> colors.canvas
            MealsyButtonStyle.Secondary -> colors.ink
            MealsyButtonStyle.Destructive -> colors.terracottaText
            MealsyButtonStyle.DestructiveOutline -> colors.terracottaOutlineText
        }
    val border =
        when (style) {
            MealsyButtonStyle.Secondary -> BorderStroke(1.dp, colors.hairline)
            MealsyButtonStyle.DestructiveOutline -> BorderStroke(1.dp, colors.terracottaOutlineText)
            else -> null
        }

    Surface(
        modifier =
            modifier
                .height(50.dp)
                .alpha(if (enabled) 1f else 0.35f)
                .semantics { this.contentDescription = contentDescription ?: text }
                .clickable(
                    interactionSource = interactionSource,
                    indication = null,
                    enabled = enabled,
                    onClick = onClick,
                ),
        shape = MealsyShapes.pill,
        color = backgroundColor,
        border = border,
    ) {
        Row(
            modifier =
                Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 20.dp),
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (leadingIcon != null) {
                androidx.compose.material3.Icon(
                    imageVector = leadingIcon,
                    contentDescription = null,
                    tint = textColor,
                    modifier = Modifier.size(18.dp),
                )
                Box(modifier = Modifier.size(8.dp))
            }
            Text(text = text, style = MealsyType.button, color = textColor)
        }
    }
}

@Preview(name = "MealsyButton light", widthDp = 390)
@Composable
private fun MealsyButtonLightPreview() {
    MealsyTheme {
        androidx.compose.material3.Surface(color = MealsyTheme.colors.canvas) {
            Column()
        }
    }
}

@Composable
private fun Column() {
    androidx.compose.foundation.layout.Column(
        modifier =
            Modifier
                .fillMaxWidth()
                .padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        MealsyButton(text = "Get started", onClick = {}, style = MealsyButtonStyle.Primary)
        MealsyButton(
            text = "I already have an account",
            onClick = {},
            style = MealsyButtonStyle.Secondary,
        )
        MealsyButton(text = "Delete meal", onClick = {}, style = MealsyButtonStyle.Destructive)
        MealsyButton(
            text = "Cancel",
            onClick = {},
            style = MealsyButtonStyle.DestructiveOutline,
        )
        MealsyButton(text = "Disabled", onClick = {}, enabled = false)
    }
}

@Preview(
    name = "MealsyButton dark",
    widthDp = 390,
    uiMode = Configuration.UI_MODE_NIGHT_YES,
)
@Composable
private fun MealsyButtonDarkPreview() {
    MealsyTheme(darkTheme = true) {
        androidx.compose.material3.Surface(color = MealsyTheme.colors.canvas) {
            Column()
        }
    }
}
