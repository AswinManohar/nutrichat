package app.mealsy.android.ui.common

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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import app.mealsy.android.R
import app.mealsy.android.design.icons.MealsyIcons
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType
import app.mealsy.domain.CardWarning

/**
 * The Care profile reminders for this meal (spec 013 FR-044). A warning that
 * needs "Log anyway" (allergy, medication interaction) is outlined in
 * terracotta, like the safety bubble; a reminder that logs normally is muted.
 */
@Composable
fun MealWarnings(
    warnings: List<CardWarning>,
    modifier: Modifier = Modifier,
) {
    val colors = MealsyTheme.colors
    val accent = if (warnings.any { it.needsAck }) colors.terracottaOutlineText else colors.muted
    Surface(
        modifier = modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        color = colors.surface,
        border = BorderStroke(1.5.dp, accent),
    ) {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                Icon(
                    imageVector = MealsyIcons.Shield,
                    contentDescription = null,
                    tint = accent,
                    modifier = Modifier.size(16.dp),
                )
                Text(
                    text = stringResource(R.string.meal_warnings_title),
                    style = MealsyType.label,
                    color = accent,
                )
            }
            warnings.forEach { warning ->
                Text(
                    text = warning.text,
                    style = MealsyType.body,
                    color = if (warning.needsAck) colors.ink else colors.muted,
                )
            }
        }
    }
}
