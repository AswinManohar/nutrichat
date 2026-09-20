package app.mealsy.android.design.theme

import android.app.Activity
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.ReadOnlyComposable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsControllerCompat

/**
 * Applies the Mealsy design system: brand [MealsyColors] via
 * [LocalMealsyColors], plus an underlying `MaterialTheme` (colors,
 * typography, shapes) so M3-only components (TextField, dialogs, Slider)
 * that this design system doesn't reimplement still inherit brand colors.
 *
 * This composable configures the status/navigation bar appearance
 * (transparent, with light/dark icon contrast matching [darkTheme]) but
 * does NOT call `enableEdgeToEdge()` itself — that call belongs in
 * `MainActivity`, owned by another task.
 *
 * @param darkTheme Whether to use the dark palette. Defaults to the system
 *   setting.
 * @param content The themed content.
 */
@Composable
fun MealsyTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    val mealsyColors = if (darkTheme) darkMealsyColors() else lightMealsyColors()

    val colorScheme =
        if (darkTheme) {
            darkColorScheme(
                primary = mealsyColors.ink,
                onPrimary = mealsyColors.canvas,
                primaryContainer = mealsyColors.surface,
                onPrimaryContainer = mealsyColors.ink,
                secondary = mealsyColors.olive,
                onSecondary = mealsyColors.oliveText,
                secondaryContainer = mealsyColors.oliveTrack,
                onSecondaryContainer = mealsyColors.oliveText,
                background = mealsyColors.canvas,
                onBackground = mealsyColors.ink,
                surface = mealsyColors.surface,
                onSurface = mealsyColors.ink,
                surfaceVariant = mealsyColors.surface,
                onSurfaceVariant = mealsyColors.muted,
                surfaceContainer = mealsyColors.surface,
                surfaceContainerHigh = mealsyColors.surface,
                surfaceContainerLow = mealsyColors.surface,
                outline = mealsyColors.hairline,
                outlineVariant = mealsyColors.divider,
                error = mealsyColors.terracotta,
                onError = mealsyColors.terracottaText,
                scrim = mealsyColors.ink.copy(alpha = 0.4f),
            )
        } else {
            lightColorScheme(
                primary = mealsyColors.ink,
                onPrimary = mealsyColors.canvas,
                primaryContainer = mealsyColors.surface,
                onPrimaryContainer = mealsyColors.ink,
                secondary = mealsyColors.olive,
                onSecondary = mealsyColors.oliveText,
                secondaryContainer = mealsyColors.oliveTrack,
                onSecondaryContainer = mealsyColors.oliveText,
                background = mealsyColors.canvas,
                onBackground = mealsyColors.ink,
                surface = mealsyColors.surface,
                onSurface = mealsyColors.ink,
                surfaceVariant = mealsyColors.surface,
                onSurfaceVariant = mealsyColors.muted,
                surfaceContainer = mealsyColors.surface,
                surfaceContainerHigh = mealsyColors.surface,
                surfaceContainerLow = mealsyColors.surface,
                outline = mealsyColors.hairline,
                outlineVariant = mealsyColors.divider,
                error = mealsyColors.terracotta,
                onError = mealsyColors.terracottaText,
                scrim = mealsyColors.ink.copy(alpha = 0.4f),
            )
        }

    val typography =
        Typography(
            displayLarge = MealsyType.hero,
            displayMedium = MealsyType.display,
            headlineMedium = MealsyType.screenTitle,
            titleMedium = MealsyType.section,
            bodyMedium = MealsyType.body,
            labelMedium = MealsyType.label,
            labelSmall = MealsyType.eyebrow,
            labelLarge = MealsyType.button,
        )

    val shapes =
        androidx.compose.material3.Shapes(
            small = MealsyShapes.strip,
            medium = MealsyShapes.card,
            large = MealsyShapes.card,
        )

    val view = LocalView.current
    if (!view.isInEditMode) {
        val context = LocalContext.current
        SideEffect {
            val activity = context as? Activity ?: return@SideEffect
            val window = activity.window ?: return@SideEffect
            window.statusBarColor = android.graphics.Color.TRANSPARENT
            window.navigationBarColor = android.graphics.Color.TRANSPARENT
            WindowCompat.setDecorFitsSystemWindows(window, false)
            val controller = WindowInsetsControllerCompat(window, view)
            controller.isAppearanceLightStatusBars = !darkTheme
            controller.isAppearanceLightNavigationBars = !darkTheme
        }
    }

    CompositionLocalProvider(LocalMealsyColors provides mealsyColors) {
        ProvideReducedMotion {
            MaterialTheme(
                colorScheme = colorScheme,
                typography = typography,
                shapes = shapes,
                content = content,
            )
        }
    }
}

/**
 * Accessor for the current [MealsyColors], mirroring the
 * `MaterialTheme.colorScheme` pattern. A composable function ([MealsyTheme])
 * and an object ([MealsyTheme]) can share a name in Kotlin, so callers write
 * `MealsyTheme.colors.ink` inside content wrapped by the `MealsyTheme { }`
 * composable.
 */
object MealsyTheme {
    /** The [MealsyColors] provided by the nearest [MealsyTheme] composable. */
    val colors: MealsyColors
        @Composable
        @ReadOnlyComposable
        get() = LocalMealsyColors.current
}
