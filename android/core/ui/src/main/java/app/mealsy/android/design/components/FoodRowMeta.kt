package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType

/**
 * The muted, tabular-numeral metadata line under a food name (e.g.
 * `181 kcal · 37g protein`), shared by the meal confirm card's food rows and
 * meal detail's ingredient list per README §5 item 3.
 *
 * [MealsyType.label] already bakes in tabular figures
 * (`fontFeatureSettings = "tnum"`), so no extra style work is needed here —
 * this composable exists purely so both call sites share one
 * implementation rather than duplicating the style/color pairing.
 *
 * @param text The metadata line, pre-formatted with its `·` separators by
 *   the caller (e.g. `"181 kcal · 37g protein"`).
 * @param modifier The modifier applied to the text.
 */
@Composable
fun FoodRowMeta(text: String, modifier: Modifier = Modifier) {
    val colors = MealsyTheme.colors
    Text(text = text, style = MealsyType.label, color = colors.muted, modifier = modifier)
}

@Preview(name = "FoodRowMeta light", widthDp = 390)
@Composable
private fun FoodRowMetaLightPreview() {
    MealsyTheme {
        Surface(color = MealsyTheme.colors.canvas) {
            FoodRowMeta(
                text = "181 kcal · 37g protein",
                modifier = Modifier.padding(20.dp),
            )
        }
    }
}

@Preview(
    name = "FoodRowMeta dark",
    widthDp = 390,
    uiMode = Configuration.UI_MODE_NIGHT_YES,
)
@Composable
private fun FoodRowMetaDarkPreview() {
    MealsyTheme(darkTheme = true) {
        Surface(color = MealsyTheme.colors.canvas) {
            FoodRowMeta(
                text = "181 kcal · 37g protein",
                modifier = Modifier.padding(20.dp),
            )
        }
    }
}
