package app.mealsy.android.design.theme

import android.os.Build
import android.view.HapticFeedbackConstants
import android.view.View
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.LocalView

/**
 * Thin, semantic wrapper around the host [View]'s
 * [View.performHapticFeedback] so every Mealsy component that wants a tick
 * or confirm buzz goes through one call site instead of picking a raw
 * [HapticFeedbackConstants] itself.
 *
 * Built on the host [View] rather than Compose's
 * [androidx.compose.ui.hapticfeedback.HapticFeedback] because that API only
 * exposes `LongPress`/`TextHandleMove` on this BOM — both too heavy or
 * semantically wrong for a stepper tick or toggle flip. Going straight to
 * [View.performHapticFeedback] gets the lighter platform constants instead.
 *
 * Obtain one via [rememberMealsyHaptics]. No component should read
 * [LocalView] directly for haptics.
 */
class MealsyHaptics internal constructor(private val view: View) {
    /** A light tick for a discrete, low-stakes step: a stepper +/- tap or
     * repeat, a toggle flip, a segmented-control selection. */
    fun tick() {
        val constant =
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
                HapticFeedbackConstants.SEGMENT_FREQUENT_TICK
            } else {
                HapticFeedbackConstants.CLOCK_TICK
            }
        view.performHapticFeedback(constant)
    }

    /** A confirmation for a committing action: confirm & log, a swipe
     * crossing its delete threshold. */
    fun confirm() {
        // minSdk is 28, so the only fallback branch that can ever apply
        // is the sub-R (API < 30) one.
        val constant =
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                HapticFeedbackConstants.CONFIRM
            } else {
                HapticFeedbackConstants.VIRTUAL_KEY
            }
        view.performHapticFeedback(constant)
    }
}

/** Remembers a [MealsyHaptics] bound to the current [LocalView]. */
@Composable
fun rememberMealsyHaptics(): MealsyHaptics {
    val view = LocalView.current
    return remember(view) { MealsyHaptics(view) }
}
