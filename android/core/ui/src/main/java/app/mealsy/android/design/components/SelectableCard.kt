package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.selection.selectable
import androidx.compose.material3.Icon
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.icons.MealsyIcons
import app.mealsy.android.design.theme.MealsyShapes
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType
import app.mealsy.android.design.theme.mealsyTween

/**
 * A selectable option card, used for onboarding's goal-selection step.
 *
 * @param title The card's primary label.
 * @param subtitle A short supporting line, rendered muted.
 * @param selected Whether this card is the current selection.
 * @param onClick Invoked when the card is tapped.
 * @param modifier The modifier applied to the card.
 * @param leading An optional leading slot, typically a 34dp
 *   [PastelIconCircle] with an initial letter.
 */
@Composable
fun SelectableCard(
    title: String,
    subtitle: String,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    leading: @Composable (() -> Unit)? = null,
) {
    val colors = MealsyTheme.colors
    val borderColor by animateColorAsState(
        targetValue = if (selected) colors.ink else Color.Transparent,
        animationSpec = mealsyTween(150),
        label = "selectable-card-border",
    )

    Surface(
        modifier =
            modifier
                .fillMaxWidth()
                .selectable(
                    selected = selected,
                    role = Role.RadioButton,
                    onClick = onClick,
                ),
        shape = MealsyShapes.card,
        color = colors.surface,
        border = BorderStroke(1.5.dp, borderColor),
    ) {
        Row(
            modifier = Modifier.padding(vertical = 14.dp, horizontal = 16.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            leading?.invoke()
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = title,
                    style = MealsyType.body.copy(fontWeight = androidx.compose.ui.text.font.FontWeight.Medium),
                    color = colors.ink,
                )
                Text(text = subtitle, style = MealsyType.label, color = colors.muted)
            }
            if (selected) {
                Icon(
                    imageVector = MealsyIcons.Check,
                    contentDescription = null,
                    tint = colors.ink,
                    modifier = Modifier.size(15.dp),
                )
            }
        }
    }
}

@Preview(name = "SelectableCard light", widthDp = 390)
@Composable
private fun SelectableCardLightPreview() {
    MealsyTheme {
        androidx.compose.material3.Surface(color = MealsyTheme.colors.canvas) {
            Column(
                modifier = Modifier.padding(20.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                SelectableCard(
                    title = "Lose weight steadily",
                    subtitle = "A gentle deficit, no crash targets",
                    selected = true,
                    onClick = {},
                    leading = { PastelIconCircle(initial = 'L', tone = TagTone.Butter) },
                )
                SelectableCard(
                    title = "Maintain where I am",
                    subtitle = "Keep energy and habits consistent",
                    selected = false,
                    onClick = {},
                    leading = { PastelIconCircle(initial = 'M', tone = TagTone.Leaf) },
                )
            }
        }
    }
}

@Preview(
    name = "SelectableCard dark",
    widthDp = 390,
    uiMode = Configuration.UI_MODE_NIGHT_YES,
)
@Composable
private fun SelectableCardDarkPreview() {
    MealsyTheme(darkTheme = true) {
        androidx.compose.material3.Surface(color = MealsyTheme.colors.canvas) {
            SelectableCard(
                title = "Build muscle",
                subtitle = "More protein, a small surplus",
                selected = true,
                onClick = {},
                modifier = Modifier.padding(20.dp),
                leading = { PastelIconCircle(initial = 'B', tone = TagTone.Powder) },
            )
        }
    }
}
