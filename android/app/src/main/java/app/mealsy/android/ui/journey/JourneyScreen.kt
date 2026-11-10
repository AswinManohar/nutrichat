package app.mealsy.android.ui.journey

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
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
import androidx.compose.foundation.layout.size
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
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.mealsy.android.R
import app.mealsy.android.design.components.CoachNote
import app.mealsy.android.design.components.Eyebrow
import app.mealsy.android.design.components.SegmentedControl
import app.mealsy.android.design.components.formatThousands
import app.mealsy.android.design.components.niceAxisMax
import app.mealsy.android.design.theme.MealsyShapes
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType
import app.mealsy.android.design.theme.mealsyTween
import app.mealsy.android.ui.common.ErrorKind
import app.mealsy.android.ui.common.ErrorState
import app.mealsy.android.ui.common.LoadingState
import app.mealsy.android.ui.micronutrients.microTipRes
import app.mealsy.domain.HERO_THRESHOLD_PCT
import app.mealsy.domain.MicroRow
import kotlin.math.roundToInt

private val MACRO_CHART_HEIGHT = 130.dp
private val MICRO_NAME_COLUMN = 82.dp
private val MICRO_PCT_COLUMN = 44.dp
private val ColumnShape = RoundedCornerShape(6.dp)

/**
 * The Journey tab (`Mealsy Journey.dc.html`): macros per day, week or month
 * against the kcal goal, a short micronutrient summary linking to the full
 * screen, and a coach note. Weight and glucose are placeholders until the
 * backend tracks them.
 *
 * @param onOpenMicronutrients Opens the full Micronutrients screen.
 */
@Composable
fun JourneyScreen(
    onOpenMicronutrients: () -> Unit,
    viewModel: JourneyViewModel = hiltViewModel(),
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    JourneyScreenContent(
        state = state,
        onSelectRange = viewModel::setRange,
        onRetry = viewModel::retry,
        onOpenMicronutrients = onOpenMicronutrients,
        modifier = Modifier.fillMaxSize(),
    )
}

/** The screen without its ViewModel, so goldens render it from a hand-built [JourneyUiState]. */
@Composable
internal fun JourneyScreenContent(
    state: JourneyUiState,
    onSelectRange: (JourneyRange) -> Unit,
    onRetry: () -> Unit,
    onOpenMicronutrients: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val colors = MealsyTheme.colors
    Column(modifier = modifier.background(colors.canvas)) {
        Header(range = state.range, onSelectRange = onSelectRange)
        val body = Modifier.fillMaxWidth().weight(1f)
        when (val content = state.content) {
            JourneyContent.Loading -> LoadingState(message = stringResource(R.string.journey_loading), modifier = body)
            is JourneyContent.Error ->
                ErrorState(
                    message =
                        stringResource(
                            if (content.kind == ErrorKind.Offline) R.string.error_offline else R.string.journey_error,
                        ),
                    onRetry = onRetry,
                    modifier = body,
                )
            is JourneyContent.Loaded ->
                LoadedBody(
                    content = content,
                    range = state.range,
                    onOpenMicronutrients = onOpenMicronutrients,
                    modifier = body,
                )
        }
    }
}

/** Eyebrow, title and range control, pinned above the body with a divider under it. */
@Composable
private fun Header(
    range: JourneyRange,
    onSelectRange: (JourneyRange) -> Unit,
) {
    val colors = MealsyTheme.colors
    val labels =
        mapOf(
            JourneyRange.Week to stringResource(R.string.journey_range_week),
            JourneyRange.Month to stringResource(R.string.journey_range_month),
            JourneyRange.Quarter to stringResource(R.string.journey_range_quarter),
        )
    Column(modifier = Modifier.fillMaxWidth().background(colors.canvas)) {
        Column(
            modifier =
                Modifier
                    .windowInsetsPadding(WindowInsets.statusBars)
                    .padding(start = 20.dp, end = 20.dp, top = 24.dp, bottom = 14.dp),
        ) {
            Eyebrow(text = stringResource(R.string.journey_eyebrow))
            Spacer(modifier = Modifier.height(6.dp))
            Text(text = stringResource(R.string.journey_title), style = MealsyType.screenTitle, color = colors.ink)
            Spacer(modifier = Modifier.height(16.dp))
            SegmentedControl(
                options = JourneyRange.entries,
                selected = range,
                onSelect = onSelectRange,
                label = { labels.getValue(it) },
            )
        }
        Box(modifier = Modifier.fillMaxWidth().height(1.dp).background(colors.divider))
    }
}

@Composable
private fun LoadedBody(
    content: JourneyContent.Loaded,
    range: JourneyRange,
    onOpenMicronutrients: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val alpha by animateFloatAsState(
        targetValue = if (content.refreshing) 0.6f else 1f,
        animationSpec = mealsyTween(150),
        label = "journeyRefreshingAlpha",
    )
    val averages = macroAverages(content.days)
    val highlights = (content.micros as? JourneyMicros.Loaded)?.summary?.highlights.orEmpty()
    Column(
        modifier =
            modifier
                .verticalScroll(rememberScrollState())
                .padding(start = 20.dp, end = 20.dp, top = 18.dp, bottom = 120.dp)
                .alpha(alpha),
    ) {
        HeroPlaceholder()

        SectionHeading(stringResource(R.string.journey_weight), stringResource(R.string.journey_coming_soon))
        PlaceholderCard(stringResource(R.string.journey_weight_placeholder))

        SectionHeading(stringResource(R.string.journey_glucose), stringResource(R.string.journey_coming_soon))
        PlaceholderCard(stringResource(R.string.journey_glucose_placeholder))

        SectionHeading(
            stringResource(R.string.journey_macros),
            stringResource(
                when (range) {
                    JourneyRange.Week -> R.string.journey_macros_hint_week
                    JourneyRange.Month -> R.string.journey_macros_hint_month
                    JourneyRange.Quarter -> R.string.journey_macros_hint_quarter
                },
            ),
        )
        MacrosCard(
            columns = buildMacroColumns(range, content.days, content.today),
            averages = averages,
            kcalGoal = content.kcalGoal,
            proteinGoal = content.proteinGoal,
            range = range,
        )

        SectionHeading(stringResource(R.string.journey_micros), stringResource(R.string.journey_micros_hint))
        MicrosCard(micros = content.micros)
        Box(modifier = Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterEnd) {
            val label = stringResource(R.string.journey_micros_all)
            Text(
                text = label,
                style = MealsyType.label.copy(fontWeight = FontWeight.Medium),
                color = MealsyTheme.colors.ink,
                modifier =
                    Modifier
                        .heightIn(min = 48.dp)
                        .clickable(onClickLabel = label, onClick = onOpenMicronutrients)
                        .semantics { role = Role.Button }
                        .padding(horizontal = 4.dp, vertical = 14.dp),
            )
        }

        journeyCoach(averages, content.proteinGoal, highlights)?.let { coach ->
            Spacer(modifier = Modifier.height(10.dp))
            CoachNote(text = coachText(coach))
        }
    }
}

/**
 * Stands in for the design's weight-progress pill until weight is tracked: the
 * same 46dp pill, in `surface` with no olive fill, so it can't read as a real status.
 */
@Composable
private fun HeroPlaceholder() {
    val colors = MealsyTheme.colors
    Row(
        modifier =
            Modifier
                .fillMaxWidth()
                .heightIn(min = 46.dp)
                .clip(MealsyShapes.pill)
                .background(colors.surface)
                .border(1.dp, colors.divider, MealsyShapes.pill)
                .padding(horizontal = 18.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(
            text = stringResource(R.string.journey_hero_placeholder),
            style = MealsyType.body.copy(fontWeight = FontWeight.Medium),
            color = colors.muted,
            modifier = Modifier.weight(1f, fill = false),
        )
        Spacer(modifier = Modifier.width(8.dp))
        Text(text = stringResource(R.string.journey_coming_soon), style = MealsyType.label, color = colors.muted)
    }
}

@Composable
private fun SectionHeading(
    title: String,
    hint: String,
) {
    val colors = MealsyTheme.colors
    Row(
        modifier = Modifier.fillMaxWidth().padding(top = 28.dp, bottom = 12.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(text = title, style = MealsyType.section, color = colors.ink, modifier = Modifier.alignByBaseline())
        Spacer(modifier = Modifier.width(12.dp))
        Text(text = hint, style = MealsyType.label, color = colors.muted, maxLines = 1, modifier = Modifier.alignByBaseline())
    }
}

@Composable
private fun PlaceholderCard(text: String) {
    Surface(shape = MealsyShapes.card, color = MealsyTheme.colors.surface, modifier = Modifier.fillMaxWidth()) {
        Text(
            text = text,
            style = MealsyType.body,
            color = MealsyTheme.colors.muted,
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 18.dp),
        )
    }
}

/** Stacked protein/carbs/fat columns against the kcal goal, then the range's daily averages. */
@Composable
private fun MacrosCard(
    columns: List<MacroColumn>,
    averages: MacroAverages?,
    kcalGoal: Double?,
    proteinGoal: Double?,
    range: JourneyRange,
) {
    val colors = MealsyTheme.colors
    Surface(shape = MealsyShapes.card, color = colors.surface, modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(start = 14.dp, end = 14.dp, top = 16.dp, bottom = 14.dp)) {
            if (averages == null) {
                Text(
                    text = stringResource(R.string.journey_macros_empty),
                    style = MealsyType.body,
                    color = colors.muted,
                    modifier = Modifier.padding(horizontal = 2.dp, vertical = 4.dp),
                )
                return@Column
            }
            val gap = if (range == JourneyRange.Week) 8.dp else 14.dp
            val unit =
                stringResource(
                    when (range) {
                        JourneyRange.Week -> R.string.journey_macros_unit_week
                        JourneyRange.Month -> R.string.journey_macros_unit_month
                        JourneyRange.Quarter -> R.string.journey_macros_unit_quarter
                    },
                )
            val description = stringResource(R.string.journey_macros_chart_a11y, unit)
            MacroColumns(
                columns = columns,
                kcalGoal = kcalGoal,
                gap = gap,
                modifier = Modifier.clearAndSetSemantics { contentDescription = description },
            )
            Row(modifier = Modifier.fillMaxWidth().padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(gap)) {
                columns.forEach { col ->
                    Text(
                        text = col.label,
                        style = MealsyType.label.copy(fontSize = 11.sp),
                        color = colors.inactive,
                        textAlign = TextAlign.Center,
                        maxLines = 1,
                        modifier = Modifier.weight(1f),
                    )
                }
            }
            Box(modifier = Modifier.padding(top = 12.dp).fillMaxWidth().height(1.dp).background(colors.divider))
            MacroAverageRow(
                name = stringResource(R.string.journey_protein),
                swatch = colors.ink,
                edge = colors.ink,
                value =
                    proteinGoal?.let { stringResource(R.string.journey_avg_of, averages.proteinG, it.roundToInt()) }
                        ?: stringResource(R.string.journey_avg, averages.proteinG),
                first = true,
            )
            MacroAverageRow(
                name = stringResource(R.string.journey_carbs),
                swatch = colors.canvas,
                edge = colors.hairline,
                value = stringResource(R.string.journey_avg, averages.carbsG),
            )
            MacroAverageRow(
                name = stringResource(R.string.journey_fat),
                swatch = colors.oliveTrack,
                edge = colors.hairline,
                value = stringResource(R.string.journey_avg, averages.fatG),
            )
        }
    }
}

/**
 * Each column's height is its average kcal on an axis that always fits the
 * goal; it is split by the share of energy from protein (4 kcal/g), carbs
 * (4 kcal/g) and fat (9 kcal/g), protein at the bottom.
 */
@Composable
private fun MacroColumns(
    columns: List<MacroColumn>,
    kcalGoal: Double?,
    gap: Dp,
    modifier: Modifier = Modifier,
) {
    val colors = MealsyTheme.colors
    val maxKcal = maxOf(columns.maxOfOrNull { it.kcal } ?: 0.0, kcalGoal ?: 0.0).toFloat()
    val axisMax = niceAxisMax(maxKcal).takeIf { it > 0f } ?: 1f
    val goalFraction = kcalGoal?.let { (it.toFloat() / axisMax).coerceIn(0f, 1f) }
    BoxWithConstraints(
        modifier =
            modifier
                .fillMaxWidth()
                .height(MACRO_CHART_HEIGHT)
                .drawBehind {
                    goalFraction ?: return@drawBehind
                    val y = size.height * (1f - goalFraction)
                    drawLine(
                        color = colors.olive,
                        start = Offset(0f, y),
                        end = Offset(size.width, y),
                        strokeWidth = 1.5.dp.toPx(),
                        pathEffect = PathEffect.dashPathEffect(floatArrayOf(4.dp.toPx(), 4.dp.toPx())),
                    )
                },
    ) {
        Row(
            modifier = Modifier.fillMaxSize(),
            horizontalArrangement = Arrangement.spacedBy(gap),
            verticalAlignment = Alignment.Bottom,
        ) {
            columns.forEach { col ->
                val fraction = (col.kcal.toFloat() / axisMax).coerceIn(0f, 1f)
                Column(
                    modifier =
                        Modifier
                            .weight(1f)
                            .fillMaxHeight(fraction.coerceAtLeast(0.0001f))
                            .clip(ColumnShape),
                ) {
                    if (!col.hasData) return@Column
                    val p = col.proteinG * 4
                    val c = col.carbsG * 4
                    val f = col.fatG * 9
                    val total = p + c + f
                    // Top to bottom: fat, carbs, protein (protein sits on the baseline).
                    if (total <= 0.0) {
                        Box(modifier = Modifier.fillMaxWidth().weight(1f).background(colors.canvas))
                    } else {
                        listOf(f to colors.oliveTrack, c to colors.canvas, p to colors.ink).forEach { (kcal, color) ->
                            if (kcal > 0.0) {
                                Box(modifier = Modifier.fillMaxWidth().weight((kcal / total).toFloat()).background(color))
                            }
                        }
                    }
                }
            }
        }
        if (goalFraction != null && kcalGoal != null) {
            // offset, not bottom padding: padding would shrink the label's own
            // height to nothing when the goal sits near the top of the chart.
            val lift = maxHeight * goalFraction + 2.dp
            Text(
                text = formatThousands(kcalGoal.roundToInt()),
                style = MealsyType.tinyTag,
                color = colors.muted,
                modifier =
                    Modifier
                        .align(Alignment.BottomEnd)
                        .offset(y = -lift)
                        .background(colors.surface.copy(alpha = 0.85f))
                        .padding(horizontal = 2.dp),
            )
        }
    }
}

@Composable
private fun MacroAverageRow(
    name: String,
    swatch: Color,
    edge: Color,
    value: String,
    first: Boolean = false,
) {
    val colors = MealsyTheme.colors
    Column {
        if (!first) Box(modifier = Modifier.fillMaxWidth().height(1.dp).background(colors.divider))
        Row(
            modifier = Modifier.fillMaxWidth().heightIn(min = 36.dp).padding(top = if (first) 4.dp else 0.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Box(
                modifier =
                    Modifier
                        .size(10.dp)
                        .clip(RoundedCornerShape(3.dp))
                        .background(swatch)
                        .border(1.dp, edge, RoundedCornerShape(3.dp)),
            )
            Text(text = name, style = MealsyType.label.copy(fontSize = 13.sp), color = colors.ink, modifier = Modifier.weight(1f))
            Text(text = value, style = MealsyType.body.copy(fontWeight = FontWeight.Medium), color = colors.ink)
        }
    }
}

/** Journey's short micronutrient list as thin bars of % daily value. */
@Composable
private fun MicrosCard(micros: JourneyMicros) {
    val colors = MealsyTheme.colors
    Surface(shape = MealsyShapes.card, color = colors.surface, modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            when (micros) {
                JourneyMicros.Unavailable ->
                    Text(text = stringResource(R.string.journey_micros_unavailable), style = MealsyType.body, color = colors.muted)
                JourneyMicros.Empty ->
                    Text(text = stringResource(R.string.journey_macros_empty), style = MealsyType.body, color = colors.muted)
                is JourneyMicros.Loaded -> micros.summary.highlights.forEach { MicroBarRow(it) }
            }
        }
    }
}

@Composable
private fun MicroBarRow(row: MicroRow) {
    val colors = MealsyTheme.colors
    val n = row.nutrient
    val pct = row.pct
    val description =
        when {
            pct == null -> stringResource(R.string.micros_row_no_data_a11y, n.name)
            n.isLimit -> stringResource(R.string.micros_row_limit_a11y, n.name, pct)
            else -> stringResource(R.string.micros_row_a11y, n.name, pct)
        }
    // As the design: past half a target (or within a limit) reads as olive; a
    // target under half is hairline; a limit passed turns terracotta.
    val fill =
        when {
            pct == null -> Color.Transparent
            n.isLimit -> if (pct > 100) colors.terracotta else colors.olive
            pct < HERO_THRESHOLD_PCT -> colors.hairline
            else -> colors.olive
        }
    Row(
        modifier = Modifier.fillMaxWidth().clearAndSetSemantics { contentDescription = description },
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Column(modifier = Modifier.width(MICRO_NAME_COLUMN * LocalDensity.current.fontScale.coerceIn(1f, 2f))) {
            Text(text = n.name, style = MealsyType.label.copy(fontSize = 13.sp, lineHeight = 16.sp), color = colors.ink)
            if (n.isLimit) Text(text = stringResource(R.string.micros_limit), style = MealsyType.tinyTag, color = colors.muted)
        }
        Box(
            modifier =
                Modifier
                    .weight(1f)
                    .height(10.dp)
                    .clip(MealsyShapes.pill)
                    .background(colors.canvas),
        ) {
            val fraction = ((pct ?: 0) / 100f).coerceIn(0f, 1f)
            Box(modifier = Modifier.fillMaxHeight().fillMaxWidth(fraction).clip(MealsyShapes.pill).background(fill))
        }
        Text(
            text = pct?.let { stringResource(R.string.micros_pct, it) } ?: "—",
            style = MealsyType.label.copy(fontSize = 13.sp, fontWeight = FontWeight.Medium),
            color = colors.ink,
            textAlign = TextAlign.End,
            modifier = Modifier.width(MICRO_PCT_COLUMN),
        )
    }
}

@Composable
private fun coachText(coach: JourneyCoach): String =
    when (coach) {
        is JourneyCoach.ProteinGap ->
            stringResource(R.string.journey_coach_protein, coach.avgG, coach.goalG - coach.avgG, coach.goalG)
        is JourneyCoach.LowNutrient -> {
            val n = coach.row.nutrient
            val tip =
                microTipRes(n.key)?.let { stringResource(it) }
                    ?: stringResource(R.string.micros_tip_generic, n.name.lowercase())
            stringResource(R.string.journey_coach_low, n.name, coach.row.pct ?: 0, tip)
        }
        JourneyCoach.Steady -> stringResource(R.string.journey_coach_steady)
    }
