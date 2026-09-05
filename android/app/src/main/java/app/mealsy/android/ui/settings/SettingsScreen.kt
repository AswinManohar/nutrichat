package app.mealsy.android.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.mealsy.android.BuildConfig
import app.mealsy.android.ui.onboarding.DietaryPrefsStep
import app.mealsy.android.ui.onboarding.NumericGoalsStep
import app.mealsy.android.ui.onboarding.TrackingModeStep

/**
 * Settings screen: goals edit, daily reminder toggle, privacy policy link,
 * app version, sign out, and the account-deletion danger zone.
 *
 * [onSignedOut] fires once [SettingsViewModel.uiState]'s `signedOut` flips
 * true (after either a plain sign-out or a successful account deletion) —
 * `AppNav`'s own [app.mealsy.data.auth.SessionManager] observer then routes
 * to login on its own, so this is only a hook for screen-local cleanup if a
 * caller needs one; the default no-op is fine since navigation happens
 * automatically.
 */
@Composable
fun SettingsScreen(
    viewModel: SettingsViewModel = hiltViewModel(),
    onSignedOut: () -> Unit = {},
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    var showDeleteDialog by remember { mutableStateOf(false) }
    val uriHandler = LocalUriHandler.current

    LaunchedEffect(uiState.signedOut) {
        if (uiState.signedOut) onSignedOut()
    }

    if (showDeleteDialog) {
        DeleteAccountDialog(
            confirmationText = uiState.deleteConfirmationText,
            deleting = uiState.deletingAccount,
            error = uiState.deleteError,
            onConfirmationTextChange = viewModel::setDeleteConfirmationText,
            onConfirm = viewModel::deleteAccount,
            onDismiss = {
                showDeleteDialog = false
                viewModel.setDeleteConfirmationText("")
            },
        )
    }

    LazyColumn(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        item {
            Text(text = "Settings", style = MaterialTheme.typography.headlineSmall)
            Spacer(modifier = Modifier.height(24.dp))
        }

        item { GoalsSection(uiState = uiState, viewModel = viewModel) }

        item {
            HorizontalDivider(modifier = Modifier.padding(vertical = 16.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text("Daily reminder", style = MaterialTheme.typography.titleMedium)
                    Text(
                        "Get a nudge to log your meals",
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
                Switch(checked = uiState.reminderEnabled, onCheckedChange = viewModel::setReminderEnabled)
            }
        }

        item {
            HorizontalDivider(modifier = Modifier.padding(vertical = 16.dp))
            TextButton(onClick = { uriHandler.openUri(BuildConfig.PRIVACY_POLICY_URL) }) {
                Text("Privacy policy")
            }
        }

        item {
            HorizontalDivider(modifier = Modifier.padding(vertical = 16.dp))
            Column {
                Text(
                    "Version ${uiState.versionName} (${uiState.versionCode})",
                    style = MaterialTheme.typography.bodyMedium,
                )
                if (uiState.updateAvailable) {
                    Text(
                        "A newer version is available.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.primary,
                    )
                }
            }
        }

        item {
            HorizontalDivider(modifier = Modifier.padding(vertical = 16.dp))
            OutlinedButton(onClick = viewModel::signOut, modifier = Modifier.fillMaxWidth()) {
                Text("Sign out")
            }
        }

        item {
            Spacer(modifier = Modifier.height(24.dp))
            Text(
                "Danger zone",
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.error,
            )
            Spacer(modifier = Modifier.height(8.dp))
            Button(
                onClick = { showDeleteDialog = true },
                colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text("Delete account")
            }
        }
    }
}

@Composable
private fun GoalsSection(uiState: SettingsUiState, viewModel: SettingsViewModel) {
    Column {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("Goals", style = MaterialTheme.typography.titleMedium)
            if (!uiState.goalsLoading && !uiState.editingGoals) {
                TextButton(onClick = viewModel::startEditingGoals) { Text("Edit") }
            }
        }

        when {
            uiState.goalsLoading -> CircularProgressIndicator(modifier = Modifier.padding(top = 16.dp))
            uiState.editingGoals -> {
                Spacer(modifier = Modifier.height(8.dp))
                TrackingModeStep(uiState.trackingMode, viewModel::setTrackingMode)
                Spacer(modifier = Modifier.height(16.dp))
                NumericGoalsStep(
                    kcalGoal = uiState.kcalGoal,
                    proteinGoal = uiState.proteinGoal,
                    fiberGoal = uiState.fiberGoal,
                    onKcalGoalChange = viewModel::setKcalGoal,
                    onProteinGoalChange = viewModel::setProteinGoal,
                    onFiberGoalChange = viewModel::setFiberGoal,
                )
                Spacer(modifier = Modifier.height(16.dp))
                DietaryPrefsStep(uiState.dietaryPrefs, viewModel::toggleDietaryPref)

                if (uiState.goalsError != null) {
                    Text(
                        text = uiState.goalsError.orEmpty(),
                        color = MaterialTheme.colorScheme.error,
                        modifier = Modifier.padding(top = 8.dp),
                    )
                }

                Row(
                    modifier = Modifier.fillMaxWidth().padding(top = 16.dp),
                    horizontalArrangement = Arrangement.End,
                ) {
                    TextButton(onClick = viewModel::cancelEditingGoals, enabled = !uiState.savingGoals) {
                        Text("Cancel")
                    }
                    Spacer(modifier = Modifier.width(8.dp))
                    if (uiState.savingGoals) {
                        CircularProgressIndicator(modifier = Modifier.padding(8.dp))
                    } else {
                        Button(onClick = viewModel::saveGoals) { Text("Save") }
                    }
                }
            }
            else -> {
                Spacer(modifier = Modifier.height(8.dp))
                Text("Calories: ${uiState.kcalGoal.toInt()} kcal")
                Text("Protein: ${uiState.proteinGoal.toInt()} g")
                Text("Fiber: ${uiState.fiberGoal.toInt()} g")
            }
        }
    }
}

@Composable
private fun DeleteAccountDialog(
    confirmationText: String,
    deleting: Boolean,
    error: String?,
    onConfirmationTextChange: (String) -> Unit,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = { if (!deleting) onDismiss() },
        title = { Text("Delete account") },
        text = {
            Column {
                Text(
                    "This permanently deletes your account and all logged meals, " +
                        "goals, and saved meals. This cannot be undone.",
                )
                Spacer(modifier = Modifier.height(16.dp))
                Text("Type DELETE to confirm.")
                Spacer(modifier = Modifier.height(8.dp))
                OutlinedTextField(
                    value = confirmationText,
                    onValueChange = onConfirmationTextChange,
                    singleLine = true,
                    enabled = !deleting,
                )
                if (error != null) {
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(text = error, color = MaterialTheme.colorScheme.error)
                }
            }
        },
        confirmButton = {
            Button(
                onClick = onConfirm,
                enabled = isDeleteConfirmed(confirmationText) && !deleting,
                colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error),
            ) {
                if (deleting) {
                    CircularProgressIndicator(modifier = Modifier.height(20.dp))
                } else {
                    Text("Delete")
                }
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss, enabled = !deleting) { Text("Cancel") }
        },
    )
}
