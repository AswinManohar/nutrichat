package app.mealsy.android.ui.meals

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import app.mealsy.android.R
import app.mealsy.android.design.components.CircleIconButton
import app.mealsy.android.design.icons.MealsyIcons
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType
import app.mealsy.android.design.theme.mealsyScreenPadding

/**
 * Placeholder for a single meal type's log list (e.g. "Breakfast"), reached
 * from [app.mealsy.android.ui.home.HomeScreen]'s meal-type rows.
 *
 * Phase 3 replaces this destination with the real list; the Home call site
 * that navigates here (`meals/{mealType}`) does not need to change when that
 * happens. The bottom nav pill is hidden on this route (it's a detail
 * screen, not one of the four tabs), so this screen reserves the smaller
 * 32dp bottom clearance via [mealsyScreenPadding].
 *
 * @param onBack Pops back to Home.
 */
@Composable
fun MealTypeListPlaceholderScreen(onBack: () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .mealsyScreenPadding(showsBottomNav = false),
    ) {
        CircleIconButton(
            icon = MealsyIcons.ChevronLeft,
            contentDescription = stringResource(R.string.meals_placeholder_back),
            onClick = onBack,
        )
        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Text(
                text = stringResource(R.string.meals_placeholder_message),
                style = MealsyType.body,
                color = MealsyTheme.colors.muted,
            )
        }
    }
}
