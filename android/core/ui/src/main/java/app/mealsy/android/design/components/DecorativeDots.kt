package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.theme.MealsyTheme

/**
 * The four pastel ornament dots scattered across the onboarding welcome
 * screen (design handoff welcome markup).
 *
 * Positioned against the full screen container — callers place this inside
 * a `Box(Modifier.fillMaxSize())` behind their padded screen content, since
 * offsets are measured from the screen edges, not from any content inset.
 *
 * Purely decorative: excluded from the accessibility tree.
 *
 * @param modifier The modifier applied to the dots' containing box.
 */
@Composable
fun DecorativeDots(modifier: Modifier = Modifier) {
    val colors = MealsyTheme.colors

    Box(
        modifier = modifier
            .fillMaxSize()
            .clearAndSetSemantics {},
    ) {
        Dot(
            color = colors.butter,
            size = 8.dp,
            alignment = Alignment.TopStart,
            offsetX = 36.dp,
            offsetY = 88.dp,
        )
        Dot(
            color = colors.pink,
            size = 6.dp,
            alignment = Alignment.TopEnd,
            offsetX = (-52).dp,
            offsetY = 120.dp,
        )
        Dot(
            color = colors.powder,
            size = 8.dp,
            alignment = Alignment.TopEnd,
            offsetX = (-30).dp,
            offsetY = 270.dp,
        )
        Dot(
            color = colors.leaf,
            size = 6.dp,
            alignment = Alignment.TopStart,
            offsetX = 28.dp,
            offsetY = 330.dp,
        )
    }
}

@Composable
private fun BoxScope.Dot(
    color: androidx.compose.ui.graphics.Color,
    size: androidx.compose.ui.unit.Dp,
    alignment: Alignment,
    offsetX: androidx.compose.ui.unit.Dp,
    offsetY: androidx.compose.ui.unit.Dp,
) {
    Box(
        modifier = Modifier
            .align(alignment)
            .offset(x = offsetX, y = offsetY)
            .size(size)
            .background(color, CircleShape),
    )
}

@Preview(name = "DecorativeDots light", widthDp = 390, heightDp = 400)
@Composable
private fun DecorativeDotsPreviewLight() {
    MealsyTheme(darkTheme = false) {
        Surface(color = MealsyTheme.colors.canvas) {
            Box(modifier = Modifier.size(390.dp, 400.dp)) {
                DecorativeDots()
            }
        }
    }
}

@Preview(name = "DecorativeDots dark", widthDp = 390, heightDp = 400, uiMode = Configuration.UI_MODE_NIGHT_YES)
@Composable
private fun DecorativeDotsPreviewDark() {
    MealsyTheme(darkTheme = true) {
        Surface(color = MealsyTheme.colors.canvas) {
            Box(modifier = Modifier.size(390.dp, 400.dp)) {
                DecorativeDots()
            }
        }
    }
}
