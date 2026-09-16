package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Icon
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
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
 * side margins, inner padding 15dp vertical / 30dp horizontal. Four 22dp
 * stroked icons; active tint `navActive`, inactive `navInactive`. In dark
 * mode the pill keeps its ink background and gains a 1dp `navBorder`
 * hairline.
 *
 * The optional [fab] slot (typically an [OliveFab]) is centered
 * horizontally and overlaps the pill's top edge, per the design's FAB
 * placement between the second and third nav items.
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
            .padding(horizontal = 16.dp)
            .padding(bottom = 26.dp),
        contentAlignment = Alignment.BottomCenter,
    ) {
        Surface(
            color = colors.navBar,
            shape = MealsyShapes.pill,
            modifier = Modifier.then(borderModifier),
        ) {
            Row(
                modifier = Modifier.padding(vertical = 15.dp, horizontal = 30.dp),
                horizontalArrangement = androidx.compose.foundation.layout.Arrangement.SpaceBetween,
            ) {
                items.forEachIndexed { index, item ->
                    NavIcon(
                        item = item,
                        isSelected = item.route == selectedRoute,
                        onSelect = onSelect,
                        colors = colors,
                    )
                    // Reserve room for the overlapping FAB between item 2 and 3.
                    if (fab != null && index == 1) {
                        Box(modifier = Modifier.width(56.dp))
                    }
                }
            }
        }
        if (fab != null) {
            Box(modifier = Modifier.padding(bottom = 26.dp)) {
                fab()
            }
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
    Icon(
        imageVector = item.icon,
        contentDescription = item.label,
        tint = if (isSelected) colors.navActive else colors.navInactive,
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
