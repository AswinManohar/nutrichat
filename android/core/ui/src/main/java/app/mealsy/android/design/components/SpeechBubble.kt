package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType

/**
 * Olli's onboarding speech bubble (design handoff welcome markup).
 *
 * A `surface`-colored bubble with one squared corner (bottom-start) so it
 * reads as pointing down toward the mascot.
 *
 * @param text The bubble's copy, rendered as given (callers pass
 *   already-uppercased strings where the design calls for it).
 * @param modifier The modifier applied to the bubble's container.
 */
@Composable
fun SpeechBubble(
    text: String,
    modifier: Modifier = Modifier,
) {
    val colors = MealsyTheme.colors
    val shape =
        RoundedCornerShape(
            topStart = 16.dp,
            topEnd = 16.dp,
            bottomEnd = 16.dp,
            bottomStart = 4.dp,
        )

    Surface(
        modifier = modifier,
        shape = shape,
        color = colors.surface,
    ) {
        Text(
            text = text,
            style =
                MealsyType.label.copy(
                    fontWeight = FontWeight.Medium,
                    letterSpacing = 0.06.em,
                ),
            color = colors.ink,
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 9.dp),
        )
    }
}

@Preview(name = "SpeechBubble light", widthDp = 390)
@Composable
private fun SpeechBubblePreviewLight() {
    MealsyTheme(darkTheme = false) {
        Surface(color = MealsyTheme.colors.canvas) {
            androidx.compose.foundation.layout.Box(modifier = Modifier.padding(20.dp)) {
                SpeechBubble(text = "HI, I'M OLLI")
            }
        }
    }
}

@Preview(name = "SpeechBubble dark", widthDp = 390, uiMode = Configuration.UI_MODE_NIGHT_YES)
@Composable
private fun SpeechBubblePreviewDark() {
    MealsyTheme(darkTheme = true) {
        Surface(color = MealsyTheme.colors.canvas) {
            androidx.compose.foundation.layout.Box(modifier = Modifier.padding(20.dp)) {
                SpeechBubble(text = "HI, I'M OLLI")
            }
        }
    }
}
