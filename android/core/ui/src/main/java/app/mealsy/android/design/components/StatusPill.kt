package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.State
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.theme.MealsyShapes
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType
import kotlin.math.roundToInt

/**
 * The signature "snack bar" status pill: a 46dp track showing how much of a
 * daily budget remains, with an olive block anchored to the right whose
 * left edge has a three-circle "bite" cut into it, and an optional mascot
 * slot floating above the bite point.
 *
 * This is the ONE olive element allowed on a screen per the Mealsy design
 * system (`android/CLAUDE.md`) — never pair it with another full-width
 * olive fill on the same screen.
 *
 * Used on Home (`Mealsy Design System.html` -> "HOME") and Meal detail
 * (-> "MEAL DETAIL").
 *
 * @param eatenLabel Text at the pill's start, e.g. "1,340 kcal eaten".
 * @param stateLabel Text at the pill's end, e.g. "560 left".
 * @param eatenFraction Fraction of the daily budget eaten so far, coerced
 *   into `0f..1f`. The olive block's width is the *remaining* fraction.
 * @param mascot Optional slot for Olli (owned by `design.mascot`), rendered
 *   at 46dp, positioned above the bite point offset -55% of its own width.
 * @param animate Whether the olive block's width animates on change (320ms
 *   ease-out). Set false for deterministic screenshot goldens.
 */
@Composable
fun StatusPill(
    eatenLabel: String,
    stateLabel: String,
    eatenFraction: Float,
    modifier: Modifier = Modifier,
    mascot: @Composable (() -> Unit)? = null,
    animate: Boolean = true,
) {
    val colors = MealsyTheme.colors
    val clampedEaten = eatenFraction.coerceIn(0f, 1f)
    val targetRemaining = 1f - clampedEaten
    val remainingState: State<Float> = if (animate) {
        animateFloatAsState(
            targetValue = targetRemaining,
            animationSpec = tween(durationMillis = 320),
            label = "statusPillRemaining",
        )
    } else {
        remember(targetRemaining) { mutableStateOf(targetRemaining) }
    }
    val remainingFraction by remainingState

    BoxWithConstraints(modifier = modifier.fillMaxWidth()) {
        val oliveWidthDp = maxWidth * remainingFraction
        val biteXDp = maxWidth - oliveWidthDp

        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(46.dp)
                .clip(MealsyShapes.pill)
                .background(colors.oliveTrack)
                .clearAndSetSemantics { contentDescription = "$eatenLabel, $stateLabel" },
        ) {
            // Olive remainder block, anchored to the right edge.
            Box(
                modifier = Modifier
                    .align(Alignment.CenterEnd)
                    .fillMaxHeight()
                    .width(oliveWidthDp)
                    .background(colors.olive),
            )

            // The three-circle "bite" cut into the olive block's left edge.
            Canvas(modifier = Modifier.fillMaxSize()) {
                val biteX = size.width - oliveWidthDp.toPx()
                val biteY = size.height / 2f
                val radii = listOf(7.dp.toPx(), 8.dp.toPx(), 6.dp.toPx())
                val offsetsY = listOf(-10.dp.toPx(), 0f, 10.dp.toPx())
                radii.forEachIndexed { index, r ->
                    drawCircle(
                        color = colors.oliveTrack,
                        radius = r,
                        center = Offset(biteX, (biteY + offsetsY[index]).coerceIn(r, size.height - r)),
                    )
                }
            }

            Text(
                text = eatenLabel,
                style = MealsyType.body.copy(fontWeight = FontWeight.Medium),
                color = colors.oliveText,
                modifier = Modifier
                    .align(Alignment.CenterStart)
                    .padding(start = 18.dp),
            )
            Text(
                text = stateLabel,
                style = MealsyType.body,
                color = colors.oliveText,
                modifier = Modifier
                    .align(Alignment.CenterEnd)
                    .padding(end = 18.dp),
            )

            if (mascot != null) {
                val mascotSize = 46.dp
                Box(
                    modifier = Modifier
                        .align(Alignment.CenterStart)
                        .offset {
                            val biteXPx = biteXDp.toPx()
                            val mascotPx = mascotSize.toPx()
                            IntOffset(
                                x = (biteXPx - mascotPx * 0.55f).roundToInt(),
                                y = -(mascotPx * 0.65f).roundToInt(),
                            )
                        },
                ) {
                    Box(modifier = Modifier.height(mascotSize)) { mascot() }
                }
            }
        }
    }
}

/**
 * The "awareness only" [StatusPill] variant, used when there is no daily
 * calorie target (mindful tracking mode): a full [MealsyTheme.colors.oliveTrack]
 * track with no olive remainder block and no bite.
 *
 * @param eatenLabel The single line of text shown, e.g. "1,340 kcal logged today".
 */
@Composable
fun StatusPillAwareness(
    eatenLabel: String,
    modifier: Modifier = Modifier,
) {
    val colors = MealsyTheme.colors
    Surface(
        color = colors.oliveTrack,
        shape = MealsyShapes.pill,
        modifier = modifier
            .fillMaxWidth()
            .height(46.dp)
            .clearAndSetSemantics { contentDescription = eatenLabel },
    ) {
        Box(modifier = Modifier.fillMaxSize()) {
            Text(
                text = eatenLabel,
                style = MealsyType.body.copy(fontWeight = FontWeight.Medium),
                color = colors.oliveText,
                modifier = Modifier
                    .align(Alignment.CenterStart)
                    .padding(start = 18.dp),
            )
        }
    }
}

@Preview(name = "StatusPill light", widthDp = 390)
@Composable
private fun StatusPillPreviewLight() {
    MealsyTheme(darkTheme = false) {
        Surface(color = MealsyTheme.colors.canvas) {
            Box(modifier = Modifier.padding(20.dp)) {
                StatusPill(eatenLabel = "1,340 kcal eaten", stateLabel = "560 left", eatenFraction = 0.7f)
            }
        }
    }
}

@Preview(name = "StatusPill dark", widthDp = 390, uiMode = Configuration.UI_MODE_NIGHT_YES)
@Composable
private fun StatusPillPreviewDark() {
    MealsyTheme(darkTheme = true) {
        Surface(color = MealsyTheme.colors.canvas) {
            Box(modifier = Modifier.padding(20.dp)) {
                StatusPill(eatenLabel = "1,340 kcal eaten", stateLabel = "560 left", eatenFraction = 0.7f)
            }
        }
    }
}

@Preview(name = "StatusPillAwareness light", widthDp = 390)
@Composable
private fun StatusPillAwarenessPreviewLight() {
    MealsyTheme(darkTheme = false) {
        Surface(color = MealsyTheme.colors.canvas) {
            Box(modifier = Modifier.padding(20.dp)) {
                StatusPillAwareness(eatenLabel = "1,340 kcal logged today")
            }
        }
    }
}

@Preview(name = "StatusPillAwareness dark", widthDp = 390, uiMode = Configuration.UI_MODE_NIGHT_YES)
@Composable
private fun StatusPillAwarenessPreviewDark() {
    MealsyTheme(darkTheme = true) {
        Surface(color = MealsyTheme.colors.canvas) {
            Box(modifier = Modifier.padding(20.dp)) {
                StatusPillAwareness(eatenLabel = "1,340 kcal logged today")
            }
        }
    }
}
