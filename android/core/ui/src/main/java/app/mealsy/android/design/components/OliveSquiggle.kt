package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Matrix
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.vector.PathParser
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.theme.MealsyTheme

/** The squiggle's path data from the onboarding welcome markup, 120x12 viewBox. */
private const val SQUIGGLE_PATH =
    "M2 8c10-6 20 6 30 0s20 6 30 0 20 6 30 0 16 4 26 0"

/** The squiggle's source viewBox dimensions. */
private const val VIEWBOX_WIDTH = 120f
private const val VIEWBOX_HEIGHT = 12f

/**
 * The olive decorative squiggle from the onboarding welcome screen — a
 * hand-drawn wave rendered from the design handoff's inline SVG path.
 *
 * Purely decorative: excluded from the accessibility tree.
 *
 * @param modifier The modifier applied to the squiggle's canvas.
 */
@Composable
fun OliveSquiggle(modifier: Modifier = Modifier) {
    val colors = MealsyTheme.colors
    val path = remember { PathParser().parsePathString(SQUIGGLE_PATH).toPath() }

    Canvas(
        modifier = modifier
            .size(width = 120.dp, height = 12.dp)
            .clearAndSetSemantics {},
    ) {
        val scaleX = size.width / VIEWBOX_WIDTH
        val scaleY = size.height / VIEWBOX_HEIGHT
        val scaledPath = androidx.compose.ui.graphics.Path().apply {
            addPath(path)
            transform(
                Matrix().apply { scale(x = scaleX, y = scaleY) },
            )
        }
        drawPath(
            path = scaledPath,
            color = colors.olive,
            style = Stroke(width = 3.dp.toPx(), cap = StrokeCap.Round),
        )
    }
}

@Preview(name = "OliveSquiggle light", widthDp = 390)
@Composable
private fun OliveSquigglePreviewLight() {
    MealsyTheme(darkTheme = false) {
        Surface(color = MealsyTheme.colors.canvas) {
            Box(modifier = Modifier.padding(20.dp)) {
                OliveSquiggle()
            }
        }
    }
}

@Preview(name = "OliveSquiggle dark", widthDp = 390, uiMode = Configuration.UI_MODE_NIGHT_YES)
@Composable
private fun OliveSquigglePreviewDark() {
    MealsyTheme(darkTheme = true) {
        Surface(color = MealsyTheme.colors.canvas) {
            Box(modifier = Modifier.padding(20.dp)) {
                OliveSquiggle()
            }
        }
    }
}
