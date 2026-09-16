package app.mealsy.android.design.theme

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.asPaddingValues
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBars
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

/**
 * Applies the Mealsy screen padding convention.
 *
 * Design rule: content should sit ~60-64dp below the status bar (the actual
 * status bar inset plus a fixed 24dp top padding), with 20dp horizontal
 * margins, and 120dp of bottom clearance to stay clear of the floating
 * bottom nav pill when one is showing (32dp otherwise).
 *
 * @param showsBottomNav Whether this screen shows the floating bottom nav
 *   pill, which reserves 120dp of bottom clearance instead of 32dp.
 */
@Composable
fun Modifier.mealsyScreenPadding(showsBottomNav: Boolean = true): Modifier {
    val statusBarTop = WindowInsets.statusBars.asPaddingValues().calculateTopPadding()
    return this.padding(
        PaddingValues(
            start = 20.dp,
            end = 20.dp,
            top = statusBarTop + 24.dp,
            bottom = if (showsBottomNav) 120.dp else 32.dp,
        ),
    )
}
