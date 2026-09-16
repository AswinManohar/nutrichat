package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Icon
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.icons.MealsyIcons
import app.mealsy.android.design.theme.MealsyShapes
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType

/**
 * The coach's short-suggestion card, shown on Home, meal detail, and inline
 * in chat.
 *
 * Voice rule (see `android/CLAUDE.md`): [text] should be at most two
 * sentences, contain no exclamation marks, and never scold — explain why
 * and suggest one concrete action.
 *
 * @param text The coach's note body.
 * @param modifier The modifier applied to the card.
 */
@Composable
fun CoachNote(text: String, modifier: Modifier = Modifier) {
    val colors = MealsyTheme.colors
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = MealsyShapes.card,
        color = colors.surface,
    ) {
        Row(
            modifier = Modifier.padding(vertical = 14.dp, horizontal = 16.dp),
            horizontalArrangement = androidx.compose.foundation.layout.Arrangement.spacedBy(10.dp),
        ) {
            Icon(
                imageVector = MealsyIcons.Sparkle,
                contentDescription = null,
                tint = colors.olive,
                modifier = Modifier
                    .padding(top = 2.dp)
                    .size(15.dp),
            )
            Text(text = text, style = MealsyType.body, color = colors.ink)
        }
    }
}

@Preview(name = "CoachNote light", widthDp = 390)
@Composable
private fun CoachNoteLightPreview() {
    MealsyTheme {
        androidx.compose.material3.Surface(color = MealsyTheme.colors.canvas) {
            CoachNote(
                text = "You're 24g short on protein today. Greek yogurt this afternoon " +
                    "would close the gap.",
                modifier = Modifier.padding(20.dp),
            )
        }
    }
}

@Preview(
    name = "CoachNote dark",
    widthDp = 390,
    uiMode = Configuration.UI_MODE_NIGHT_YES,
)
@Composable
private fun CoachNoteDarkPreview() {
    MealsyTheme(darkTheme = true) {
        androidx.compose.material3.Surface(color = MealsyTheme.colors.canvas) {
            CoachNote(
                text = "You're 24g short on protein today. Greek yogurt this afternoon " +
                    "would close the gap.",
                modifier = Modifier.padding(20.dp),
            )
        }
    }
}
