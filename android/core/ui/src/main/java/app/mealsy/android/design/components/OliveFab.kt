package app.mealsy.android.design.components

import android.content.res.Configuration
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import app.mealsy.android.design.icons.MealsyIcons
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.mealsyTween

/**
 * The floating "log a meal" action button, centered on and overlapping
 * [BottomNavPill]. 56dp olive circle, 24dp [MealsyIcons.Plus] tinted
 * `fabIcon`, pressed scale 0.94 over 150ms.
 *
 * This is the ONLY element in the entire Mealsy design allowed a drop
 * shadow (`0dp 4dp 14dp rgba(28,27,23,0.28)`, i.e. [MealsyTheme.colors.fabShadow])
 * — every other component must stay flat per `android/CLAUDE.md`.
 *
 * @param onClick Invoked on tap, e.g. to open quick-log chat.
 * @param contentDescription Accessibility label, e.g. "Log a meal".
 */
@Composable
fun OliveFab(
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    contentDescription: String,
) {
    val colors = MealsyTheme.colors
    val interactionSource = remember { MutableInteractionSource() }
    val pressed by interactionSource.collectIsPressedAsState()
    val scale by animateFloatAsState(
        targetValue = if (pressed) 0.94f else 1f,
        animationSpec = mealsyTween(durationMillis = 120),
        label = "oliveFabScale",
    )

    Box(
        modifier = modifier
            .size(56.dp)
            .scale(scale)
            .shadow(
                elevation = 14.dp,
                shape = CircleShape,
                ambientColor = colors.fabShadow,
                spotColor = colors.fabShadow,
            )
            .clip(CircleShape)
            .background(colors.fab)
            .clickable(
                interactionSource = interactionSource,
                indication = null,
                onClickLabel = contentDescription,
                role = Role.Button,
                onClick = onClick,
            )
            .semantics {
                role = Role.Button
            },
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            imageVector = MealsyIcons.Plus,
            contentDescription = contentDescription,
            tint = colors.fabIcon,
            modifier = Modifier.size(24.dp),
        )
    }
}

@Preview(name = "OliveFab light", widthDp = 390)
@Composable
private fun OliveFabPreviewLight() {
    MealsyTheme(darkTheme = false) {
        Surface(color = MealsyTheme.colors.canvas) {
            Box(modifier = Modifier.size(120.dp), contentAlignment = Alignment.Center) {
                OliveFab(onClick = {}, contentDescription = "Log a meal")
            }
        }
    }
}

@Preview(name = "OliveFab dark", widthDp = 390, uiMode = Configuration.UI_MODE_NIGHT_YES)
@Composable
private fun OliveFabPreviewDark() {
    MealsyTheme(darkTheme = true) {
        Surface(color = MealsyTheme.colors.canvas) {
            Box(modifier = Modifier.size(120.dp), contentAlignment = Alignment.Center) {
                OliveFab(onClick = {}, contentDescription = "Log a meal")
            }
        }
    }
}
