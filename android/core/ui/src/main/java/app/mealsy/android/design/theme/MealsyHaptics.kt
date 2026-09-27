package app.mealsy.android.design.theme

import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.hapticfeedback.HapticFeedback
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalHapticFeedback

/**
 * Thin, semantic wrapper around [HapticFeedback] so every Mealsy component
 * that wants a tick or confirm buzz goes through one call site instead of
 * picking a raw [HapticFeedbackType] itself.
 *
 * Obtain one via [rememberMealsyHaptics]. No component should read
 * [LocalHapticFeedback] directly.
 */
class MealsyHaptics internal constructor(private val haptics: HapticFeedback) {
    /**
     * A light tick for a discrete, low-stakes step: a stepper +/- tap or
     * repeat, a toggle flip, a segmented-control selection.
     *
     * [HapticFeedbackType.LongPress] is the only tick-like constant this
     * Compose BOM exposes (`SegmentTick`/`Confirm` land in a later version);
     * it's reused here as the "confirm" haptic too, so all call sites go
     * through this one method regardless of which BOM lands it maps to.
     */
    fun tick() = haptics.performHapticFeedback(HapticFeedbackType.LongPress)

    /** A confirmation for a committing action: confirm & log, a swipe
     * crossing its delete threshold. Currently the same feel as [tick] —
     * see its doc for why. */
    fun confirm() = haptics.performHapticFeedback(HapticFeedbackType.LongPress)
}

/** Remembers a [MealsyHaptics] bound to the current [LocalHapticFeedback]. */
@Composable
fun rememberMealsyHaptics(): MealsyHaptics {
    val haptics = LocalHapticFeedback.current
    return remember(haptics) { MealsyHaptics(haptics) }
}
