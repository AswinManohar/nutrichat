package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.theme.MealsyShapes
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType

/**
 * A small metric tile, used in Home's 3-column macro grid (protein, carbs,
 * fat).
 *
 * @param label The metric's name, rendered muted.
 * @param value The metric's formatted value (e.g. "86g"), rendered in
 *   [MealsyType.bigNumber].
 * @param modifier The modifier applied to the card.
 */
@Composable
fun MetricCard(label: String, value: String, modifier: Modifier = Modifier) {
    val colors = MealsyTheme.colors
    Surface(
        modifier = modifier,
        shape = MealsyShapes.card,
        color = colors.surface,
    ) {
        Column(
            modifier = Modifier.padding(vertical = 13.dp, horizontal = 14.dp),
        ) {
            Text(text = label, style = MealsyType.label, color = colors.muted)
            Text(text = value, style = MealsyType.bigNumber, color = colors.ink)
        }
    }
}

@Preview(name = "MetricCard light", widthDp = 390)
@Composable
private fun MetricCardLightPreview() {
    MealsyTheme {
        androidx.compose.material3.Surface(color = MealsyTheme.colors.canvas) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(20.dp),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                MetricCard(label = "Protein", value = "86g", modifier = Modifier.weight(1f))
                MetricCard(label = "Carbs", value = "152g", modifier = Modifier.weight(1f))
                MetricCard(label = "Fat", value = "48g", modifier = Modifier.weight(1f))
            }
        }
    }
}

@Preview(
    name = "MetricCard dark",
    widthDp = 390,
    uiMode = Configuration.UI_MODE_NIGHT_YES,
)
@Composable
private fun MetricCardDarkPreview() {
    MealsyTheme(darkTheme = true) {
        androidx.compose.material3.Surface(color = MealsyTheme.colors.canvas) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(20.dp),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                MetricCard(label = "Protein", value = "86g", modifier = Modifier.weight(1f))
                MetricCard(label = "Carbs", value = "152g", modifier = Modifier.weight(1f))
                MetricCard(label = "Fat", value = "48g", modifier = Modifier.weight(1f))
            }
        }
    }
}
