package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material3.Icon
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.icons.MealsyIcons
import app.mealsy.android.design.theme.MealsyShapes
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.mealsyTween

/**
 * One destination in a [BottomNavPill].
 *
 * @param icon The 22dp stroked icon shown for this tab.
 * @param label Accessible label and tab name (not rendered as visible text
 *   in the pill per the handoff — icon-only nav).
 * @param route An opaque route identifier. `:core:ui` has no Navigation
 *   dependency, so this is just a string the caller interprets.
 */
data class MealsyNavItem(
    val icon: ImageVector,
    val label: String,
    val route: String,
)

/**
 * The floating ink bottom navigation pill, per "Bottom nav + FAB" in
 * `Mealsy Design System.html`. Floats 26dp above the bottom edge with 16dp
 * side margins, max width 340dp (centered when the available width is
 * wider), inner padding 14dp vertical / 28dp horizontal. Four 22dp stroked
 * icons; active tint `navActive`, inactive `navInactive`. In dark mode the
 * pill keeps its ink background and gains a 1dp `navBorder` hairline.
 *
 * The optional [fab] slot (typically an [OliveFab]) is centered on the
 * pill's own centre point, both horizontally and vertically — it overhangs
 * evenly above and below the pill, matching the reference HTML where the
 * FAB is `position: absolute; left: 50%; top: 50%; transform:
 * translate(-50%, -50%)` relative to the pill. When [fab] is non-null,
 * [items] is split into a left half and a right half (the first half gets
 * the extra item for an odd count) with a reserved 56dp centre gap between
 * them so the FAB drops in without clipping or crowding any icon. Each half
 * spreads its icons evenly across its share of the row. When [fab] is null,
 * all icons spread evenly across the full width with no gap.
 *
 * @param items The nav destinations, rendered in order.
 * @param selectedRoute The currently active [MealsyNavItem.route].
 * @param onSelect Invoked with a [MealsyNavItem.route] when a tab is tapped.
 * @param fab Optional centered, overlapping FAB slot.
 */
@Composable
fun BottomNavPill(
    items: List<MealsyNavItem>,
    selectedRoute: String,
    onSelect: (String) -> Unit,
    modifier: Modifier = Modifier,
    fab: @Composable (() -> Unit)? = null,
) {
    val colors = MealsyTheme.colors
    val borderModifier = if (colors.isDark) {
        Modifier.border(width = 1.dp, color = colors.navBorder, shape = MealsyShapes.pill)
    } else {
        Modifier
    }

    Box(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp)
            .padding(bottom = 26.dp),
        contentAlignment = Alignment.Center,
    ) {
        Surface(
            color = colors.navBar,
            shape = MealsyShapes.pill,
            modifier = Modifier
                .fillMaxWidth()
                .widthIn(max = 340.dp)
                .then(borderModifier),
        ) {
            Row(
                modifier = Modifier
                    .padding(vertical = 14.dp, horizontal = 28.dp)
                    .fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                if (fab != null) {
                    val half = (items.size + 1) / 2
                    val left = items.take(half)
                    val right = items.drop(half)
                    NavHalf(
                        items = left,
                        selectedRoute = selectedRoute,
                        onSelect = onSelect,
                        colors = colors,
                        modifier = Modifier.weight(1f),
                    )
                    Box(modifier = Modifier.width(56.dp))
                    NavHalf(
                        items = right,
                        selectedRoute = selectedRoute,
                        onSelect = onSelect,
                        colors = colors,
                        modifier = Modifier.weight(1f),
                    )
                } else {
                    NavHalf(
                        items = items,
                        selectedRoute = selectedRoute,
                        onSelect = onSelect,
                        colors = colors,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            }
        }
        // Centered on the pill's own centre point (both axes), not its top
        // edge — matches the reference HTML's `translate(-50%, -50%)` FAB.
        if (fab != null) {
            fab()
        }
    }
}

/**
 * One side of the nav pill: [items] spread evenly across [modifier]'s width
 * via [androidx.compose.foundation.layout.Arrangement.SpaceEvenly].
 */
@Composable
private fun NavHalf(
    items: List<MealsyNavItem>,
    selectedRoute: String,
    onSelect: (String) -> Unit,
    colors: app.mealsy.android.design.theme.MealsyColors,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier,
        horizontalArrangement = androidx.compose.foundation.layout.Arrangement.SpaceEvenly,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        items.forEach { item ->
            NavIcon(
                item = item,
                isSelected = item.route == selectedRoute,
                onSelect = onSelect,
                colors = colors,
            )
        }
    }
}

@Composable
private fun NavIcon(
    item: MealsyNavItem,
    isSelected: Boolean,
    onSelect: (String) -> Unit,
    colors: app.mealsy.android.design.theme.MealsyColors,
) {
    val interactionSource = remember { MutableInteractionSource() }
    val tint by animateColorAsState(
        targetValue = if (isSelected) colors.navActive else colors.navInactive,
        animationSpec = mealsyTween(150),
        label = "navIconTint",
    )
    Icon(
        imageVector = item.icon,
        contentDescription = item.label,
        tint = tint,
        modifier = Modifier
            .size(22.dp)
            .clickable(
                interactionSource = interactionSource,
                indication = null,
                onClickLabel = item.label,
                role = Role.Tab,
                onClick = { onSelect(item.route) },
            )
            .semantics {
                role = Role.Tab
                selected = isSelected
                contentDescription = item.label
            },
    )
}

@Preview(name = "BottomNavPill light", widthDp = 390)
@Composable
private fun BottomNavPillPreviewLight() {
    val items = listOf(
        MealsyNavItem(MealsyIcons.Home, "Home", "home"),
        MealsyNavItem(MealsyIcons.BowlBars, "Meals", "meals"),
        MealsyNavItem(MealsyIcons.LineChart, "Trends", "trends"),
        MealsyNavItem(MealsyIcons.Chat, "Chat", "chat"),
    )
    MealsyTheme(darkTheme = false) {
        Surface(color = MealsyTheme.colors.canvas) {
            BottomNavPill(
                items = items,
                selectedRoute = "home",
                onSelect = {},
                fab = { OliveFab(onClick = {}, contentDescription = "Log a meal") },
            )
        }
    }
}

@Preview(name = "BottomNavPill dark", widthDp = 390, uiMode = Configuration.UI_MODE_NIGHT_YES)
@Composable
private fun BottomNavPillPreviewDark() {
    val items = listOf(
        MealsyNavItem(MealsyIcons.Home, "Home", "home"),
        MealsyNavItem(MealsyIcons.BowlBars, "Meals", "meals"),
        MealsyNavItem(MealsyIcons.LineChart, "Trends", "trends"),
        MealsyNavItem(MealsyIcons.Chat, "Chat", "chat"),
    )
    MealsyTheme(darkTheme = true) {
        Surface(color = MealsyTheme.colors.canvas) {
            BottomNavPill(
                items = items,
                selectedRoute = "home",
                onSelect = {},
                fab = { OliveFab(onClick = {}, contentDescription = "Log a meal") },
            )
        }
    }
}
