package app.mealsy.android.ui.trends

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.mealsy.android.R
import app.mealsy.android.design.components.Eyebrow
import app.mealsy.android.design.components.InsetDivider
import app.mealsy.android.design.components.ListContainer
import app.mealsy.android.design.components.MetricCard
import app.mealsy.android.design.components.PastelIconCircle
import app.mealsy.android.design.components.SegmentedControl
import app.mealsy.android.design.components.ShareBar
import app.mealsy.android.design.components.TagTone
import app.mealsy.android.design.components.drawDashedHorizontalLine
import app.mealsy.android.design.components.formatThousands
import app.mealsy.android.design.components.niceAxisMax
import app.mealsy.android.design.icons.MealsyIcons
import app.mealsy.android.design.mascot.Olli
import app.mealsy.android.design.mascot.OlliSize
import app.mealsy.android.design.theme.MealsyColors
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType
import app.mealsy.android.design.theme.mealsyScreenPadding
import app.mealsy.android.design.theme.mealsyTween
import app.mealsy.android.ui.common.ErrorKind
import app.mealsy.android.ui.common.ErrorState
import app.mealsy.android.ui.common.LoadingState
import app.mealsy.data.repo.CategorySlice
import app.mealsy.data.repo.DayPoint
import java.time.DayOfWeek
import java.time.LocalDate
import kotlin.math.roundToInt

/**
 * The Trends screen: a week/month toggle, three headline metric cards, two
 * hand-drawn [Canvas] charts (kcal bars, protein line) and a per-category
 * breakdown with kcal share bars.
 *
 * @param viewModel Supplies [TrendsViewModel.window]/[TrendsViewModel.uiState]
 *   and drives refetches via [TrendsViewModel.setWindow]/[TrendsViewModel.retry].
 */
@Composable
fun TrendsScreen(viewModel: TrendsViewModel = hiltViewModel()) {
    val window by viewModel.window.collectAsStateWithLifecycle()
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()

    TrendsContent(
        window = window,
        uiState = uiState,
        onSelectWindow = { viewModel.setWindow(it) },
        onRetry = viewModel::retry,
        modifier = Modifier.fillMaxSize(),
    )
}

/**
 * The Trends screen's content, decoupled from [TrendsViewModel] so screenshot
 * goldens can render it directly from hand-built [TrendsUiState] values.
 *
 * @param today The date the day-of-week bars/labels are anchored to. Defaults
 *   to the device's current date; goldens and tests pass a fixed date so
 *   rendered weekday labels stay deterministic.
 */
@Composable
internal fun TrendsContent(
    window: TrendsWindow,
    uiState: TrendsUiState,
    onSelectWindow: (TrendsWindow) -> Unit,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
    today: LocalDate = LocalDate.now(),
) {
    when (uiState) {
        TrendsUiState.Loading ->
            LoadingState(
                message = stringResource(R.string.trends_loading),
                modifier = modifier,
            )
        is TrendsUiState.Error ->
            ErrorState(
                message =
                    stringResource(
                        when (uiState.kind) {
                            ErrorKind.Offline -> R.string.error_offline
                            ErrorKind.LoadFailed -> R.string.trends_error_load_failed
                        },
                    ),
                onRetry = onRetry,
                modifier = modifier,
            )
        else -> TrendsBody(window, uiState, onSelectWindow, today, modifier)
    }
}

@Composable
private fun TrendsBody(
    window: TrendsWindow,
    uiState: TrendsUiState,
    onSelectWindow: (TrendsWindow) -> Unit,
    today: LocalDate,
    modifier: Modifier = Modifier,
) {
    val colors = MealsyTheme.colors
    Column(
        modifier =
            modifier
                .verticalScroll(rememberScrollState())
                .mealsyScreenPadding(),
    ) {
        Eyebrow(text = stringResource(R.string.trends_eyebrow))
        Spacer(modifier = Modifier.height(6.dp))
        Text(
            text =
                stringResource(
                    if (window == TrendsWindow.WEEK) R.string.trends_title_week else R.string.trends_title_month,
                ),
            style = MealsyType.display,
            color = colors.ink,
        )

        Spacer(modifier = Modifier.height(20.dp))

        val weekLabel = stringResource(R.string.trends_segment_week)
        val monthLabel = stringResource(R.string.trends_segment_month)
        SegmentedControl(
            options = listOf(TrendsWindow.WEEK, TrendsWindow.MONTH),
            selected = window,
            onSelect = onSelectWindow,
            label = { if (it == TrendsWindow.WEEK) weekLabel else monthLabel },
        )

        Spacer(modifier = Modifier.height(24.dp))

        when (uiState) {
            TrendsUiState.Empty -> TrendsEmptyState()
            is TrendsUiState.Loaded -> TrendsLoadedContent(window, uiState, today)
            else -> Unit
        }
    }
}

@Composable
private fun TrendsEmptyState(modifier: Modifier = Modifier) {
    Column(
        modifier = modifier.fillMaxWidth().padding(top = 40.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Olli(size = OlliSize.Done)
        Spacer(modifier = Modifier.height(16.dp))
        Text(
            text = stringResource(R.string.trends_empty_message),
            style = MealsyType.body,
            color = MealsyTheme.colors.muted,
        )
    }
}

@Composable
private fun TrendsLoadedContent(
    window: TrendsWindow,
    state: TrendsUiState.Loaded,
    today: LocalDate,
) {
    val bars = buildTrendsDayBars(window, state.trends.days, today)
    val labels = trendsDayLabels(window, bars)

    // A refreshing Week/Month toggle keeps this whole stale Loaded content
    // on screen (see TrendsViewModel's stale-while-revalidate load()) rather
    // than blanking to Loading; a light fade is the only visual cue that a
    // refetch is in flight.
    val contentAlpha by
        animateFloatAsState(
            targetValue = if (state.refreshing) 0.6f else 1f,
            animationSpec = mealsyTween(150),
            label = "trendsRefreshingAlpha",
        )

    Column(modifier = Modifier.alpha(contentAlpha)) {
        TrendsLoadedBody(window, state, bars, labels)
    }
}

@Composable
private fun TrendsLoadedBody(
    window: TrendsWindow,
    state: TrendsUiState.Loaded,
    bars: List<TrendsDayBar>,
    labels: List<String>,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        MetricCard(
            label = stringResource(R.string.trends_metric_avg_kcal),
            value = formatThousands(state.avgKcal),
            modifier = Modifier.weight(1f),
        )
        MetricCard(
            label = stringResource(R.string.trends_metric_avg_protein),
            value = "${state.avgProteinG}g",
            modifier = Modifier.weight(1f),
        )
        MetricCard(
            label = stringResource(R.string.trends_metric_days_logged),
            value =
                stringResource(
                    R.string.trends_days_logged_value,
                    state.daysLoggedCount,
                    state.daysInWindow,
                ),
            modifier = Modifier.weight(1f),
        )
    }

    Spacer(modifier = Modifier.height(24.dp))

    Eyebrow(text = stringResource(R.string.trends_chart_calories))
    Spacer(modifier = Modifier.height(8.dp))
    val kcalDesc =
        stringResource(
            R.string.trends_kcal_chart_desc,
            state.daysInWindow,
            formatThousands(state.avgKcal),
        )
    KcalBarChart(
        bars = bars,
        labels = labels,
        goalKcal = state.kcalGoal,
        contentDescriptionText = kcalDesc,
    )

    Spacer(modifier = Modifier.height(20.dp))

    Eyebrow(text = stringResource(R.string.trends_chart_protein))
    Spacer(modifier = Modifier.height(8.dp))
    val proteinDesc =
        stringResource(
            R.string.trends_protein_chart_desc,
            state.daysInWindow,
            state.avgProteinG,
        )
    ProteinLineChart(
        bars = bars,
        goalProtein = state.proteinGoal,
        contentDescriptionText = proteinDesc,
    )

    Spacer(modifier = Modifier.height(28.dp))

    Eyebrow(text = stringResource(R.string.trends_by_category))
    Spacer(modifier = Modifier.height(12.dp))

    ListContainer {
        state.categories.forEachIndexed { index, slice ->
            CategoryRow(slice)
            if (index != state.categories.lastIndex) InsetDivider()
        }
    }
}

/**
 * The screen's one olive element: kcal bars filled [MealsyTheme.colors]`.olive`
 * on an `oliveTrack` track, with the kcal goal as a 1dp dashed ink line.
 */
@Composable
private fun KcalBarChart(
    bars: List<TrendsDayBar>,
    labels: List<String>,
    goalKcal: Double?,
    contentDescriptionText: String,
    modifier: Modifier = Modifier,
) {
    val colors = MealsyTheme.colors
    val chartHeight = 120.dp
    // Grows bar heights from the floor up whenever `bars` changes identity —
    // i.e. on a Week/Month toggle — so the chart visibly morphs between
    // ranges instead of snapping. `remember(bars)` resets `revealed` to
    // false on each new bar set; ReducedMotion's zero-duration tween makes
    // the resulting animateFloatAsState land on 1f effectively instantly.
    var revealed by remember(bars) { mutableStateOf(false) }
    LaunchedEffect(bars) { revealed = true }
    val revealProgress by animateFloatAsState(
        targetValue = if (revealed) 1f else 0f,
        animationSpec = mealsyTween(280),
        label = "trendsKcalReveal",
    )
    Column(modifier = modifier.fillMaxWidth()) {
        val maxRaw = maxOf(bars.maxOfOrNull { it.kcal }?.toFloat() ?: 0f, (goalKcal ?: 0.0).toFloat())
        val axisMax = niceAxisMax(maxRaw)
        val goalFraction =
            if (goalKcal != null && axisMax > 0f) (goalKcal.toFloat() / axisMax).coerceIn(0f, 1f) else null
        Box(modifier = Modifier.fillMaxWidth()) {
            Canvas(
                modifier =
                    Modifier
                        .fillMaxWidth()
                        .height(chartHeight)
                        .clearAndSetSemantics { contentDescription = contentDescriptionText },
            ) {
                val slotWidth = if (bars.isEmpty()) size.width else size.width / bars.size
                val barWidth = slotWidth * 0.5f
                bars.forEachIndexed { index, bar ->
                    val left = index * slotWidth + (slotWidth - barWidth) / 2f
                    drawRoundRect(
                        color = colors.oliveTrack,
                        topLeft = Offset(left, 0f),
                        size = Size(barWidth, size.height),
                        cornerRadius = CornerRadius(barWidth / 2f, barWidth / 2f),
                    )
                    if (axisMax > 0f && bar.kcal > 0.0) {
                        val fraction = (bar.kcal.toFloat() / axisMax).coerceIn(0f, 1f)
                        val barHeight = size.height * fraction * revealProgress
                        drawRoundRect(
                            color = colors.olive,
                            topLeft = Offset(left, size.height - barHeight),
                            size = Size(barWidth, barHeight),
                            cornerRadius = CornerRadius(barWidth / 2f, barWidth / 2f),
                        )
                    }
                }
                if (goalFraction != null) {
                    val goalY = size.height * (1f - goalFraction)
                    drawDashedHorizontalLine(y = goalY, color = colors.ink, strokeWidthPx = 1.dp.toPx())
                }
            }
            if (goalFraction != null) {
                TargetLineLabel(goalFraction = goalFraction, chartHeight = chartHeight, colors = colors)
            }
        }
        Spacer(modifier = Modifier.height(6.dp))
        Row(modifier = Modifier.fillMaxWidth()) {
            labels.forEach { label ->
                Text(
                    text = label,
                    style = MealsyType.label.copy(fontSize = 11.sp),
                    color = colors.muted,
                    textAlign = TextAlign.Center,
                    maxLines = 1,
                    softWrap = false,
                    overflow = TextOverflow.Visible,
                    modifier = Modifier.weight(1f),
                )
            }
        }
    }
}

/**
 * Small "Target" caption for a chart's dashed goal/target line, positioned
 * just above the line so it never overlaps the bars/points beneath it. Kept
 * as a tiny label rather than an in-line annotation to stay within the
 * design system's existing type scale ([MealsyType.tinyTag]).
 */
@Composable
private fun BoxScope.TargetLineLabel(
    goalFraction: Float,
    chartHeight: Dp,
    colors: MealsyColors,
) {
    val labelHeight = 13.dp
    val lineOffset = chartHeight * (1f - goalFraction)
    val topOffset = (lineOffset - labelHeight).coerceAtLeast(0.dp)
    Text(
        text = stringResource(R.string.trends_target_label),
        style = MealsyType.tinyTag,
        color = colors.muted,
        modifier =
            Modifier
                .align(Alignment.TopEnd)
                .offset(y = topOffset),
    )
}

/**
 * The protein trend line: a 2dp ink stroke over a `divider`-colored grid,
 * with the protein goal as a dashed reference line. Deliberately olive-free
 * — [KcalBarChart] already spends the screen's single olive element.
 */
@Composable
private fun ProteinLineChart(
    bars: List<TrendsDayBar>,
    goalProtein: Double?,
    contentDescriptionText: String,
    modifier: Modifier = Modifier,
) {
    val colors = MealsyTheme.colors
    val chartHeight = 100.dp
    val maxRaw = maxOf(bars.maxOfOrNull { it.proteinG }?.toFloat() ?: 0f, (goalProtein ?: 0.0).toFloat())
    val axisMax = niceAxisMax(maxRaw)
    val goalFraction =
        if (goalProtein != null && axisMax > 0f) (goalProtein.toFloat() / axisMax).coerceIn(0f, 1f) else null
    // Same reveal-on-window-change treatment as KcalBarChart's bars, so the
    // line visibly grows from the floor rather than snapping between ranges.
    var revealed by remember(bars) { mutableStateOf(false) }
    LaunchedEffect(bars) { revealed = true }
    val revealProgress by animateFloatAsState(
        targetValue = if (revealed) 1f else 0f,
        animationSpec = mealsyTween(280),
        label = "trendsProteinReveal",
    )
    Box(modifier = modifier.fillMaxWidth()) {
        Canvas(
            modifier =
                Modifier
                    .fillMaxWidth()
                    .height(chartHeight)
                    .clearAndSetSemantics { contentDescription = contentDescriptionText },
        ) {
            repeat(3) { i ->
                val y = size.height * (i + 1) / 4f
                drawLine(
                    color = colors.divider,
                    start = Offset(0f, y),
                    end = Offset(size.width, y),
                    strokeWidth = 1.dp.toPx(),
                )
            }
            if (bars.size >= 2 && axisMax > 0f) {
                // Days with no logs break the line into separate segments
                // ("no point" for that day) instead of plotting 0 g, which
                // would otherwise read as "ate zero protein".
                val horizontalInset = 4.dp.toPx()
                val plotWidth = size.width - horizontalInset * 2f
                proteinLineSegments(bars).forEach { indices ->
                    val segment = Path()
                    indices.forEachIndexed { i, index ->
                        val bar = bars[index]
                        val x = horizontalInset + index * plotWidth / (bars.size - 1)
                        val fraction = (bar.proteinG.toFloat() / axisMax).coerceIn(0f, 1f)
                        val y = size.height * (1f - fraction * revealProgress)
                        if (i == 0) segment.moveTo(x, y) else segment.lineTo(x, y)
                    }
                    drawPath(
                        path = segment,
                        color = colors.ink,
                        style = Stroke(width = 2.dp.toPx(), cap = StrokeCap.Round, join = StrokeJoin.Round),
                    )
                }
            }
            if (goalFraction != null) {
                val goalY = size.height * (1f - goalFraction)
                drawDashedHorizontalLine(y = goalY, color = colors.ink, strokeWidthPx = 1.dp.toPx())
            }
        }
        if (goalFraction != null) {
            TargetLineLabel(goalFraction = goalFraction, chartHeight = chartHeight, colors = colors)
        }
    }
}

/**
 * One "By category" row: pastel icon, meal-type label, muted "avg N kcal ·
 * M×" trailing text, and a [ShareBar] beneath showing the category's share
 * of total kcal. Composed by hand (rather than via [app.mealsy.android.design.components.ListRow])
 * so a bar can render beneath the row's main content while keeping the same
 * padding/min-height/typography as a plain [ListRow].
 */
@Composable
private fun CategoryRow(
    slice: CategorySlice,
    modifier: Modifier = Modifier,
) {
    val colors = MealsyTheme.colors
    val shareFraction = (slice.shareKcalPct / 100.0).toFloat()
    val trailing =
        stringResource(
            R.string.trends_category_avg,
            formatThousands(slice.avgKcal.roundToInt()),
            slice.nMeals,
        )
    val shareDescription =
        stringResource(
            R.string.trends_category_share_desc,
            stringResource(mealTypeLabelRes(slice.mealType)),
            (slice.shareKcalPct.roundToInt()),
        )
    Column(
        modifier =
            modifier
                .fillMaxWidth()
                .defaultMinSize(minHeight = 48.dp)
                .padding(vertical = 9.dp, horizontal = 16.dp),
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            PastelIconCircle(
                icon = mealTypeIcon(slice.mealType),
                tone = mealTypeTone(slice.mealType),
                contentDescription = null,
            )
            Text(
                text = stringResource(mealTypeLabelRes(slice.mealType)),
                style = MealsyType.body,
                color = colors.ink,
                modifier = Modifier.weight(1f),
            )
            Text(text = trailing, style = MealsyType.label, color = colors.muted)
        }
        Spacer(modifier = Modifier.height(8.dp))
        ShareBar(
            fraction = shareFraction,
            modifier = Modifier.semantics { contentDescription = shareDescription },
        )
    }
}

/** Resolves a meal-type wire key to its "Today's meals" icon — mirrors `HomeScreen`'s mapping. */
private fun mealTypeIcon(mealType: String) =
    when (mealType) {
        "breakfast" -> MealsyIcons.Breakfast
        "lunch" -> MealsyIcons.Lunch
        "dinner" -> MealsyIcons.Dinner
        else -> MealsyIcons.Snack
    }

/** Resolves a meal-type wire key to its pastel tone — mirrors `HomeScreen`'s `MEAL_ROW_ORDER`. */
private fun mealTypeTone(mealType: String): TagTone =
    when (mealType) {
        "breakfast" -> TagTone.Butter
        "lunch" -> TagTone.Leaf
        "dinner" -> TagTone.Pink
        else -> TagTone.Powder
    }

private fun mealTypeLabelRes(mealType: String): Int =
    when (mealType) {
        "breakfast" -> R.string.home_meal_breakfast
        "lunch" -> R.string.home_meal_lunch
        "dinner" -> R.string.home_meal_dinner
        else -> R.string.home_meal_snack
    }

/** One day slot for the charts: the backend's [DayPoint] value, or zero when nothing was logged. */
internal data class TrendsDayBar(val date: LocalDate, val kcal: Double, val proteinG: Double, val hasData: Boolean)

/**
 * Builds one [TrendsDayBar] per day in the window ending at [today] (inclusive),
 * so charts always draw a full week/month of slots — missing days render as
 * zero-height bars rather than being skipped, which keeps weekday labels
 * aligned to the correct column.
 */
internal fun buildTrendsDayBars(
    window: TrendsWindow,
    days: List<DayPoint>,
    today: LocalDate,
): List<TrendsDayBar> {
    val byDate =
        days.mapNotNull { point ->
            runCatching { LocalDate.parse(point.date) }.getOrNull()?.let { it to point }
        }.toMap()
    val start = today.minusDays((window.days - 1).toLong())
    return (0 until window.days).map { offset ->
        val date = start.plusDays(offset.toLong())
        val point = byDate[date]
        TrendsDayBar(
            date = date,
            kcal = point?.kcal ?: 0.0,
            proteinG = point?.proteinG ?: 0.0,
            hasData = point != null,
        )
    }
}

/**
 * Labels beneath the kcal chart's bars. The week window shows every day's
 * single-letter weekday initial (`M T W T F S S`); the month window thins
 * labels to the first, last and every 6th day so 30 labels don't collide.
 */
internal fun trendsDayLabels(
    window: TrendsWindow,
    bars: List<TrendsDayBar>,
): List<String> =
    when (window) {
        TrendsWindow.WEEK -> bars.map { weekdayInitial(it.date) }
        TrendsWindow.MONTH ->
            bars.mapIndexed { index, bar ->
                if (index == 0 || index == bars.lastIndex || index % 6 == 0) {
                    bar.date.dayOfMonth.toString()
                } else {
                    ""
                }
            }
    }

private fun weekdayInitial(date: LocalDate): String =
    when (date.dayOfWeek) {
        DayOfWeek.MONDAY -> "M"
        DayOfWeek.TUESDAY -> "T"
        DayOfWeek.WEDNESDAY -> "W"
        DayOfWeek.THURSDAY -> "T"
        DayOfWeek.FRIDAY -> "F"
        DayOfWeek.SATURDAY -> "S"
        DayOfWeek.SUNDAY -> "S"
    }

/**
 * Groups [bars] into runs of consecutive indices that all [TrendsDayBar.hasData],
 * so [ProteinLineChart] can draw one path per run instead of a single path
 * that would otherwise plot no-log days as 0 g. A day with no logs ends the
 * current run and starts a new one on the next logged day — that day is
 * simply not plotted, leaving a gap in the line rather than a dip to zero.
 *
 * Returns each run as a list of bar indices (length 1 for an isolated logged
 * day surrounded by gaps, which draws as a zero-length path and thus no
 * visible mark).
 */
internal fun proteinLineSegments(bars: List<TrendsDayBar>): List<List<Int>> {
    val segments = mutableListOf<MutableList<Int>>()
    bars.forEachIndexed { index, bar ->
        if (!bar.hasData) return@forEachIndexed
        val current = segments.lastOrNull()
        if (current != null && current.last() == index - 1) {
            current.add(index)
        } else {
            segments.add(mutableListOf(index))
        }
    }
    return segments
}
