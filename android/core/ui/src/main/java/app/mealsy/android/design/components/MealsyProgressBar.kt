package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.ProgressBarRangeInfo
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.progressBarRangeInfo
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.theme.MealsyShapes
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.mealsyTween

/**
 * A flat linear progress bar used on onboarding step headers.
 *
 * Matches the onboarding markup: a 6dp-tall `oliveTrack` track with an
 * `olive` fill, both fully rounded ([MealsyShapes.pill]).
 *
 * @param progress Fraction complete, coerced into `0f..1f`.
 * @param modifier The modifier applied to the bar's row.
 * @param animate Whether width changes animate (350ms ease). Set `false`
 *   for deterministic screenshot goldens — the width must render instantly.
 * @param contentDescription Accessibility label, e.g. "Step 2 of 4". When
 *   `null`, the bar is treated as purely decorative and excluded from the
 *   accessibility tree.
 */
@Composable
fun MealsyProgressBar(
    progress: Float,
    modifier: Modifier = Modifier,
    animate: Boolean = true,
    contentDescription: String? = null,
) {
    val colors = MealsyTheme.colors
    val clamped = progress.coerceIn(0f, 1f)
    val animatedProgress by if (animate) {
        animateFloatAsState(
            targetValue = clamped,
            animationSpec = mealsyTween(durationMillis = 350, easing = FastOutSlowInEasing),
            label = "mealsyProgressBar",
        )
    } else {
        remember(clamped) { mutableStateOf(clamped) }
    }

    Box(
        modifier = modifier
            .fillMaxWidth()
            .height(6.dp)
            .background(colors.oliveTrack, MealsyShapes.pill)
            .then(
                if (contentDescription != null) {
                    Modifier.semantics {
                        this.contentDescription = contentDescription
                        progressBarRangeInfo = ProgressBarRangeInfo(current = clamped, range = 0f..1f)
                    }
                } else {
                    Modifier.clearAndSetSemantics {}
                },
            ),
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth(animatedProgress)
                .height(6.dp)
                .background(colors.olive, MealsyShapes.pill),
        )
    }
}

@Preview(name = "MealsyProgressBar light", widthDp = 390)
@Composable
private fun MealsyProgressBarPreviewLight() {
    MealsyTheme(darkTheme = false) {
        Surface(color = MealsyTheme.colors.canvas) {
            Box(modifier = Modifier.height(40.dp).fillMaxWidth()) {
                MealsyProgressBar(progress = 0.5f, animate = false, contentDescription = "Step 2 of 4")
            }
        }
    }
}

@Preview(name = "MealsyProgressBar dark", widthDp = 390, uiMode = Configuration.UI_MODE_NIGHT_YES)
@Composable
private fun MealsyProgressBarPreviewDark() {
    MealsyTheme(darkTheme = true) {
        Surface(color = MealsyTheme.colors.canvas) {
            Box(modifier = Modifier.height(40.dp).fillMaxWidth()) {
                MealsyProgressBar(progress = 0.5f, animate = false, contentDescription = "Step 2 of 4")
            }
        }
    }
}
