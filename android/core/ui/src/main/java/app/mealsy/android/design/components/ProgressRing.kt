package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.ProgressBarRangeInfo
import androidx.compose.ui.semantics.progressBarRangeInfo
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.theme.MealsyTheme

/**
 * A ring progress indicator: an olive stroke over an `oliveTrack` track,
 * round caps, sweeping clockwise from 12 o'clock. Matches the "PROGRESS
 * RING" swatch in `Mealsy Design System.html` (96dp box, r=42, 6dp stroke).
 *
 * @param progress Fraction complete, coerced into `0f..1f`.
 * @param size Overall ring diameter. Defaults to the handoff's 96dp.
 * @param strokeWidth Ring stroke width. Defaults to the handoff's 6dp.
 * @param animate Whether [progress] changes animate (320ms). Set false for
 *   deterministic screenshot goldens.
 * @param content Optional centered content, e.g. a percentage label.
 */
@Composable
fun ProgressRing(
    progress: Float,
    modifier: Modifier = Modifier,
    size: Dp = 96.dp,
    strokeWidth: Dp = 6.dp,
    animate: Boolean = true,
    content: @Composable (BoxScope.() -> Unit)? = null,
) {
    val colors = MealsyTheme.colors
    val clamped = progress.coerceIn(0f, 1f)
    val progressState: androidx.compose.runtime.State<Float> = if (animate) {
        animateFloatAsState(
            targetValue = clamped,
            animationSpec = tween(durationMillis = 320),
            label = "progressRing",
        )
    } else {
        remember(clamped) { mutableStateOf(clamped) }
    }
    val animatedProgress by progressState

    Box(
        modifier = modifier
            .size(size)
            .semantics {
                progressBarRangeInfo = ProgressBarRangeInfo(current = clamped, range = 0f..1f)
            },
        contentAlignment = Alignment.Center,
    ) {
        Canvas(modifier = Modifier.size(size)) {
            val strokePx = strokeWidth.toPx()
            val diameter = this.size.minDimension - strokePx
            val topLeft = androidx.compose.ui.geometry.Offset(strokePx / 2f, strokePx / 2f)
            val arcSize = androidx.compose.ui.geometry.Size(diameter, diameter)

            drawArc(
                color = colors.oliveTrack,
                startAngle = -90f,
                sweepAngle = 360f,
                useCenter = false,
                topLeft = topLeft,
                size = arcSize,
                style = Stroke(width = strokePx, cap = StrokeCap.Round),
            )
            drawArc(
                color = colors.olive,
                startAngle = -90f,
                sweepAngle = 360f * animatedProgress,
                useCenter = false,
                topLeft = topLeft,
                size = arcSize,
                style = Stroke(width = strokePx, cap = StrokeCap.Round),
            )
        }
        if (content != null) {
            content()
        }
    }
}

@Preview(name = "ProgressRing light", widthDp = 390)
@Composable
private fun ProgressRingPreviewLight() {
    MealsyTheme(darkTheme = false) {
        Surface(color = MealsyTheme.colors.canvas) {
            Box(modifier = Modifier.size(150.dp), contentAlignment = Alignment.Center) {
                ProgressRing(progress = 0.72f) {
                    Text(text = "72%", color = MealsyTheme.colors.ink)
                }
            }
        }
    }
}

@Preview(name = "ProgressRing dark", widthDp = 390, uiMode = Configuration.UI_MODE_NIGHT_YES)
@Composable
private fun ProgressRingPreviewDark() {
    MealsyTheme(darkTheme = true) {
        Surface(color = MealsyTheme.colors.canvas) {
            Box(modifier = Modifier.size(150.dp), contentAlignment = Alignment.Center) {
                ProgressRing(progress = 0.72f) {
                    Text(text = "72%", color = MealsyTheme.colors.ink)
                }
            }
        }
    }
}
