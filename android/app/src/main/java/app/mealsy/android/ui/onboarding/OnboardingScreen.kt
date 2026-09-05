package app.mealsy.android.ui.onboarding

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.wrapContentWidth
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle

private const val PAGE_COUNT = 3

/**
 * 3-step goal-setup pager: tracking mode -> numeric goals -> dietary prefs.
 * "Skip for now" is always available and posts backend-required defaults
 * ([OnboardingViewModel.skip]) so a user can reach chat immediately.
 */
@Composable
fun OnboardingScreen(
    onDone: () -> Unit,
    viewModel: OnboardingViewModel = hiltViewModel(),
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val pagerState = rememberPagerState(pageCount = { PAGE_COUNT })

    LaunchedEffect(uiState.done) {
        if (uiState.done) onDone()
    }

    LaunchedEffect(uiState.step) {
        if (pagerState.currentPage != uiState.step) {
            pagerState.animateScrollToPage(uiState.step)
        }
    }

    Column(modifier = Modifier.fillMaxSize().padding(24.dp)) {
        Text(text = "Set up your goals", style = MaterialTheme.typography.headlineSmall)
        Spacer(modifier = Modifier.height(16.dp))

        HorizontalPager(
            state = pagerState,
            modifier = Modifier.weight(1f),
            userScrollEnabled = false,
        ) { page ->
            when (page) {
                0 -> TrackingModeStep(uiState.trackingMode, viewModel::setTrackingMode)
                1 -> NumericGoalsStep(uiState, viewModel)
                else -> DietaryPrefsStep(uiState.dietaryPrefs, viewModel::toggleDietaryPref)
            }
        }

        if (uiState.error != null) {
            Text(
                text = uiState.error.orEmpty(),
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.padding(bottom = 8.dp),
            )
        }

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            if (uiState.step > 0) {
                OutlinedButton(onClick = viewModel::prevStep, enabled = !uiState.saving) {
                    Text("Back")
                }
            } else {
                Spacer(modifier = Modifier.wrapContentWidth())
            }

            if (uiState.step < PAGE_COUNT - 1) {
                Button(onClick = viewModel::nextStep, enabled = !uiState.saving) {
                    Text("Next")
                }
            } else if (uiState.saving) {
                CircularProgressIndicator(modifier = Modifier.padding(8.dp))
            } else {
                Button(onClick = viewModel::save) {
                    Text("Save")
                }
            }
        }

        TextButton(
            onClick = viewModel::skip,
            enabled = !uiState.saving,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text("Skip for now")
        }
    }
}

@Composable
private fun TrackingModeStep(selected: String, onSelect: (String) -> Unit) {
    Column {
        Text(text = "How do you want to track?", style = MaterialTheme.typography.titleMedium)
        Spacer(modifier = Modifier.height(16.dp))

        TrackingModeOption(
            label = "Goals — track calories, protein, fiber",
            value = "goals",
            selected = selected == "goals",
            onSelect = onSelect,
        )
        TrackingModeOption(
            label = "Mindful — log meals without numeric targets",
            value = "mindful",
            selected = selected == "mindful",
            onSelect = onSelect,
        )
    }
}

@Composable
private fun TrackingModeOption(
    label: String,
    value: String,
    selected: Boolean,
    onSelect: (String) -> Unit,
) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
    ) {
        RadioButton(selected = selected, onClick = { onSelect(value) })
        Spacer(modifier = Modifier.width(8.dp))
        Text(text = label)
    }
}

@Composable
private fun NumericGoalsStep(uiState: OnboardingUiState, viewModel: OnboardingViewModel) {
    Column {
        Text(text = "Daily goals", style = MaterialTheme.typography.titleMedium)
        Spacer(modifier = Modifier.height(16.dp))

        GoalStepper(
            label = "Calories (kcal)",
            value = uiState.kcalGoal,
            step = 50.0,
            onChange = viewModel::setKcalGoal,
        )
        GoalStepper(
            label = "Protein (g)",
            value = uiState.proteinGoal,
            step = 5.0,
            onChange = viewModel::setProteinGoal,
        )
        GoalStepper(
            label = "Fiber (g)",
            value = uiState.fiberGoal,
            step = 5.0,
            onChange = viewModel::setFiberGoal,
        )
    }
}

@Composable
private fun GoalStepper(label: String, value: Double, step: Double, onChange: (Double) -> Unit) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(text = label, modifier = Modifier.weight(1f))
        OutlinedButton(onClick = { onChange((value - step).coerceAtLeast(0.0)) }) { Text("-") }
        Text(
            text = value.toInt().toString(),
            modifier = Modifier.padding(horizontal = 12.dp),
            style = MaterialTheme.typography.titleMedium,
        )
        OutlinedButton(onClick = { onChange(value + step) }) { Text("+") }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun DietaryPrefsStep(selected: Set<String>, onToggle: (String) -> Unit) {
    Column {
        Text(text = "Dietary preferences", style = MaterialTheme.typography.titleMedium)
        Spacer(modifier = Modifier.height(16.dp))

        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            DIETARY_PREF_OPTIONS.forEach { pref ->
                FilterChip(
                    selected = pref in selected,
                    onClick = { onToggle(pref) },
                    label = { Text(pref.replace('_', ' ')) },
                    colors = FilterChipDefaults.filterChipColors(),
                )
            }
        }
    }
}
