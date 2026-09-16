package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import app.mealsy.android.design.theme.MealsyShapes
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType

/**
 * A hairline-outlined eyebrow pill, e.g. "IT'S EASIER TOGETHER" on the
 * onboarding welcome screen.
 *
 * @param text The pill's copy, rendered as given — callers pass
 *   already-uppercased strings.
 * @param modifier The modifier applied to the pill's container.
 */
@Composable
fun OutlinePill(text: String, modifier: Modifier = Modifier) {
    val colors = MealsyTheme.colors

    Surface(
        modifier = modifier,
        shape = MealsyShapes.pill,
        color = androidx.compose.ui.graphics.Color.Transparent,
        border = BorderStroke(1.dp, colors.hairline),
    ) {
        Text(
            text = text,
            style = MealsyType.eyebrow.copy(
                fontWeight = FontWeight.Medium,
                letterSpacing = 0.1.em,
            ),
            color = colors.muted,
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 7.dp),
        )
    }
}

@Preview(name = "OutlinePill light", widthDp = 390)
@Composable
private fun OutlinePillPreviewLight() {
    MealsyTheme(darkTheme = false) {
        Surface(color = MealsyTheme.colors.canvas) {
            Box(modifier = Modifier.padding(20.dp)) {
                OutlinePill(text = "IT'S EASIER TOGETHER")
            }
        }
    }
}

@Preview(name = "OutlinePill dark", widthDp = 390, uiMode = Configuration.UI_MODE_NIGHT_YES)
@Composable
private fun OutlinePillPreviewDark() {
    MealsyTheme(darkTheme = true) {
        Surface(color = MealsyTheme.colors.canvas) {
            Box(modifier = Modifier.padding(20.dp)) {
                OutlinePill(text = "IT'S EASIER TOGETHER")
            }
        }
    }
}
