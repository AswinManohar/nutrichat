package app.mealsy.android.ui.home

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.mealsy.android.R
import app.mealsy.android.design.theme.MealsyShapes
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType

private val CellShape = RoundedCornerShape(8.dp)
private val SwatchShape = RoundedCornerShape(3.dp)

/** Protein and fiber cells are short; carbs, the largest macro by weight, gets the tall cell. */
private val ShortCellHeight = 34.dp
private val TallCellHeight = 52.dp

/** Which macro row a week-grid cell belongs to; fixes its fill, text color and height. */
private enum class WeekMacro { Protein, Fiber, Carbs }

/**
 * Home's "This week" section: a heading with the date range, then one column per
 * day showing the kcal total over protein, fiber and carbs cells. A cell under
 * 70% of its goal renders as a dashed outline instead of a fill.
 *
 * @param week The built grid, or `null` before it loads or when it failed to load;
 *   with [unavailable] also false the section renders nothing.
 * @param unavailable Whether the trends fetch failed; shows an inline message in place of the grid.
 */
@Composable
internal fun HomeWeekSection(
    week: HomeWeek?,
    unavailable: Boolean,
    modifier: Modifier = Modifier,
) {
    if (week == null && !unavailable) return
    val colors = MealsyTheme.colors
    Column(modifier = modifier) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text(
                text = stringResource(R.string.home_this_week),
                style = MealsyType.section,
                color = colors.ink,
                modifier = Modifier.alignByBaseline(),
            )
            if (week != null) {
                Text(
                    text = stringResource(R.string.home_week_range, week.startLabel),
                    style = MealsyType.label,
                    color = colors.muted,
                    modifier = Modifier.alignByBaseline(),
                )
            }
        }

        Spacer(modifier = Modifier.height(12.dp))

        Surface(shape = MealsyShapes.card, color = colors.surface, modifier = Modifier.fillMaxWidth()) {
            when {
                week != null -> WeekGrid(week)
                unavailable ->
                    Text(
                        text = stringResource(R.string.home_week_unavailable),
                        style = MealsyType.body,
                        color = colors.muted,
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 14.dp),
                    )
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun WeekGrid(week: HomeWeek) {
    val colors = MealsyTheme.colors
    Column(modifier = Modifier.padding(start = 12.dp, end = 12.dp, top = 14.dp, bottom = 12.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(5.dp),
        ) {
            week.days.forEach { day ->
                WeekColumn(day = day, modifier = Modifier.weight(1f))
            }
        }

        Spacer(modifier = Modifier.height(12.dp))
        Box(modifier = Modifier.fillMaxWidth().height(1.dp).background(colors.divider))
        Spacer(modifier = Modifier.height(10.dp))

        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(14.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            LegendItem(label = stringResource(R.string.home_metric_protein), fill = colors.ink)
            LegendItem(label = stringResource(R.string.home_week_legend_fiber), fill = colors.oliveTrack)
            LegendItem(label = stringResource(R.string.home_metric_carbs), fill = colors.canvas)
            if (week.showsGoalLegend) {
                LegendItem(label = stringResource(R.string.home_week_legend_low), fill = null)
            }
        }
    }
}

/** One day: kcal badge, the three macro cells, then the weekday. Read by TalkBack as one sentence. */
@Composable
private fun WeekColumn(
    day: HomeWeekDay,
    modifier: Modifier = Modifier,
) {
    val colors = MealsyTheme.colors
    val dayLabel = if (day.isToday) stringResource(R.string.home_week_today) else day.weekday
    val description =
        if (day.kcal == null) {
            stringResource(R.string.home_week_day_empty_a11y, dayLabel)
        } else {
            stringResource(
                R.string.home_week_day_a11y,
                dayLabel,
                day.kcal,
                cellDescription(day.protein, R.string.home_week_a11y_protein),
                cellDescription(day.fiber, R.string.home_week_a11y_fiber),
                cellDescription(day.carbs, R.string.home_week_a11y_carbs),
            )
        }

    Column(
        modifier = modifier.clearAndSetSemantics { contentDescription = description },
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Box(
            modifier =
                Modifier
                    .align(Alignment.CenterHorizontally)
                    .padding(bottom = 2.dp)
                    .background(colors.ink, MealsyShapes.pill)
                    .padding(horizontal = 6.dp, vertical = 2.dp),
        ) {
            // No auto-size text in this Compose version: at large font scales a full
            // "1,980" overflows a seventh of the screen, so fall back to "2.0k".
            var compact by remember(day.kcal) { mutableStateOf(false) }
            Text(
                text =
                    when {
                        day.kcal == null -> stringResource(R.string.home_week_no_kcal)
                        compact && day.kcalThousands != null ->
                            stringResource(R.string.home_week_kcal_compact, day.kcalThousands)
                        else -> day.kcal
                    },
                style = MealsyType.badge.copy(fontSize = 10.sp, lineHeight = 13.sp),
                color = colors.canvas,
                maxLines = 1,
                softWrap = false,
                onTextLayout = { if (it.didOverflowWidth) compact = true },
            )
        }
        WeekCell(cell = day.protein, macro = WeekMacro.Protein)
        WeekCell(cell = day.fiber, macro = WeekMacro.Fiber)
        WeekCell(cell = day.carbs, macro = WeekMacro.Carbs)
        Text(
            text = dayLabel,
            style =
                MealsyType.label.copy(
                    fontSize = 11.sp,
                    fontWeight = if (day.isToday) FontWeight.SemiBold else FontWeight.Normal,
                ),
            color = if (day.isToday) colors.ink else colors.muted,
            textAlign = TextAlign.Center,
            maxLines = 1,
            modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
        )
    }
}

/**
 * One macro cell. A `null` [cell] (nothing logged that day) and a low cell both
 * render as the dashed outline; only a logged cell carries a label.
 */
@Composable
private fun WeekCell(
    cell: HomeWeekCell?,
    macro: WeekMacro,
) {
    val colors = MealsyTheme.colors
    val (fill, textColor) =
        when (macro) {
            WeekMacro.Protein -> colors.ink to colors.canvas
            WeekMacro.Fiber -> colors.oliveTrack to colors.oliveTrackValue
            WeekMacro.Carbs -> colors.canvas to colors.ink
        }
    val height = if (macro == WeekMacro.Carbs) TallCellHeight else ShortCellHeight
    val outlined = cell == null || cell.low
    val base = Modifier.fillMaxWidth().height(height)
    Box(
        modifier = if (outlined) base.dashedOutline(colors.inactive, 8.dp) else base.background(fill, CellShape),
        contentAlignment = Alignment.Center,
    ) {
        if (cell != null) {
            Text(
                text = stringResource(macroLabelRes(macro), cell.grams),
                style = MealsyType.badge.copy(fontSize = 11.sp),
                color = if (outlined) colors.muted else textColor,
                maxLines = 1,
                softWrap = false,
            )
        }
    }
}

/** A legend swatch and its label; a `null` [fill] draws the dashed "under goal" swatch. */
@Composable
private fun LegendItem(
    label: String,
    fill: Color?,
) {
    val colors = MealsyTheme.colors
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        val swatch = Modifier.size(10.dp)
        Box(modifier = if (fill == null) swatch.dashedOutline(colors.inactive, 3.dp) else swatch.background(fill, SwatchShape))
        Text(text = label, style = MealsyType.label, color = colors.muted)
    }
}

/** A 1dp dashed rounded-rect outline drawn inside the bounds, as CSS `border: 1px dashed`. */
private fun Modifier.dashedOutline(
    color: Color,
    radius: Dp,
): Modifier =
    drawBehind {
        val stroke = 1.dp.toPx()
        val inset = stroke / 2
        drawRoundRect(
            color = color,
            topLeft = Offset(inset, inset),
            size = Size(size.width - stroke, size.height - stroke),
            cornerRadius = CornerRadius(radius.toPx() - inset),
            style = Stroke(width = stroke, pathEffect = PathEffect.dashPathEffect(floatArrayOf(3.dp.toPx(), 3.dp.toPx()))),
        )
    }

private fun macroLabelRes(macro: WeekMacro): Int =
    when (macro) {
        WeekMacro.Protein -> R.string.home_week_cell_protein
        WeekMacro.Fiber -> R.string.home_week_cell_fiber
        WeekMacro.Carbs -> R.string.home_week_cell_carbs
    }

@Composable
private fun cellDescription(
    cell: HomeWeekCell?,
    macroRes: Int,
): String {
    val grams = cell?.grams ?: 0
    val text = stringResource(macroRes, grams)
    return if (cell?.low == true) stringResource(R.string.home_week_a11y_under_goal, text) else text
}
