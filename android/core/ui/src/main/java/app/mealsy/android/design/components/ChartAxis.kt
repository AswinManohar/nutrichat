package app.mealsy.android.design.components

import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import java.text.NumberFormat
import java.util.Locale

/**
 * Rounds [maxValue] up to a pleasant axis ceiling for a Trends-style chart.
 *
 * The step scales with magnitude so small series (e.g. grams of protein)
 * get fine ceilings and large series (e.g. kcal) get coarse ones:
 * - `maxValue <= 0` -> `0f` (an empty/flat series draws no headroom).
 * - `maxValue <= 20` -> nearest multiple of 5.
 * - `maxValue <= 100` -> nearest multiple of 10.
 * - `maxValue <= 1000` -> nearest multiple of 200 (kcal scale).
 * - otherwise -> nearest multiple of 500.
 *
 * In every case the result is strictly greater than [maxValue] when
 * [maxValue] is not already an exact multiple of the step, so the topmost
 * data point never touches the axis's top edge.
 */
fun niceAxisMax(maxValue: Float): Float {
    if (maxValue <= 0f) return 0f
    val step =
        when {
            maxValue <= 20f -> 5f
            maxValue <= 100f -> 10f
            maxValue <= 1000f -> 200f
            else -> 500f
        }
    val ceilingSteps = kotlin.math.ceil(maxValue / step)
    return ceilingSteps * step
}

/**
 * Draws a horizontal dashed line across the full width of this [DrawScope],
 * for a chart's goal/target reference line.
 *
 * @param y The vertical offset (in px) to draw the line at.
 * @param color The line color.
 * @param strokeWidthPx The line's stroke width, in px.
 * @param dashPx The length of each dash, in px.
 * @param gapPx The length of each gap between dashes, in px.
 */
fun DrawScope.drawDashedHorizontalLine(
    y: Float,
    color: Color,
    strokeWidthPx: Float,
    dashPx: Float = 6f,
    gapPx: Float = 6f,
) {
    drawLine(
        color = color,
        start = Offset(0f, y),
        end = Offset(size.width, y),
        strokeWidth = strokeWidthPx,
        pathEffect = PathEffect.dashPathEffect(floatArrayOf(dashPx, gapPx), 0f),
        cap = Stroke.DefaultCap,
    )
}

/**
 * Formats [value] with thousands separators, e.g. `1840` -> `"1,840"`.
 *
 * Always uses [Locale.US] rather than the device locale, so Trends'
 * screenshot goldens (which bake in rendered numeral text) stay
 * deterministic across locales.
 */
fun formatThousands(value: Int): String = NumberFormat.getIntegerInstance(Locale.US).format(value)
