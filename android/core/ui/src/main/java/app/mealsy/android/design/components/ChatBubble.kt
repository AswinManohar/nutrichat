package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.layout
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType

/** Who authored a [ChatBubble], driving its color and corner treatment. */
enum class ChatBubbleAuthor {
    /** The coach ("Olli"): `surface` bg, `ink` text, aligned to the start. */
    Coach,

    /** The user: `userBubble` bg, `userBubbleText` text, aligned to the end. */
    User,
}

/**
 * A chat message bubble, per the "Coach chat" screen in
 * `Mealsy Design System.html`. Max width 82% of the parent, 11dp vertical /
 * 14dp horizontal padding, [MealsyType.body].
 *
 * Coach bubbles get corner radii `18/18/18/6` (top-start, top-end,
 * bottom-end, bottom-start) and align to the start; user bubbles get
 * `18/18/6/18` and align to the end.
 *
 * @param text The message body.
 * @param author Who sent the message, driving color and corner shape.
 * @param timestamp Optional 11sp `inactive`-colored timestamp shown below
 *   the bubble, aligned to the bubble's side.
 * @param tags Optional row of pastel `TagChip`s (owned by another component
 *   file) shown below the text, e.g. macro tags on a coach reply about a
 *   logged meal.
 */
@Composable
fun ChatBubble(
    text: String,
    author: ChatBubbleAuthor,
    modifier: Modifier = Modifier,
    timestamp: String? = null,
    tags: @Composable (RowScope.() -> Unit)? = null,
) {
    val colors = MealsyTheme.colors
    val isCoach = author == ChatBubbleAuthor.Coach
    val bubbleColor = if (isCoach) colors.surface else colors.userBubble
    val textColor = if (isCoach) colors.ink else colors.userBubbleText
    val shape = if (isCoach) {
        RoundedCornerShape(topStart = 18.dp, topEnd = 18.dp, bottomEnd = 18.dp, bottomStart = 6.dp)
    } else {
        RoundedCornerShape(topStart = 18.dp, topEnd = 18.dp, bottomEnd = 6.dp, bottomStart = 18.dp)
    }
    val horizontalAlignment = if (isCoach) Alignment.Start else Alignment.End

    Column(
        modifier = modifier.fillMaxWidth(),
        horizontalAlignment = horizontalAlignment,
    ) {
        Column(
            modifier = Modifier
                .widthIn(max = 999.dp)
                .fillMaxWidthFraction(0.82f)
                .clip(shape)
                .background(bubbleColor)
                .padding(vertical = 11.dp, horizontal = 14.dp),
        ) {
            Text(text = text, style = MealsyType.body, color = textColor)
            if (tags != null) {
                Row(
                    modifier = Modifier.padding(top = 6.dp),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                    content = tags,
                )
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

/**
 * Constrains this composable to a fraction of its parent's max width,
 * matching CSS `max-width: 82%` semantics (as opposed to [Modifier.fillMaxWidth]
 * which would also stretch a short message to the full 82%).
 */
private fun Modifier.fillMaxWidthFraction(fraction: Float): Modifier =
    this.layout { measurable, constraints ->
        val maxW = (constraints.maxWidth * fraction).toInt()
        val placeable = measurable.measure(constraints.copy(maxWidth = maxW))
        layout(placeable.width, placeable.height) { placeable.placeRelative(0, 0) }
    }

@Preview(name = "ChatBubble light", widthDp = 390)
@Composable
private fun ChatBubblePreviewLight() {
    MealsyTheme(darkTheme = false) {
        Surface(color = MealsyTheme.colors.canvas) {
            Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                ChatBubble(
                    text = "Here's what I found for your lunch — 412 kcal, 28g protein.",
                    author = ChatBubbleAuthor.Coach,
                    timestamp = "07:39 PM",
                )
                ChatBubble(
                    text = "two eggs and toast",
                    author = ChatBubbleAuthor.User,
                    timestamp = "07:38 PM",
                )
            }
        }
    }
}

@Preview(name = "ChatBubble dark", widthDp = 390, uiMode = Configuration.UI_MODE_NIGHT_YES)
@Composable
private fun ChatBubblePreviewDark() {
    MealsyTheme(darkTheme = true) {
        Surface(color = MealsyTheme.colors.canvas) {
            Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                ChatBubble(
                    text = "Here's what I found for your lunch — 412 kcal, 28g protein.",
                    author = ChatBubbleAuthor.Coach,
                    timestamp = "07:39 PM",
                )
                ChatBubble(
                    text = "two eggs and toast",
                    author = ChatBubbleAuthor.User,
                    timestamp = "07:38 PM",
                )
            }
        }
    }
}
