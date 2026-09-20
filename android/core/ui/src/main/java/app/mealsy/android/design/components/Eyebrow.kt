package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType

/**
 * A small uppercase label used above section headers and dates (e.g.
 * `WEDNESDAY, AUG 6`, `CONFIRM MEAL`).
 *
 * @param text The label text; rendered uppercase regardless of input case.
 * @param modifier The modifier applied to the text.
 */
@Composable
fun Eyebrow(
    text: String,
    modifier: Modifier = Modifier,
) {
    val colors = MealsyTheme.colors
    Text(
        text = text.uppercase(),
        style = MealsyType.eyebrow,
        color = colors.muted,
        modifier = modifier,
    )
}

@Preview(name = "Eyebrow light", widthDp = 390)
@Composable
private fun EyebrowLightPreview() {
    MealsyTheme {
        androidx.compose.material3.Surface(color = MealsyTheme.colors.canvas) {
            Eyebrow(text = "Wednesday, Aug 6", modifier = Modifier.padding(20.dp))
        }
    }
}

@Preview(
    name = "Eyebrow dark",
    widthDp = 390,
    uiMode = Configuration.UI_MODE_NIGHT_YES,
)
@Composable
private fun EyebrowDarkPreview() {
    MealsyTheme(darkTheme = true) {
        androidx.compose.material3.Surface(color = MealsyTheme.colors.canvas) {
            Eyebrow(text = "Confirm meal", modifier = Modifier.padding(20.dp))
        }
    }
}
