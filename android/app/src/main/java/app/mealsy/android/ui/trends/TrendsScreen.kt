package app.mealsy.android.ui.trends

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.mealsy.android.ui.common.ErrorState
import app.mealsy.android.ui.common.LoadingState
import app.mealsy.data.repo.CategorySlice
import app.mealsy.data.repo.DayPoint

/**
 * Trends screen: kcal bar chart + protein line (with a goal reference line)
 * over the selected [TrendsWindow], plus a per-category breakdown list.
 * Charts are hand-drawn with Compose [Canvas] — no chart library, per the
 * task brief (two simple charts don't justify the dependency).
 */
@Composable
fun TrendsScreen(viewModel: TrendsViewModel = hiltViewModel()) {
    val window by viewModel.window.collectAsStateWithLifecycle()
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()

    Column(modifier = Modifier.fillMaxSize()) {
        Text(
            text = "Trends",
            style = MaterialTheme.typography.titleLarge,
            modifier = Modifier.padding(16.dp),
        )

        SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp)) {
            TrendsWindow.entries.forEachIndexed { index, entry ->
                SegmentedButton(
                    selected = window == entry,
                    onClick = { viewModel.setWindow(entry) },
                    shape = SegmentedButtonDefaults.itemShape(index, TrendsWindow.entries.size),
                ) {
                    Text(if (entry == TrendsWindow.WEEK) "7 days" else "30 days")
                }
            }
        }

        HorizontalDivider(modifier = Modifier.padding(top = 16.dp))

        when (val state = uiState) {
            TrendsUiState.Loading -> LoadingState("Loading trends…")
            TrendsUiState.Empty -> EmptyState()
            is TrendsUiState.Error -> ErrorState(message = state.message, onRetry = viewModel::retry)
            is TrendsUiState.Loaded -> LoadedState(state)
        }
    }
}

@Composable
private fun EmptyState() {
    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Text(
            text = "Log a few meals to see trends",
            style = MaterialTheme.typography.bodyLarge,
            modifier = Modifier.padding(32.dp),
        )
    }
}

@Composable
private fun LoadedState(state: TrendsUiState.Loaded) {
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(24.dp),
    ) {
        item {
            Column {
                Text("Calories", style = MaterialTheme.typography.titleMedium)
                KcalBarChart(
                    days = state.trends.days,
                    modifier = Modifier.fillMaxWidth().height(160.dp).padding(top = 8.dp),
                )
            }
        }
        item {
            Column {
                Text("Protein", style = MaterialTheme.typography.titleMedium)
                ProteinLineChart(
                    days = state.trends.days,
                    goal = state.proteinGoal,
                    modifier = Modifier.fillMaxWidth().height(160.dp).padding(top = 8.dp),
                )
            }
        }
        item {
            Text(
                "By category",
                style = MaterialTheme.typography.titleMedium,
                modifier = Modifier.padding(top = 8.dp),
            )
        }
        items(state.categories) { category ->
            CategoryRow(category)
        }
    }
}

/** Simple bar chart of per-day kcal totals, drawn on [Canvas]. */
@Composable
private fun KcalBarChart(days: List<DayPoint>, modifier: Modifier = Modifier) {
    if (days.isEmpty()) {
        Box(modifier = modifier, contentAlignment = Alignment.Center) { Text("No data") }
        return
    }
    val maxKcal = (days.maxOf { it.kcal }).coerceAtLeast(1.0)
    val barColor = MaterialTheme.colorScheme.primary
    Canvas(modifier = modifier) {
        val barSlot = size.width / days.size
        val barWidth = barSlot * 0.6f
        days.forEachIndexed { index, day ->
            val barHeight = (day.kcal / maxKcal).toFloat() * size.height
            val left = index * barSlot + (barSlot - barWidth) / 2f
            drawRect(
                color = barColor,
                topLeft = Offset(left, size.height - barHeight),
                size = androidx.compose.ui.geometry.Size(barWidth, barHeight),
            )
        }
    }
}

/** Protein line chart with an optional dashed goal reference line, drawn on [Canvas]. */
@Composable
private fun ProteinLineChart(days: List<DayPoint>, goal: Double?, modifier: Modifier = Modifier) {
    if (days.isEmpty()) {
        Box(modifier = modifier, contentAlignment = Alignment.Center) { Text("No data") }
        return
    }
    val maxProtein = (listOfNotNull(days.maxOf { it.proteinG }, goal).maxOrNull() ?: 1.0)
        .coerceAtLeast(1.0)
    val lineColor = MaterialTheme.colorScheme.secondary
    val goalColor = MaterialTheme.colorScheme.error
    Canvas(modifier = modifier) {
        val stepX = if (days.size > 1) size.width / (days.size - 1) else 0f

        if (goal != null) {
            val goalY = size.height - (goal / maxProtein).toFloat() * size.height
            drawLine(
                color = goalColor,
                start = Offset(0f, goalY),
                end = Offset(size.width, goalY),
                strokeWidth = 2f,
                pathEffect = PathEffect.dashPathEffect(floatArrayOf(12f, 8f)),
            )
        }

        val points = days.mapIndexed { index, day ->
            val x = if (days.size > 1) index * stepX else size.width / 2f
            val y = size.height - (day.proteinG / maxProtein).toFloat() * size.height
            Offset(x, y)
        }
        for (i in 0 until points.size - 1) {
            drawLine(
                color = lineColor,
                start = points[i],
                end = points[i + 1],
                strokeWidth = 4f,
            )
        }
        points.forEach { point ->
            drawCircle(color = lineColor, radius = 5f, center = point)
        }
    }
}

/** One row of the category breakdown: meal type, avg kcal, and a bar sized to its kcal share. */
@Composable
private fun CategoryRow(category: CategorySlice, modifier: Modifier = Modifier) {
    Column(modifier = modifier.fillMaxWidth().padding(vertical = 6.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text(category.mealType.replaceFirstChar { it.uppercase() })
            Text("${category.avgKcal.toInt()} kcal avg · ${category.nMeals}x")
        }
        val barColor = MaterialTheme.colorScheme.primary
        Canvas(modifier = Modifier.fillMaxWidth().height(8.dp).padding(top = 4.dp)) {
            val fraction = (category.shareKcalPct / 100.0).toFloat().coerceIn(0f, 1f)
            drawRect(
                color = barColor,
                size = androidx.compose.ui.geometry.Size(size.width * fraction, size.height),
            )
        }
    }
}
