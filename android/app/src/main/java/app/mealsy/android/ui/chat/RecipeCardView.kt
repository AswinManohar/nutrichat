package app.mealsy.android.ui.chat

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.mealsy.android.R
import app.mealsy.android.design.components.Eyebrow
import app.mealsy.android.design.components.MarkdownText
import app.mealsy.android.design.components.MealsyButton
import app.mealsy.android.design.components.MealsyButtonStyle
import app.mealsy.android.design.components.PillInput
import app.mealsy.android.design.icons.MealsyIcons
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType
import app.mealsy.data.api.RecipeDto
import java.util.Locale

/**
 * A recipe reply as a card: name, intro, ingredients with grams, numbered
 * steps, a time row and the constraint sentence, then "Sounds good" / "Not for
 * me" buttons. "Not for me" first opens an optional reason field. Once
 * [choice] is set the buttons are replaced by the recorded answer.
 *
 * @param recipe The checked recipe from the reply.
 * @param constraintNote The "Kept ..." sentence explaining the limits it respects, or null.
 * @param choice The patient's answer so far; [RecipeChoice.Sending] disables the buttons.
 * @param onFeedback Called with `accepted` and an optional rejection reason.
 * @param timestamp Optional timestamp shown below the card.
 */
@Composable
fun RecipeCardView(
    recipe: RecipeDto,
    constraintNote: String?,
    choice: RecipeChoice,
    onFeedback: (accepted: Boolean, reason: String?) -> Unit,
    modifier: Modifier = Modifier,
    timestamp: String? = null,
) {
    val colors = MealsyTheme.colors
    Column(modifier = modifier.fillMaxWidth().padding(vertical = 8.dp)) {
        Surface(color = colors.surface, shape = RoundedCornerShape(18.dp)) {
            Column(modifier = Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text(text = recipe.name, style = MealsyType.screenTitle, color = colors.ink)
                if (recipe.intro.isNotBlank()) {
                    Text(text = recipe.intro, style = MealsyType.body, color = colors.ink)
                }
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Eyebrow(text = stringResource(R.string.chat_recipe_ingredients))
                    recipe.ingredients.forEach { ingredient ->
                        Text(
                            text = stringResource(R.string.chat_recipe_ingredient_line, ingredient.name, gramsText(ingredient.qtyG)),
                            style = MealsyType.body,
                            color = colors.ink,
                        )
                    }
                }
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Eyebrow(text = stringResource(R.string.chat_recipe_steps))
                    recipe.steps.forEachIndexed { index, step ->
                        Text(text = "${index + 1}. $step", style = MealsyType.body, color = colors.ink)
                    }
                }
                Text(
                    text = stringResource(R.string.chat_recipe_time, recipe.activeMinutes, recipe.totalMinutes),
                    style = MealsyType.label,
                    color = colors.muted,
                )
                if (!constraintNote.isNullOrBlank()) {
                    Text(text = constraintNote, style = MealsyType.label, color = colors.muted)
                }
                RecipeFeedbackRow(choice = choice, onFeedback = onFeedback)
            }
        }
        if (timestamp != null) {
            Text(
                text = timestamp,
                style = MealsyType.label.copy(fontSize = 11.sp),
                color = colors.inactive,
                modifier = Modifier.padding(top = 4.dp),
            )
        }
    }
}

@Composable
private fun RecipeFeedbackRow(
    choice: RecipeChoice,
    onFeedback: (Boolean, String?) -> Unit,
) {
    val colors = MealsyTheme.colors
    var askingReason by remember { mutableStateOf(false) }
    var reason by remember { mutableStateOf("") }
    val answered = choice == RecipeChoice.Accepted || choice == RecipeChoice.Rejected
    if (answered) {
        Text(
            text =
                stringResource(
                    if (choice == RecipeChoice.Accepted) R.string.chat_recipe_accepted else R.string.chat_recipe_rejected,
                ),
            style = MealsyType.label,
            color = colors.muted,
        )
        return
    }
    val enabled = choice == RecipeChoice.None
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        if (askingReason) {
            PillInput(
                value = reason,
                onValueChange = { reason = it.take(MAX_REASON_CHARS) },
                placeholder = stringResource(R.string.chat_recipe_reason_placeholder),
                enabled = enabled,
                modifier = Modifier.fillMaxWidth(),
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (askingReason) {
                MealsyButton(
                    text = stringResource(R.string.chat_recipe_reason_send),
                    onClick = { onFeedback(false, reason) },
                    enabled = enabled,
                    modifier = Modifier.weight(1f),
                )
            } else {
                MealsyButton(
                    text = stringResource(R.string.chat_recipe_accept),
                    onClick = { onFeedback(true, null) },
                    modifier = Modifier.weight(1f),
                    enabled = enabled,
                )
                MealsyButton(
                    text = stringResource(R.string.chat_recipe_reject),
                    onClick = { askingReason = true },
                    modifier = Modifier.weight(1f),
                    style = MealsyButtonStyle.Secondary,
                    enabled = enabled,
                )
            }
        }
    }
}

/**
 * A safety reply (a red-flag response from the coach): a bubble with a shield
 * icon and a terracotta outline, so it reads differently from ordinary coach
 * text. It carries no rating controls.
 *
 * @param text The reply body.
 * @param timestamp Optional timestamp shown below the bubble.
 */
@Composable
fun SafetyBubble(
    text: String,
    modifier: Modifier = Modifier,
    timestamp: String? = null,
) {
    val colors = MealsyTheme.colors
    Column(modifier = modifier.fillMaxWidth().padding(vertical = 8.dp)) {
        Surface(
            color = colors.surface,
            shape = RoundedCornerShape(18.dp),
            border = BorderStroke(1.5.dp, colors.terracottaOutlineText),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth().padding(14.dp),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
                verticalAlignment = Alignment.Top,
            ) {
                Icon(
                    imageVector = MealsyIcons.Shield,
                    contentDescription = stringResource(R.string.chat_safety_icon_description),
                    tint = colors.terracottaOutlineText,
                    modifier = Modifier.size(24.dp),
                )
                MarkdownText(markdown = text, color = colors.ink)
            }
        }
        if (timestamp != null) {
            Text(
                text = timestamp,
                style = MealsyType.label.copy(fontSize = 11.sp),
                color = colors.inactive,
                modifier = Modifier.padding(top = 4.dp),
            )
        }
    }
}

/** Whole grams without a trailing ".0"; one decimal otherwise. */
private fun gramsText(grams: Double): String =
    if (grams % 1.0 == 0.0) grams.toLong().toString() else String.format(Locale.US, "%.1f", grams)

private const val MAX_REASON_CHARS = 500
