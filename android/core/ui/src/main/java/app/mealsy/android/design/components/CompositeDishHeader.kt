package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.mealsy.android.design.R
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType

/**
 * Groups the ingredient rows of one composite dish (e.g. "Chicken caesar
 * salad") inside the meal confirm card, per README §5 item 3's mention that
 * a composite dish can be broken into ingredients or logged whole.
 *
 * Deliberately plain — no pastel, no olive — per `android/CLAUDE.md`'s "one
 * olive element per screen" rule, which the confirm card's totals strip
 * already spends.
 *
 * @param dishName The humanized dish name, e.g. "Chicken caesar salad".
 * @param onBreakIntoIngredients Invoked when the user chooses to expand the
 *   dish into its ingredient rows, or null to hide that action (e.g. the
 *   dish is already expanded).
 * @param onLogAsSingleItem Invoked when the user chooses to log the dish as
 *   one item instead of its ingredients, or null to hide that action.
 * @param modifier The modifier applied to the header's column.
 */
@Composable
fun CompositeDishHeader(
    dishName: String,
    onBreakIntoIngredients: (() -> Unit)?,
    onLogAsSingleItem: (() -> Unit)?,
    modifier: Modifier = Modifier,
) {
    val colors = MealsyTheme.colors
    Column(modifier = modifier, verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(
            text = dishName,
            style = MealsyType.body.copy(fontWeight = FontWeight.Medium),
            color = colors.ink,
        )
        if (onBreakIntoIngredients != null || onLogAsSingleItem != null) {
            Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                if (onBreakIntoIngredients != null) {
                    DishHeaderTextAction(
                        text = stringResource(R.string.confirm_card_break_into_ingredients),
                        onClick = onBreakIntoIngredients,
                    )
                }
                if (onLogAsSingleItem != null) {
                    DishHeaderTextAction(
                        text = stringResource(R.string.confirm_card_log_as_single),
                        onClick = onLogAsSingleItem,
                    )
                }
            }
        }
    }
}

/**
 * A low-emphasis text action for [CompositeDishHeader] — per the design
 * (README §5 item 3 / `Meal Confirm Card.html`), these are plain underlined
 * ink text, not full-width pill buttons: [MealsyButton]'s content `Row` is
 * `fillMaxWidth()`, which would otherwise let one (or, worse, greedily
 * starve a second) action swallow the entire row width.
 */
@Composable
private fun DishHeaderTextAction(text: String, onClick: () -> Unit) {
    val colors = MealsyTheme.colors
    Text(
        text = text,
        style = MealsyType.label.copy(fontSize = 13.sp, textDecoration = TextDecoration.Underline),
        color = colors.ink,
        modifier = Modifier
            .semantics { role = Role.Button }
            .clickable(onClick = onClick),
    )
}

@Preview(name = "CompositeDishHeader light", widthDp = 390)
@Composable
private fun CompositeDishHeaderLightPreview() {
    MealsyTheme {
        Surface(color = MealsyTheme.colors.canvas) {
            CompositeDishHeader(
                dishName = "Chicken caesar salad",
                onBreakIntoIngredients = {},
                onLogAsSingleItem = {},
                modifier = Modifier.padding(20.dp),
            )
        }
    }
}

@Preview(
    name = "CompositeDishHeader dark",
    widthDp = 390,
    uiMode = Configuration.UI_MODE_NIGHT_YES,
)
@Composable
private fun CompositeDishHeaderDarkPreview() {
    MealsyTheme(darkTheme = true) {
        Surface(color = MealsyTheme.colors.canvas) {
            CompositeDishHeader(
                dishName = "Chicken caesar salad",
                onBreakIntoIngredients = {},
                onLogAsSingleItem = null,
                modifier = Modifier.padding(20.dp),
            )
        }
    }
}
