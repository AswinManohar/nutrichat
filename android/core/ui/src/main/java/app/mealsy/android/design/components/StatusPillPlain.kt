package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.theme.MealsyShapes
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType

/**
 * The plain, full-olive-filled status pill from the "MEAL DETAIL" block in
 * `Mealsy Design System.html`: a 46dp pill with a solid olive fill, [label]
 * on the left and [value] on the right. Unlike [StatusPill] there is no
 * bite notch and no mascot slot — this is the flat variant used where a
 * status needs to read as a single fact rather than a remaining budget.
 *
 * @param label Left-aligned text, medium weight, e.g. "Logged at".
 * @param value Right-aligned text with tabular numerals, e.g. "8:42 AM".
 */
@Composable
fun StatusPillPlain(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
) {
    val colors = MealsyTheme.colors
    Surface(
        color = colors.olive,
        shape = MealsyShapes.pill,
        modifier = modifier
            .fillMaxWidth()
            .height(46.dp)
            .clearAndSetSemantics { contentDescription = "$label, $value" },
    ) {
        Box(modifier = Modifier.fillMaxWidth()) {
            Text(
                text = label,
                style = MealsyType.body.copy(fontWeight = FontWeight.Medium),
                color = colors.oliveText,
                modifier = Modifier
                    .align(Alignment.CenterStart)
                    .padding(start = 18.dp),
            )
            // MealsyType.body already bakes in tabular numerals
            // (`fontFeatureSettings = "tnum"`) — every Mealsy type role does.
            Text(
                text = value,
                style = MealsyType.body,
                color = colors.oliveText,
                modifier = Modifier
                    .align(Alignment.CenterEnd)
                    .padding(end = 18.dp),
            )
        }
    }
}

@Preview(name = "StatusPillPlain light", widthDp = 390)
@Composable
private fun StatusPillPlainPreviewLight() {
    MealsyTheme(darkTheme = false) {
        Surface(color = MealsyTheme.colors.canvas) {
            Box(modifier = Modifier.padding(20.dp)) {
                StatusPillPlain(label = "Logged at", value = "8:42 AM")
            }
        }
    }
}

@Preview(name = "StatusPillPlain dark", widthDp = 390, uiMode = Configuration.UI_MODE_NIGHT_YES)
@Composable
private fun StatusPillPlainPreviewDark() {
    MealsyTheme(darkTheme = true) {
        Surface(color = MealsyTheme.colors.canvas) {
            Box(modifier = Modifier.padding(20.dp)) {
                StatusPillPlain(label = "Logged at", value = "8:42 AM")
            }
        }
    }
}
