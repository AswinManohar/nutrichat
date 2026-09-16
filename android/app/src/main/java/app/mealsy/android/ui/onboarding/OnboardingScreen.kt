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
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle

/**
 * TEMPORARY STUB — this composable is being rewritten against the new
 * six-state [OnboardingViewModel] API (see [OnboardingUiState]) by a
 * separate pass right after this one. This body only exists so the module
 * compiles; it is not the intended UI. [TrackingModeStep], [NumericGoalsStep],
 * [GoalStepper] and [DietaryPrefsStep] below are untouched — they're still
 * used by [app.mealsy.android.ui.settings.SettingsScreen].
 */
@Composable
fun OnboardingScreen(
    onDone: () -> Unit,
    viewModel: OnboardingViewModel = hiltViewModel(),
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()

    LaunchedEffect(uiState.done) {
        if (uiState.done) onDone()
    }

    Column(modifier = Modifier.fillMaxSize().padding(24.dp)) {
        Text(text = "Onboarding step ${uiState.step}", style = MaterialTheme.typography.headlineSmall)
        Spacer(modifier = Modifier.height(16.dp))

        if (uiState.error) {
            Text(
                text = "Something went wrong.",
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.padding(bottom = 8.dp),
            )
            Button(onClick = viewModel::retry) { Text("Retry") }
        } else if (uiState.saving) {
            CircularProgressIndicator(modifier = Modifier.padding(8.dp))
        } else {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                OutlinedButton(onClick = viewModel::back) { Text("Back") }
                Button(onClick = viewModel::next, enabled = uiState.continueEnabled) {
                    Text(uiState.continueLabel.name)
                }
            }
        }
    }
}

/**
 * `internal` (rather than `private`) so [app.mealsy.android.ui.settings.SettingsScreen]
 * can reuse these same step composables for editing goals post-onboarding —
 * see Task 13's "Goals" section.
 */
@Composable
internal fun TrackingModeStep(selected: String, onSelect: (String) -> Unit) {
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
internal fun NumericGoalsStep(
    kcalGoal: Double,
    proteinGoal: Double,
    fiberGoal: Double,
    onKcalGoalChange: (Double) -> Unit,
    onProteinGoalChange: (Double) -> Unit,
    onFiberGoalChange: (Double) -> Unit,
) {
    Column {
        Text(text = "Daily goals", style = MaterialTheme.typography.titleMedium)
        Spacer(modifier = Modifier.height(16.dp))

        GoalStepper(
            label = "Calories (kcal)",
            value = kcalGoal,
            step = 50.0,
            onChange = onKcalGoalChange,
        )
        GoalStepper(
            label = "Protein (g)",
            value = proteinGoal,
            step = 5.0,
            onChange = onProteinGoalChange,
        )
        GoalStepper(
            label = "Fiber (g)",
            value = fiberGoal,
            step = 5.0,
            onChange = onFiberGoalChange,
        )
    }
}

@Composable
internal fun GoalStepper(label: String, value: Double, step: Double, onChange: (Double) -> Unit) {
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
internal fun DietaryPrefsStep(selected: Set<String>, onToggle: (String) -> Unit) {
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
