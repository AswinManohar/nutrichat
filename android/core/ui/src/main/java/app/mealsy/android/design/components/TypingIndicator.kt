package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalInspectionMode
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.theme.MealsyTheme

/**
 * The coach's "typing" indicator: three 6dp `inactive` dots at staggered
 * opacities (1.0 / 0.7 / 0.4), animating in a calm, non-bouncy loop, drawn
 * inside a coach-shaped bubble. Shown in the chat message list while
 * awaiting a reply (`Mealsy Design System.html` -> "AI COACH CHAT").
 *
 * Renders with static opacities (no animation) whenever
 * [LocalInspectionMode] is true, so `@Preview`s and screenshot goldens stay
 * deterministic.
 */
@Composable
fun TypingIndicator(modifier: Modifier = Modifier) {
    val colors = MealsyTheme.colors
    val isPreview = LocalInspectionMode.current

    val transition = rememberInfiniteTransition(label = "typingIndicator")
    val phase by transition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec =
            infiniteRepeatable(
                animation = tween(durationMillis = 1200),
                repeatMode = RepeatMode.Reverse,
            ),
        label = "typingIndicatorPhase",
    )

    val baseAlphas = listOf(1.0f, 0.7f, 0.4f)
    val alphas =
        if (isPreview) {
            baseAlphas
        } else {
            // Stagger by rotating which dot currently holds the brightest slot.
            listOf(
                baseAlphas[0] * (0.6f + 0.4f * phase),
                baseAlphas[1] * (0.6f + 0.4f * (1f - phase)),
                baseAlphas[2],
            )
        }

    Surface(
        color = colors.surface,
        shape = RoundedCornerShape(topStart = 18.dp, topEnd = 18.dp, bottomEnd = 18.dp, bottomStart = 6.dp),
        modifier = modifier.semantics { contentDescription = "Coach is typing" },
    ) {
        Row(
            modifier = Modifier.padding(vertical = 14.dp, horizontal = 16.dp),
        ) {
            alphas.forEachIndexed { index, dotAlpha ->
                androidx.compose.foundation.layout.Box(
                    modifier =
                        Modifier
                            .padding(start = if (index == 0) 0.dp else 6.dp)
                            .size(6.dp)
                            .alpha(dotAlpha)
                            .clip(CircleShape)
                            .background(colors.inactive),
                )
            }
        }
    }
}

@Preview(name = "TypingIndicator light", widthDp = 390)
@Composable
private fun TypingIndicatorPreviewLight() {
    MealsyTheme(darkTheme = false) {
        Surface(color = MealsyTheme.colors.canvas) {
            androidx.compose.foundation.layout.Box(modifier = Modifier.padding(16.dp)) {
                TypingIndicator()
            }
        }
    }
}

@Preview(name = "TypingIndicator dark", widthDp = 390, uiMode = Configuration.UI_MODE_NIGHT_YES)
@Composable
private fun TypingIndicatorPreviewDark() {
    MealsyTheme(darkTheme = true) {
        Surface(color = MealsyTheme.colors.canvas) {
            androidx.compose.foundation.layout.Box(modifier = Modifier.padding(16.dp)) {
                TypingIndicator()
            }
        }
    }
}
