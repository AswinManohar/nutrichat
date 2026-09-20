package app.mealsy.android.design.theme

import android.content.ContentResolver
import android.provider.Settings
import androidx.compose.animation.core.Easing
import androidx.compose.animation.core.TweenSpec
import androidx.compose.animation.core.tween
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.ProvidableCompositionLocal
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalInspectionMode

/**
 * Whether every animation in the Mealsy design system should snap instead of
 * animate. Defaults to `false` and is provided by [app.mealsy.android.design.theme.MealsyTheme]
 * from [rememberReducedMotion], which also folds in the system's "Remove
 * animations" accessibility setting.
 *
 * Components read this (directly or via [motionDurationMs] / [mealsyTween])
 * rather than the raw system settings so every call site gates the same way,
 * and so previews/screenshot tests (which force this `true` via
 * [LocalInspectionMode]) never need their own opt-out.
 */
val LocalReducedMotion: ProvidableCompositionLocal<Boolean> = compositionLocalOf { false }

/**
 * Pure decision function behind [rememberReducedMotion]: motion is reduced
 * when either the animator or the transition system-wide duration scale has
 * been set to zero (Android's "Remove animations" developer/accessibility
 * setting can zero either independently).
 *
 * Kept as a plain function, rather than inlined into the [Composable] that
 * reads [ContentResolver], so it has a JVM unit test with no Robolectric
 * dependency.
 *
 * @param animatorScale `Settings.Global.ANIMATOR_DURATION_SCALE`, or `1f`
 *   (the platform default, not reduced) if unset.
 * @param transitionScale `Settings.Global.TRANSITION_ANIMATION_SCALE`, or
 *   `1f` if unset.
 */
internal fun isReducedMotion(
    animatorScale: Float,
    transitionScale: Float,
): Boolean = animatorScale == 0f || transitionScale == 0f

/**
 * Reads the system's animator/transition duration scales via
 * [ContentResolver] and combines them with [isReducedMotion]. Also forces
 * `true` under [LocalInspectionMode] so `@Preview`s and Roborazzi goldens
 * render deterministically without depending on the host machine's
 * accessibility settings.
 *
 * `Settings.SettingNotFoundException`, or any other lookup failure, is
 * treated as "not reduced" (scale `1f`) rather than propagated — a missing
 * setting is not a signal the user wants reduced motion.
 */
@Composable
fun rememberReducedMotion(): Boolean {
    val inInspection = LocalInspectionMode.current
    val contentResolver = LocalContext.current.contentResolver
    return remember(inInspection, contentResolver) {
        if (inInspection) {
            true
        } else {
            isReducedMotion(
                animatorScale = readDurationScale(contentResolver, Settings.Global.ANIMATOR_DURATION_SCALE),
                transitionScale = readDurationScale(contentResolver, Settings.Global.TRANSITION_ANIMATION_SCALE),
            )
        }
    }
}

/** Reads a `Settings.Global` float duration scale, defaulting to `1f` on any failure. */
private fun readDurationScale(
    contentResolver: ContentResolver,
    name: String,
): Float =
    try {
        Settings.Global.getFloat(contentResolver, name)
    } catch (_: Settings.SettingNotFoundException) {
        1f
    }

/**
 * Provides [LocalReducedMotion] for [content], sourced from
 * [rememberReducedMotion]. Called once, from `MealsyTheme`, so every
 * descendant composable shares one gating decision.
 */
@Composable
internal fun ProvideReducedMotion(content: @Composable () -> Unit) {
    CompositionLocalProvider(LocalReducedMotion provides rememberReducedMotion(), content = content)
}

/**
 * Convenience gate for a single animation duration: `0` (snap) under
 * [LocalReducedMotion], otherwise [base] unchanged. Prefer this, or
 * [mealsyTween], at every animation call site so the reduced-motion gating
 * stays uniform and greppable.
 */
@Composable
fun motionDurationMs(base: Int): Int = if (LocalReducedMotion.current) 0 else base

/**
 * Builds a [TweenSpec] gated by [LocalReducedMotion]: [durationMillis] is
 * used at rest, and forced to `0` (an instant snap, not merely a shorter
 * animation) when reduced motion is active.
 */
@Composable
fun <T> mealsyTween(
    durationMillis: Int,
    easing: Easing = androidx.compose.animation.core.FastOutSlowInEasing,
): TweenSpec<T> = tween(durationMillis = motionDurationMs(durationMillis), easing = easing)
