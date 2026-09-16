package app.mealsy.android.design.theme

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.unit.dp

/**
 * The Mealsy corner-radius scale.
 *
 * Icon chips are perfect circles (`CircleShape`), not part of this object —
 * see `android/CLAUDE.md`.
 */
object MealsyShapes {
    /** Cards and containers (18dp). */
    val card = RoundedCornerShape(18.dp)

    /** Totals strip and small icon-chip tiles (14dp). */
    val strip = RoundedCornerShape(14.dp)

    /** Pills, badges, buttons, nav, inputs (fully rounded). */
    val pill = RoundedCornerShape(percent = 50)

    /** Reference-only phone container radius (26dp), not used in-app. */
    val phone = RoundedCornerShape(26.dp)
}
