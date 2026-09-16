package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.theme.MealsyShapes
import app.mealsy.android.design.theme.MealsyTheme

/**
 * A thin horizontal share/progress bar for list rows (e.g. a meal's protein
 * share of the day's total).
 *
 * Purely decorative: the enclosing row is expected to carry the semantics
 * (e.g. `progressBarRangeInfo`) describing what this bar represents, so this
 * composable clears its own to avoid double-announcing to TalkBack.
 *
 * @param fraction The filled portion, coerced into `0f..1f`.
 * @param modifier The modifier applied to the bar's track. Callers
 *   typically constrain width via [Modifier.fillMaxWidth] or a fixed width.
 */
@Composable
fun ShareBar(fraction: Float, modifier: Modifier = Modifier) {
    val colors = MealsyTheme.colors
    val clamped = fraction.coerceIn(0f, 1f)

    Surface(
        modifier = modifier
            .fillMaxWidth()
            .height(4.dp)
            .clearAndSetSemantics {},
        shape = MealsyShapes.pill,
        color = colors.oliveTrack,
    ) {
        Box(modifier = Modifier.fillMaxWidth()) {
            Box(
                modifier = Modifier
                    .fillMaxHeight()
                    .fillMaxWidth(clamped)
                    .align(Alignment.CenterStart)
                    .background(colors.leaf, MealsyShapes.pill),
            )
        }
    }
}

@Preview(name = "ShareBar light", widthDp = 390)
@Composable
private fun ShareBarLightPreview() {
    MealsyTheme {
        Surface(color = MealsyTheme.colors.canvas) {
            androidx.compose.foundation.layout.Column(
                modifier = Modifier.padding(20.dp),
                verticalArrangement = androidx.compose.foundation.layout.Arrangement.spacedBy(12.dp),
            ) {
                ShareBar(fraction = 0.35f)
                ShareBar(fraction = 0.8f)
                ShareBar(fraction = 1.2f)
            }
        }
    }
}

@Preview(
    name = "ShareBar dark",
    widthDp = 390,
    uiMode = Configuration.UI_MODE_NIGHT_YES,
)
@Composable
private fun ShareBarDarkPreview() {
    MealsyTheme(darkTheme = true) {
        Surface(color = MealsyTheme.colors.canvas) {
            Box(modifier = Modifier.padding(20.dp)) {
                ShareBar(fraction = 0.6f)
            }
        }
    }
}
