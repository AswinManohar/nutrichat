package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType

/**
 * A perfect-circle pastel icon chip, used on list rows, goal cards, and food
 * rows in the meal confirm card.
 *
 * Reminder: pastels are allowed ONLY in tiny tags and 32-36dp icon circles —
 * see `android/CLAUDE.md`.
 *
 * @param icon The stroked icon to draw at 15dp, tinted with the tone's dark
 *   text color.
 * @param tone Which pastel tone fills the circle.
 * @param modifier The modifier applied to the circle.
 * @param size The circle's diameter. The design uses 32dp (confirm-card
 *   rows), 34dp (list rows, goal cards), or 36dp.
 * @param contentDescription An accessibility label for the icon, or null if
 *   a sibling text label already describes it.
 */
@Composable
fun PastelIconCircle(
    icon: ImageVector,
    tone: TagTone,
    modifier: Modifier = Modifier,
    size: Dp = 34.dp,
    contentDescription: String? = null,
) {
    val resolved = tone.resolve()
    Surface(
        modifier = modifier.size(size),
        shape = CircleShape,
        color = resolved.fill,
    ) {
        Box(contentAlignment = Alignment.Center) {
            Icon(
                imageVector = icon,
                contentDescription = contentDescription,
                tint = resolved.text,
                modifier = Modifier.size(15.dp),
            )
        }
    }
}

/**
 * A perfect-circle pastel chip showing a single initial letter instead of an
 * icon, used by onboarding's goal-selection cards.
 *
 * Reminder: pastels are allowed ONLY in tiny tags and 32-36dp icon circles —
 * see `android/CLAUDE.md`.
 *
 * @param initial The single character to render, in [MealsyType.section].
 * @param tone Which pastel tone fills the circle.
 * @param modifier The modifier applied to the circle.
 * @param size The circle's diameter.
 */
@Composable
fun PastelIconCircle(
    initial: Char,
    tone: TagTone,
    modifier: Modifier = Modifier,
    size: Dp = 34.dp,
) {
    val resolved = tone.resolve()
    Surface(
        modifier = modifier.size(size).semantics { this.contentDescription = initial.toString() },
        shape = CircleShape,
        color = resolved.fill,
    ) {
        Box(contentAlignment = Alignment.Center) {
            Text(text = initial.toString(), style = MealsyType.section, color = resolved.text)
        }
    }
}

@Preview(name = "PastelIconCircle light", widthDp = 390)
@Composable
private fun PastelIconCircleLightPreview() {
    MealsyTheme {
        androidx.compose.material3.Surface(color = MealsyTheme.colors.canvas) {
            Row(
                modifier = Modifier.padding(20.dp),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                PastelIconCircle(initial = 'L', tone = TagTone.Butter)
                PastelIconCircle(initial = 'M', tone = TagTone.Leaf)
            }
        }
    }
}

@Preview(
    name = "PastelIconCircle dark",
    widthDp = 390,
    uiMode = Configuration.UI_MODE_NIGHT_YES,
)
@Composable
private fun PastelIconCircleDarkPreview() {
    MealsyTheme(darkTheme = true) {
        androidx.compose.material3.Surface(color = MealsyTheme.colors.canvas) {
            Row(
                modifier = Modifier.padding(20.dp),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                PastelIconCircle(initial = 'B', tone = TagTone.Powder)
                PastelIconCircle(initial = 'P', tone = TagTone.Pink)
            }
        }
    }
}
