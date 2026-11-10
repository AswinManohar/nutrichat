package app.mealsy.android.ui.micronutrients

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.clipRect
import androidx.compose.ui.layout.Layout
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.onClick
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.mealsy.android.R
import app.mealsy.android.design.components.CircleIconButton
import app.mealsy.android.design.components.CoachNote
import app.mealsy.android.design.components.Eyebrow
import app.mealsy.android.design.components.FilterChipPill
import app.mealsy.android.design.components.SegmentedControl
import app.mealsy.android.design.icons.MealsyIcons
import app.mealsy.android.design.theme.MealsyShapes
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType
import app.mealsy.android.design.theme.mealsyTween
import app.mealsy.android.ui.common.ErrorKind
import app.mealsy.android.ui.common.ErrorState
import app.mealsy.android.ui.common.LoadingState
import app.mealsy.domain.MicroRange
import app.mealsy.domain.MicroRow
import app.mealsy.domain.MicroSummary
import app.mealsy.domain.MicroTabSummary
import app.mealsy.domain.lowestTarget
import java.text.DecimalFormat
import java.text.NumberFormat

/** A target nutrient under this percent draws as an outline, not a fill (design `lowStyle: outline`). */
private const val LOW_OUTLINE_PCT = 25

/** Past this share of the axis the percent label moves inside the bar, in cream. */
private const val LABEL_INSIDE_FRACTION = 0.8f

/** The chart's x axis runs 0..100% of the daily value; longer bars are capped and marked "›". */
private const val AXIS_MAX_PCT = 100

private val AXIS_TICKS = listOf(0f, 0.25f, 0.5f, 0.75f, 1f)
private val NAME_COLUMN = 80.dp
private val NAME_GAP = 8.dp
private val BAR_END_GUTTER = 44.dp
private val BAR_HEIGHT = 30.dp
private val BarShape = RoundedCornerShape(topEndPercent = 50, bottomEndPercent = 50)

/**
 * Trends -> Micronutrients: each charted nutrient as a percent of its daily
 * value for today, the last 7 days or the last 30 days, grouped into the
 * catalogue's tabs. Tapping a nutrient opens its amount and top sources.
 *
 * @param onBack Returns to Trends.
 */
@Composable
fun MicronutrientsScreen(
    onBack: () -> Unit,
    viewModel: MicronutrientsViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    MicronutrientsScreenContent(
        state = state,
        onBack = onBack,
        onSelectRange = viewModel::setRange,
        onSelectTab = viewModel::setTab,
        onToggleNutrient = viewModel::toggleNutrient,
        onRetry = viewModel::retry,
        modifier = Modifier.fillMaxSize(),
    )
}

/** The screen without its ViewModel, so goldens render it from a hand-built [MicronutrientsUiState]. */
@Composable
internal fun MicronutrientsScreenContent(
    state: MicronutrientsUiState,
    onBack: () -> Unit,
    onSelectRange: (MicroRange) -> Unit,
    onSelectTab: (String) -> Unit,
    onToggleNutrient: (String) -> Unit,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val colors = MealsyTheme.colors
    Column(modifier = modifier.background(colors.canvas)) {
        Header(range = state.range, onBack = onBack, onSelectRange = onSelectRange)
        val bodyModifier = Modifier.fillMaxWidth().weight(1f)
        when (val content = state.content) {
            MicronutrientsContent.Loading ->
                LoadingState(message = stringResource(R.string.micros_loading), modifier = bodyModifier)
            is MicronutrientsContent.Error ->
                ErrorState(
                    message =
                        stringResource(
                            if (content.kind == ErrorKind.Offline) R.string.error_offline else R.string.micros_error,
                        ),
                    onRetry = onRetry,
                    modifier = bodyModifier,
                )
            MicronutrientsContent.Empty -> EmptyBody(range = state.range, modifier = bodyModifier)
            is MicronutrientsContent.Loaded ->
                LoadedBody(
                    summary = content.summary,
                    refreshing = content.refreshing,
                    tabId = state.tabId,
                    selectedKey = state.selectedKey,
                    range = state.range,
                    onSelectTab = onSelectTab,
                    onToggleNutrient = onToggleNutrient,
                    modifier = bodyModifier,
                )
        }
    }
}

/** Back button, eyebrow, title and range control, pinned above the body with a divider under it. */
@Composable
private fun Header(
    range: MicroRange,
    onBack: () -> Unit,
    onSelectRange: (MicroRange) -> Unit,
) {
    val colors = MealsyTheme.colors
    Column(modifier = Modifier.fillMaxWidth().background(colors.canvas)) {
        Column(
            modifier =
                Modifier
                    .windowInsetsPadding(WindowInsets.statusBars)
                    .padding(start = 20.dp, end = 20.dp, top = 16.dp, bottom = 14.dp),
        ) {
            Box(modifier = Modifier.fillMaxWidth()) {
                CircleIconButton(
                    icon = MealsyIcons.ChevronLeft,
                    contentDescription = stringResource(R.string.micros_back),
                    onClick = onBack,
                    modifier = Modifier.align(Alignment.CenterStart),
                )
                Eyebrow(text = stringResource(R.string.micros_eyebrow), modifier = Modifier.align(Alignment.Center))
            }
            Spacer(modifier = Modifier.height(22.dp))
            Text(text = stringResource(R.string.micros_title), style = MealsyType.display, color = colors.ink)
            Spacer(modifier = Modifier.height(18.dp))
            val labels =
                mapOf(
                    MicroRange.Today to stringResource(R.string.micros_range_today),
                    MicroRange.Week to stringResource(R.string.micros_range_week),
                    MicroRange.Month to stringResource(R.string.micros_range_month),
                )
            SegmentedControl(
                options = MicroRange.entries,
                selected = range,
                onSelect = onSelectRange,
                label = { labels.getValue(it) },
            )
        }
        Box(modifier = Modifier.fillMaxWidth().height(1.dp).background(colors.divider))
    }
}

@Composable
private fun EmptyBody(
    range: MicroRange,
    modifier: Modifier = Modifier,
) {
    Box(modifier = modifier.padding(horizontal = 32.dp), contentAlignment = Alignment.Center) {
        Text(
            text =
                stringResource(
                    if (range == MicroRange.Today) R.string.micros_empty_today else R.string.micros_empty_range,
                ),
            style = MealsyType.body,
            color = MealsyTheme.colors.muted,
            textAlign = TextAlign.Center,
        )
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun LoadedBody(
    summary: MicroSummary,
    refreshing: Boolean,
    tabId: String?,
    selectedKey: String?,
    range: MicroRange,
    onSelectTab: (String) -> Unit,
    onToggleNutrient: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val colors = MealsyTheme.colors
    val tab = summary.tabs.firstOrNull { it.tab.id == tabId } ?: summary.tabs.firstOrNull() ?: return
    val alpha by animateFloatAsState(
        targetValue = if (refreshing) 0.6f else 1f,
        animationSpec = mealsyTween(150),
        label = "microsRefreshingAlpha",
    )
    Column(
        modifier =
            modifier
                .verticalScroll(rememberScrollState())
                .padding(start = 20.dp, end = 20.dp, bottom = 32.dp)
                .alpha(alpha),
    ) {
        Spacer(modifier = Modifier.height(18.dp))
        HeroPill(count = summary.heroCount, total = summary.heroTotal)

        Spacer(modifier = Modifier.height(26.dp))
        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            summary.tabs.forEach { t ->
                FilterChipPill(text = t.tab.name, selected = t.tab.id == tab.tab.id, onClick = { onSelectTab(t.tab.id) })
            }
        }

        Spacer(modifier = Modifier.height(12.dp))
        Surface(shape = MealsyShapes.card, color = colors.surface, modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 18.dp, bottom = 16.dp)) {
                NutrientChart(rows = tab.rows, selectedKey = selectedKey, onToggleNutrient = onToggleNutrient)
                tab.rows.firstOrNull { it.nutrient.key == selectedKey && it.pct != null }?.let {
                    NutrientDetail(row = it, range = range)
                }
            }
        }
        Text(
            text = stringResource(R.string.micros_hint),
            style = MealsyType.label,
            color = colors.inactive,
            modifier = Modifier.padding(start = 4.dp, top = 8.dp),
        )

        Spacer(modifier = Modifier.height(22.dp))
        CoachNote(text = coachText(tab))
    }
}

/**
 * The screen's one olive element: how many target nutrients are past half
 * their daily value, as an olive fill from the start of an `oliveTrack` pill.
 * The labels are drawn twice and clipped at the fill's edge so each glyph
 * gets the text color that reads on what is under it (as [StatusPill] does).
 */
@Composable
private fun HeroPill(
    count: Int,
    total: Int,
) {
    val colors = MealsyTheme.colors
    val fraction = if (total == 0) 0f else count.toFloat() / total
    val description = stringResource(R.string.micros_hero_a11y, count, total)
    BoxWithConstraints(
        modifier =
            Modifier
                .fillMaxWidth()
                .heightIn(min = 46.dp)
                .clip(MealsyShapes.pill)
                .background(colors.oliveTrack)
                .clearAndSetSemantics { contentDescription = description },
    ) {
        val edge = maxWidth * fraction
        // matchParentSize, not fillMaxHeight: in a scrolling column the pill's
        // max height is unbounded, so fillMaxHeight would give the fill 0 height.
        Box(modifier = Modifier.matchParentSize(), contentAlignment = Alignment.CenterStart) {
            Box(modifier = Modifier.fillMaxHeight().width(edge).clip(MealsyShapes.pill).background(colors.olive))
        }
        HeroLabels(
            count = count,
            total = total,
            textColor = colors.oliveText,
            modifier = Modifier.drawWithContent { clipRect(right = edge.toPx()) { this@drawWithContent.drawContent() } },
        )
        HeroLabels(
            count = count,
            total = total,
            textColor = colors.oliveTrackValue,
            modifier = Modifier.drawWithContent { clipRect(left = edge.toPx()) { this@drawWithContent.drawContent() } },
        )
    }
}

@Composable
private fun HeroLabels(
    count: Int,
    total: Int,
    textColor: Color,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier.fillMaxWidth().heightIn(min = 46.dp).padding(horizontal = 18.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(
            text = stringResource(R.string.micros_hero_count, count, total),
            style = MealsyType.body.copy(fontWeight = FontWeight.Medium),
            color = textColor,
            modifier = Modifier.weight(1f, fill = false),
        )
        Spacer(modifier = Modifier.width(8.dp))
        Text(
            text = stringResource(R.string.micros_hero_state),
            style = MealsyType.label.copy(fontWeight = FontWeight.Medium),
            color = textColor,
        )
    }
}

/** One bar per nutrient over 0/25/50/75/100% gridlines, with the axis labels under them. */
@Composable
private fun NutrientChart(
    rows: List<MicroRow>,
    selectedKey: String?,
    onToggleNutrient: (String) -> Unit,
) {
    val colors = MealsyTheme.colors
    // The name column grows with the user's font size so "Phosphorus" never
    // breaks mid-word; the gridlines and axis labels move with it.
    val nameColumn = NAME_COLUMN * LocalDensity.current.fontScale.coerceIn(1f, 2f)
    Column {
        Column(
            verticalArrangement = Arrangement.spacedBy(10.dp),
            modifier =
                Modifier.drawBehind {
                    val start = (nameColumn + NAME_GAP).toPx()
                    val width = size.width - start - BAR_END_GUTTER.toPx()
                    AXIS_TICKS.forEach { f ->
                        val x = start + width * f
                        drawLine(colors.divider, Offset(x, 0f), Offset(x, size.height), strokeWidth = 1.dp.toPx())
                    }
                },
        ) {
            rows.forEach { row ->
                NutrientBarRow(
                    row = row,
                    nameColumn = nameColumn,
                    dimmed = selectedKey != null && selectedKey != row.nutrient.key,
                    selected = selectedKey == row.nutrient.key,
                    onToggle = { onToggleNutrient(row.nutrient.key) },
                )
            }
        }
        AxisLabels(
            modifier =
                Modifier
                    .fillMaxWidth()
                    .padding(start = nameColumn + NAME_GAP, end = BAR_END_GUTTER, top = 10.dp)
                    .clearAndSetSemantics {},
        )
    }
}

@Composable
private fun NutrientBarRow(
    row: MicroRow,
    nameColumn: Dp,
    dimmed: Boolean,
    selected: Boolean,
    onToggle: () -> Unit,
) {
    val colors = MealsyTheme.colors
    val n = row.nutrient
    val pct = row.pct
    val description =
        when {
            pct == null -> stringResource(R.string.micros_row_no_data_a11y, n.name)
            n.isLimit -> stringResource(R.string.micros_row_limit_a11y, n.name, pct)
            else -> stringResource(R.string.micros_row_a11y, n.name, pct)
        }
    val openLabel = stringResource(R.string.micros_row_open)
    val alpha by animateFloatAsState(
        targetValue = if (dimmed) 0.35f else 1f,
        animationSpec = mealsyTween(200),
        label = "microsRowAlpha",
    )
    val interactive = pct != null
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier =
            Modifier
                .fillMaxWidth()
                .alpha(alpha)
                .then(if (interactive) Modifier.clickable(onClickLabel = openLabel, onClick = onToggle) else Modifier)
                .clearAndSetSemantics {
                    contentDescription = description
                    if (interactive) {
                        role = Role.Button
                        this.selected = selected
                        onClick(label = openLabel) {
                            onToggle()
                            true
                        }
                    }
                },
    ) {
        Column(modifier = Modifier.width(nameColumn), horizontalAlignment = Alignment.End) {
            Text(text = n.name, style = MealsyType.label.copy(fontSize = 13.sp), color = colors.ink, textAlign = TextAlign.End)
            if (n.isLimit) {
                Text(text = stringResource(R.string.micros_limit), style = MealsyType.tinyTag, color = colors.muted)
            }
        }
        Spacer(modifier = Modifier.width(NAME_GAP))
        BoxWithConstraints(
            modifier = Modifier.weight(1f).padding(end = BAR_END_GUTTER).height(BAR_HEIGHT),
            contentAlignment = Alignment.CenterStart,
        ) {
            if (pct == null) {
                Text(text = stringResource(R.string.micros_no_data), style = MealsyType.label, color = colors.muted)
                return@BoxWithConstraints
            }
            val fraction = (pct.toFloat() / AXIS_MAX_PCT).coerceIn(0f, 1f)
            val barWidth = maxWidth * fraction
            val outlined = !n.isLimit && pct < LOW_OUTLINE_PCT
            val bar = Modifier.fillMaxHeight().width(barWidth)
            Box(
                modifier =
                    if (outlined) {
                        bar.border(1.5.dp, colors.ink, BarShape)
                    } else {
                        bar.background(colors.ink, BarShape)
                    },
            )
            val label =
                if (pct > AXIS_MAX_PCT) {
                    stringResource(R.string.micros_pct_over, pct)
                } else {
                    stringResource(R.string.micros_pct, pct)
                }
            val labelStyle = MealsyType.badge
            if (fraction > LABEL_INSIDE_FRACTION) {
                Box(modifier = Modifier.width(barWidth), contentAlignment = Alignment.CenterEnd) {
                    Text(text = label, style = labelStyle, color = colors.canvas, modifier = Modifier.padding(end = 8.dp))
                }
            } else {
                Text(text = label, style = labelStyle, color = colors.ink, modifier = Modifier.offset(x = barWidth + 6.dp))
            }
        }
    }
}

/**
 * "0%  25%  50%  75%  100%", each centered under its gridline. When the labels
 * would touch (large font scales), only 0%, 50% and 100% are shown.
 */
@Composable
private fun AxisLabels(modifier: Modifier = Modifier) {
    val colors = MealsyTheme.colors
    Layout(
        modifier = modifier,
        content = {
            AXIS_TICKS.forEach { f ->
                Text(
                    text = stringResource(R.string.micros_pct, (f * AXIS_MAX_PCT).toInt()),
                    style = MealsyType.label.copy(fontSize = 11.sp),
                    color = colors.inactive,
                    maxLines = 1,
                )
            }
        },
    ) { measurables, constraints ->
        val placeables = measurables.map { it.measure(constraints.copy(minWidth = 0)) }
        val height = placeables.maxOfOrNull { it.height } ?: 0
        val step = constraints.maxWidth * (AXIS_TICKS[1] - AXIS_TICKS[0])
        val gap = 4.dp.toPx()
        val crowded = placeables.zipWithNext().any { (a, b) -> (a.width + b.width) / 2f + gap > step }
        layout(constraints.maxWidth, height) {
            placeables.forEachIndexed { i, p ->
                if (crowded && i % 2 == 1) return@forEachIndexed
                val center = (constraints.maxWidth * AXIS_TICKS[i]).toInt()
                p.placeRelative(center - p.width / 2, 0)
            }
        }
    }
}

/** The tapped nutrient's percent, amount against its daily value or limit, and top sources. */
@Composable
private fun NutrientDetail(
    row: MicroRow,
    range: MicroRange,
) {
    val colors = MealsyTheme.colors
    val n = row.nutrient
    val amount = formatAmount(row.avgAmount ?: 0.0)
    val dv = formatAmount(n.dailyValue)
    val amountLine =
        stringResource(
            if (n.isLimit) R.string.micros_amount_limit else R.string.micros_amount_value,
            amount,
            dv,
            n.unit,
        )
    val sources =
        when (row.topFoods.size) {
            0 -> stringResource(R.string.micros_sources_none)
            1 -> stringResource(R.string.micros_sources_one, midSentence(row.topFoods[0]))
            else -> stringResource(R.string.micros_sources_two, midSentence(row.topFoods[0]), midSentence(row.topFoods[1]))
        }
    Column(modifier = Modifier.padding(top = 12.dp)) {
        Box(modifier = Modifier.fillMaxWidth().height(1.dp).background(colors.divider))
        Spacer(modifier = Modifier.height(14.dp))
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text(text = n.name, style = MealsyType.section, color = colors.ink, modifier = Modifier.alignByBaseline())
            Text(
                text = stringResource(R.string.micros_pct, row.pct ?: 0),
                style = MealsyType.bigNumber,
                color = colors.ink,
                modifier = Modifier.alignByBaseline(),
            )
        }
        Spacer(modifier = Modifier.height(6.dp))
        Text(
            text = if (range == MicroRange.Today) amountLine else stringResource(R.string.micros_amount_average, amountLine),
            style = MealsyType.label.copy(fontSize = 13.sp),
            color = colors.muted,
        )
        Spacer(modifier = Modifier.height(6.dp))
        Text(text = sources, style = MealsyType.label.copy(fontSize = 13.sp, lineHeight = 19.sp), color = colors.ink)
    }
}

/** The coach note: the tab's lowest target under half its daily value with a food tip, else a well done. */
@Composable
private fun coachText(tab: MicroTabSummary): String {
    val low = lowestTarget(tab) ?: return stringResource(R.string.micros_coach_all_good)
    val tip =
        microTipRes(low.nutrient.key)?.let { stringResource(it) }
            ?: stringResource(R.string.micros_tip_generic, low.nutrient.name.lowercase())
    return stringResource(R.string.micros_coach_low, low.nutrient.name, low.pct ?: 0, tip)
}

/** 1,426 for amounts of 100 or more, else one decimal at most (2.4, 0.9, 18). */
internal fun formatAmount(value: Double): String =
    if (value >= 100) NumberFormat.getIntegerInstance().format(Math.round(value)) else DecimalFormat("0.#").format(value)

/** Lowercases a food's first letter for use mid-sentence, unless it starts an acronym ("BBQ sauce"). */
internal fun midSentence(food: String): String =
    if (food.length > 1 && food[1].isUpperCase()) food else food.replaceFirstChar { it.lowercaseChar() }
