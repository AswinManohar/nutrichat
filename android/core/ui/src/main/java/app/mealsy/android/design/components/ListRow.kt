package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Icon
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
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

/**
 * A single tappable row used inside [ListContainer], as seen on Home's
 * "Today's meals" list and meal detail's ingredient list.
 *
 * @param label The row's primary text.
 * @param onClick Invoked when the row is tapped, or null to render a
 *   non-interactive row (no pressed state).
 * @param modifier The modifier applied to the row's root container.
 * @param onClickLabel Describes the tap action for TalkBack (e.g. "Open
 *   meal"), announced alongside the row's label. Ignored when [onClick] is
 *   null.
 * @param leading An optional leading slot, typically a 34dp
 *   [PastelIconCircle].
 * @param badgeCount When non-null, renders an ink count badge as the
 *   trailing element instead of [trailingText].
 * @param trailingText Muted trailing text (e.g. "not yet"), shown when
 *   [badgeCount] is null.
 * @param showChevron Whether to draw the trailing chevron.
 */
@Composable
fun ListRow(
    label: String,
    onClick: (() -> Unit)?,
    modifier: Modifier = Modifier,
    onClickLabel: String? = null,
    leading: @Composable (() -> Unit)? = null,
    badgeCount: Int? = null,
    trailingText: String? = null,
    showChevron: Boolean = true,
) {
    val colors = MealsyTheme.colors
    val interactionSource = remember { MutableInteractionSource() }
    val pressed by interactionSource.collectIsPressedAsState()
    val background = if (pressed && onClick != null) colors.surfacePressed else Color.Transparent

    // #48 item 1: `clickable(role = Role.Button, onClickLabel = ...)` gives
    // TalkBack/Switch Access a click action and a "Button" role — plain
    // `pointerInput(detectTapGestures)` (the old approach elsewhere in this
    // screen family) exposes none of that.
    val clickableModifier =
        if (onClick != null) {
            Modifier.clickable(
                interactionSource = interactionSource,
                indication = null,
                onClickLabel = onClickLabel,
                role = Role.Button,
                onClick = onClick,
            )
        } else {
            Modifier
        }

    Row(
        modifier =
            modifier
                .fillMaxWidth()
                .defaultMinSize(minHeight = 48.dp)
                .background(background)
                .then(clickableModifier)
                .padding(vertical = 9.dp, horizontal = 16.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        leading?.invoke()
        Text(
            text = label,
            style = MealsyType.body,
            color = colors.ink,
            modifier = Modifier.weight(1f),
        )
        when {
            badgeCount != null -> {
                Surface(shape = MealsyShapes.pill, color = colors.ink) {
                    Text(
                        text = badgeCount.toString(),
                        style = MealsyType.badge,
                        color = colors.canvas,
                        modifier = Modifier.padding(vertical = 2.dp, horizontal = 9.dp),
                    )
                }
            }
            trailingText != null -> {
                Text(text = trailingText, style = MealsyType.label, color = colors.muted)
            }
        }
        if (showChevron) {
            Icon(
                imageVector = MealsyIcons.ChevronRight,
                contentDescription = null,
                tint = colors.inactive,
                modifier = Modifier.size(13.dp),
            )
        }
    }
}

/**
 * A `surface` container with [MealsyShapes.card] rounding, used to wrap a
 * sequence of [ListRow]s on Home and meal detail.
 *
 * Callers insert [InsetDivider] between rows themselves (see the previews
 * below) rather than this container drawing them automatically, since
 * `Column`'s children API does not let a wrapping composable see or insert
 * between siblings supplied by an arbitrary caller lambda without either
 * `Layout`-level introspection or a dedicated scope type — a plain explicit
 * divider call keeps this component simple and stateless.
 *
 * @param modifier The modifier applied to the container.
 * @param content The row content, typically a sequence of [ListRow]s
 *   separated by [InsetDivider].
 */
@Composable
fun ListContainer(
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit,
) {
    val colors = MealsyTheme.colors
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = MealsyShapes.card,
        color = colors.surface,
    ) {
        Column(content = content)
    }
}

@Preview(name = "ListRow light", widthDp = 390)
@Composable
private fun ListRowLightPreview() {
    MealsyTheme {
        androidx.compose.material3.Surface(color = MealsyTheme.colors.canvas) {
            Column(modifier = Modifier.padding(20.dp)) {
                ListContainer {
                    ListRow(
                        label = "Breakfast",
                        onClick = {},
                        leading = { PastelIconCircle(initial = 'B', tone = TagTone.Butter) },
                        badgeCount = 2,
                    )
                    InsetDivider()
                    ListRow(
                        label = "Dinner",
                        onClick = {},
                        leading = { PastelIconCircle(initial = 'D', tone = TagTone.Pink) },
                        trailingText = "not yet",
                    )
                }
            }
        }
    }
}

/**
 * A 1dp `divider`-colored hairline inset 16dp from the start, matching
 * [ListContainer]'s row separators. Place between [ListRow]s manually when
 * composing a container's content.
 */
@Composable
fun InsetDivider(modifier: Modifier = Modifier) {
    val colors = MealsyTheme.colors
    Box(
        modifier =
            modifier
                .padding(start = 16.dp)
                .fillMaxWidth()
                .height(1.dp)
                .background(colors.divider),
    )
}

@Preview(
    name = "ListRow dark",
    widthDp = 390,
    uiMode = Configuration.UI_MODE_NIGHT_YES,
)
@Composable
private fun ListRowDarkPreview() {
    MealsyTheme(darkTheme = true) {
        androidx.compose.material3.Surface(color = MealsyTheme.colors.canvas) {
            Column(modifier = Modifier.padding(20.dp)) {
                ListContainer {
                    ListRow(
                        label = "Lunch",
                        onClick = {},
                        leading = { PastelIconCircle(initial = 'L', tone = TagTone.Leaf) },
                        badgeCount = 1,
                    )
                }
            }
        }
    }
}
