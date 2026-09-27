package app.mealsy.android.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.asPaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.mealsy.android.BuildConfig
import app.mealsy.android.R
import app.mealsy.android.design.components.CircleIconButton
import app.mealsy.android.design.components.Eyebrow
import app.mealsy.android.design.components.FilterChipPill
import app.mealsy.android.design.components.InkToast
import app.mealsy.android.design.components.InsetDivider
import app.mealsy.android.design.components.ListContainer
import app.mealsy.android.design.components.ListRow
import app.mealsy.android.design.components.MealsyButton
import app.mealsy.android.design.components.MealsyButtonStyle
import app.mealsy.android.design.components.MealsyDialog
import app.mealsy.android.design.components.MealsyToggle
import app.mealsy.android.design.components.PastelIconCircle
import app.mealsy.android.design.components.PillInput
import app.mealsy.android.design.components.SelectableCard
import app.mealsy.android.design.components.Stepper
import app.mealsy.android.design.components.formatThousands
import app.mealsy.android.design.icons.MealsyIcons
import app.mealsy.android.design.theme.MealsyTheme
import app.mealsy.android.design.theme.MealsyType
import app.mealsy.android.ui.onboarding.DietaryPref
import app.mealsy.android.ui.onboarding.GOAL_CARD_SPECS
import app.mealsy.android.ui.onboarding.OnboardingGoal
import app.mealsy.android.ui.onboarding.PREF_LABELS
import kotlinx.coroutines.delay

/**
 * Settings screen: profile (name, goal focus), always-live daily targets,
 * dietary preferences, the daily reminder toggle, privacy policy link, app
 * version, sign out, and the account-deletion danger zone.
 *
 * Unlike the old modal "editing goals" flow, every control here is inline
 * and saves on its own — see [SettingsViewModel] for the per-field
 * (debounced) save behavior.
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
    onBack: () -> Unit = {},
    viewModel: SettingsViewModel = hiltViewModel(),
    onSignedOut: () -> Unit = {},
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val uriHandler = LocalUriHandler.current

    LaunchedEffect(uiState.signedOut) {
        if (uiState.signedOut) onSignedOut()
    }

    SettingsContent(
        uiState = uiState,
        onBack = onBack,
        onStartEditingName = viewModel::startEditingName,
        onSetNameDraft = viewModel::setNameDraft,
        onSaveName = viewModel::saveName,
        onOpenGoalSheet = viewModel::openGoalSheet,
        onDismissGoalSheet = viewModel::dismissGoalSheet,
        onSelectGoalFocus = viewModel::selectGoalFocus,
        onKeepCurrentKcalTarget = viewModel::keepCurrentKcalTarget,
        onUseGoalDefaultKcal = viewModel::useGoalDefaultKcal,
        onSetTrackingEnabled = viewModel::setTrackingEnabled,
        onSetKcalGoal = viewModel::setKcalGoal,
        onSetProteinGoal = viewModel::setProteinGoal,
        onSetFiberGoal = viewModel::setFiberGoal,
        onToggleDietaryPref = viewModel::toggleDietaryPref,
        onSetReminderEnabled = viewModel::setReminderEnabled,
        onOpenPrivacyPolicy = { uriHandler.openUri(BuildConfig.PRIVACY_POLICY_URL) },
        onSignOut = viewModel::signOut,
        onSetDeleteConfirmationText = viewModel::setDeleteConfirmationText,
        onDeleteAccount = viewModel::deleteAccount,
        isDeleteConfirmed = viewModel::isDeleteConfirmedNow,
    )
}

/**
 * Stateless render of the whole screen — [SettingsScreen] is the Hilt/state
 * entry point above; this is what [app.mealsy.android.ui.settings.SettingsGoldenTest]
 * exercises directly with hand-built [SettingsUiState] values, same
 * convention as `HomeContent`/`OnboardingContent`.
 */
@Composable
fun SettingsContent(
    uiState: SettingsUiState,
    onBack: () -> Unit,
    onStartEditingName: () -> Unit,
    onSetNameDraft: (String) -> Unit,
    onSaveName: () -> Unit,
    onOpenGoalSheet: () -> Unit,
    onDismissGoalSheet: () -> Unit,
    onSelectGoalFocus: (OnboardingGoal) -> Unit,
    onKeepCurrentKcalTarget: () -> Unit,
    onUseGoalDefaultKcal: () -> Unit,
    onSetTrackingEnabled: (Boolean) -> Unit,
    onSetKcalGoal: (Double) -> Unit,
    onSetProteinGoal: (Double) -> Unit,
    onSetFiberGoal: (Double) -> Unit,
    onToggleDietaryPref: (String) -> Unit,
    onSetReminderEnabled: (Boolean) -> Unit,
    onOpenPrivacyPolicy: () -> Unit,
    onSignOut: () -> Unit,
    onSetDeleteConfirmationText: (String) -> Unit,
    onDeleteAccount: () -> Unit,
    isDeleteConfirmed: () -> Boolean,
    modifier: Modifier = Modifier,
) {
    var showDeleteDialog by remember { mutableStateOf(false) }
    var showSavedToast by remember { mutableStateOf(false) }
    val statusBarTop = WindowInsets.statusBars.asPaddingValues().calculateTopPadding()

    LaunchedEffect(uiState.savedTick) {
        if (uiState.savedTick > 0) {
            showSavedToast = true
            delay(1500)
            showSavedToast = false
        }
    }

    if (showDeleteDialog) {
        DeleteAccountDialog(
            confirmationText = uiState.deleteConfirmationText,
            deleting = uiState.deletingAccount,
            error = uiState.deleteError,
            confirmed = isDeleteConfirmed(),
            onConfirmationTextChange = onSetDeleteConfirmationText,
            onConfirm = onDeleteAccount,
            onDismiss = {
                showDeleteDialog = false
                onSetDeleteConfirmationText("")
            },
        )
    }

    if (uiState.showGoalSheet) {
        GoalPickerDialog(
            selectedKey = uiState.goalFocus,
            onSelect = onSelectGoalFocus,
            onDismiss = onDismissGoalSheet,
        )
    }

    uiState.kcalPromptGoal?.let { goal ->
        MealsyDialog(
            onDismissRequest = onKeepCurrentKcalTarget,
            title = stringResource(R.string.settings_kcal_prompt_title),
            body =
                stringResource(
                    R.string.settings_kcal_prompt_body,
                    goalTitleFor(goal),
                ),
            buttons = {
                MealsyButton(
                    text = stringResource(R.string.settings_kcal_prompt_use_default, "%,d".format(goal.defaultKcal)),
                    onClick = onUseGoalDefaultKcal,
                    modifier = Modifier.fillMaxWidth(),
                    style = MealsyButtonStyle.Primary,
                )
                MealsyButton(
                    text = stringResource(R.string.settings_kcal_prompt_keep),
                    onClick = onKeepCurrentKcalTarget,
                    modifier = Modifier.fillMaxWidth(),
                    style = MealsyButtonStyle.Secondary,
                )
            },
        )
    }

    Box(modifier = modifier.fillMaxSize()) {
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding =
                PaddingValues(
                    top = statusBarTop + 24.dp,
                    start = 20.dp,
                    end = 20.dp,
                    bottom = 120.dp,
                ),
        ) {
            item { HeaderRow(onBack = onBack) }
            item { Spacer(modifier = Modifier.height(20.dp)) }

            item {
                ProfileSection(
                    uiState = uiState,
                    onStartEditingName = onStartEditingName,
                    onSetNameDraft = onSetNameDraft,
                    onSaveName = onSaveName,
                    onOpenGoalSheet = onOpenGoalSheet,
                )
            }
            item { Spacer(modifier = Modifier.height(24.dp)) }

            item {
                TargetsSection(
                    uiState = uiState,
                    onSetTrackingEnabled = onSetTrackingEnabled,
                    onSetKcalGoal = onSetKcalGoal,
                    onSetProteinGoal = onSetProteinGoal,
                    onSetFiberGoal = onSetFiberGoal,
                )
            }
            item { Spacer(modifier = Modifier.height(24.dp)) }

            item { PreferencesSection(uiState = uiState, onTogglePref = onToggleDietaryPref) }
            item { Spacer(modifier = Modifier.height(24.dp)) }

            item {
                RemindersSection(uiState = uiState, onSetReminderEnabled = onSetReminderEnabled)
            }
            item { Spacer(modifier = Modifier.height(24.dp)) }

            item {
                AboutSection(uiState = uiState, onOpenPrivacyPolicy = onOpenPrivacyPolicy)
            }
            item { Spacer(modifier = Modifier.height(24.dp)) }

            item {
                Eyebrow(text = stringResource(R.string.settings_section_account))
                Spacer(modifier = Modifier.height(10.dp))
                MealsyButton(
                    text = stringResource(R.string.settings_sign_out),
                    onClick = onSignOut,
                    modifier = Modifier.fillMaxWidth(),
                    style = MealsyButtonStyle.Secondary,
                )
            }
            item { Spacer(modifier = Modifier.height(28.dp)) }

            item {
                Eyebrow(text = stringResource(R.string.settings_danger_zone))
                Spacer(modifier = Modifier.height(10.dp))
                MealsyButton(
                    text = stringResource(R.string.settings_delete_account),
                    onClick = { showDeleteDialog = true },
                    modifier = Modifier.fillMaxWidth(),
                    style = MealsyButtonStyle.DestructiveOutline,
                )
            }
        }

        InkToast(
            text = stringResource(R.string.settings_saved_toast),
            visible = showSavedToast,
            modifier =
                Modifier
                    .align(Alignment.BottomCenter)
                    .padding(bottom = 32.dp),
        )
    }
}

@Composable
private fun HeaderRow(onBack: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        CircleIconButton(
            icon = MealsyIcons.ChevronLeft,
            contentDescription = stringResource(R.string.settings_back),
            onClick = onBack,
            size = 38.dp,
        )
        Eyebrow(text = stringResource(R.string.settings_eyebrow))
        Spacer(modifier = Modifier.width(38.dp))
    }
}

@Composable
private fun goalTitleFor(goal: OnboardingGoal): String {
    val spec = GOAL_CARD_SPECS.first { it.goal == goal }
    return stringResource(spec.titleRes)
}

// --- Profile -----------------------------------------------------------

@Composable
private fun ProfileSection(
    uiState: SettingsUiState,
    onStartEditingName: () -> Unit,
    onSetNameDraft: (String) -> Unit,
    onSaveName: () -> Unit,
    onOpenGoalSheet: () -> Unit,
) {
    Column {
        Eyebrow(text = stringResource(R.string.settings_section_profile))
        Spacer(modifier = Modifier.height(10.dp))
        ListContainer {
            if (uiState.editingName) {
                Row(
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    PillInput(
                        value = uiState.nameDraft,
                        onValueChange = onSetNameDraft,
                        placeholder = stringResource(R.string.settings_name_placeholder),
                        modifier = Modifier.weight(1f),
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                    MealsyButton(
                        text = stringResource(R.string.settings_save),
                        onClick = onSaveName,
                        style = MealsyButtonStyle.Primary,
                    )
                }
            } else {
                ListRow(
                    label = stringResource(R.string.settings_name),
                    onClick = onStartEditingName,
                    trailingText = uiState.firstName.ifBlank { null },
                )
            }
            InsetDivider()
            ListRow(
                label = stringResource(R.string.settings_goal),
                onClick = onOpenGoalSheet,
                trailingText = goalFocusLabel(uiState.goalFocus),
            )
        }
    }
}

@Composable
private fun goalFocusLabel(key: String): String {
    val spec = GOAL_CARD_SPECS.find { it.goal.key == key } ?: return ""
    return stringResource(spec.titleRes)
}

@Composable
private fun GoalPickerDialog(
    selectedKey: String,
    onSelect: (OnboardingGoal) -> Unit,
    onDismiss: () -> Unit,
) {
    MealsyDialog(
        onDismissRequest = onDismiss,
        title = stringResource(R.string.settings_goal_sheet_title),
        content = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                GOAL_CARD_SPECS.forEach { spec ->
                    val title = stringResource(spec.titleRes)
                    SelectableCard(
                        title = title,
                        subtitle = stringResource(spec.subtitleRes),
                        selected = spec.goal.key == selectedKey,
                        onClick = { onSelect(spec.goal) },
                        leading = { PastelIconCircle(initial = title.first(), tone = spec.tone) },
                    )
                }
            }
        },
        buttons = {
            MealsyButton(
                text = stringResource(R.string.settings_cancel),
                onClick = onDismiss,
                modifier = Modifier.fillMaxWidth(),
                style = MealsyButtonStyle.Secondary,
            )
        },
    )
}

// --- Targets -------------------------------------------------------------

@Composable
private fun TargetsSection(
    uiState: SettingsUiState,
    onSetTrackingEnabled: (Boolean) -> Unit,
    onSetKcalGoal: (Double) -> Unit,
    onSetProteinGoal: (Double) -> Unit,
    onSetFiberGoal: (Double) -> Unit,
) {
    Column {
        Eyebrow(text = stringResource(R.string.settings_section_targets))
        Spacer(modifier = Modifier.height(10.dp))
        ListContainer {
            Row(
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 14.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(
                    text = stringResource(R.string.settings_track_targets),
                    style = MealsyType.body,
                    color = MealsyTheme.colors.ink,
                )
                MealsyToggle(
                    checked = uiState.trackingMode == "goals",
                    onCheckedChange = onSetTrackingEnabled,
                )
            }

            if (uiState.trackingMode == "goals") {
                InsetDivider()
                TargetStepperRow(
                    label = stringResource(R.string.settings_calories),
                    value = uiState.kcalGoal.toInt(),
                    step = 50,
                    min = 1000,
                    valueLabel = { "${formatThousands(it)} kcal" },
                    onValueChange = { onSetKcalGoal(it.toDouble()) },
                )
                InsetDivider()
                TargetStepperRow(
                    label = stringResource(R.string.settings_protein),
                    value = uiState.proteinGoal.toInt(),
                    step = 5,
                    min = 20,
                    valueLabel = { "$it g" },
                    onValueChange = { onSetProteinGoal(it.toDouble()) },
                )
                InsetDivider()
                TargetStepperRow(
                    label = stringResource(R.string.settings_fiber),
                    value = uiState.fiberGoal.toInt(),
                    step = 1,
                    min = 5,
                    valueLabel = { "$it g" },
                    onValueChange = { onSetFiberGoal(it.toDouble()) },
                )
            }
        }
    }
}

@Composable
private fun TargetStepperRow(
    label: String,
    value: Int,
    step: Int,
    min: Int,
    valueLabel: (Int) -> String,
    onValueChange: (Int) -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(
            text = label,
            style = MealsyType.body,
            color = MealsyTheme.colors.ink,
        )
        Stepper(
            value = value,
            onValueChange = onValueChange,
            step = step,
            min = min,
            valueLabel = valueLabel,
        )
    }
}

// --- Preferences -----------------------------------------------------------

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun PreferencesSection(
    uiState: SettingsUiState,
    onTogglePref: (String) -> Unit,
) {
    Column {
        Eyebrow(text = stringResource(R.string.settings_section_preferences))
        Spacer(modifier = Modifier.height(10.dp))
        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            // 12dp so the 48dp touch targets of adjacent rows don't overlap
            // (#48 item 6).
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            DietaryPref.entries.forEach { pref ->
                FilterChipPill(
                    text = stringResource(PREF_LABELS.getValue(pref)),
                    selected = pref.key in uiState.dietaryPrefs,
                    onClick = { onTogglePref(pref.key) },
                )
            }
        }
    }
}

// --- Reminders ---------------------------------------------------------------

@Composable
private fun RemindersSection(
    uiState: SettingsUiState,
    onSetReminderEnabled: (Boolean) -> Unit,
) {
    Column {
        Eyebrow(text = stringResource(R.string.settings_section_reminders))
        Spacer(modifier = Modifier.height(10.dp))
        ListContainer {
            Row(
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 14.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(
                    text = stringResource(R.string.settings_daily_summary),
                    style = MealsyType.body,
                    color = MealsyTheme.colors.ink,
                )
                MealsyToggle(
                    checked = uiState.reminderEnabled,
                    onCheckedChange = onSetReminderEnabled,
                )
            }
        }
    }
}

// --- About -----------------------------------------------------------------

@Composable
private fun AboutSection(
    uiState: SettingsUiState,
    onOpenPrivacyPolicy: () -> Unit,
) {
    Column {
        Eyebrow(text = stringResource(R.string.settings_section_about))
        Spacer(modifier = Modifier.height(10.dp))
        ListContainer {
            ListRow(
                label = stringResource(R.string.settings_privacy_policy),
                onClick = onOpenPrivacyPolicy,
            )
            InsetDivider()
            Column(modifier = Modifier.fillMaxWidth()) {
                ListRow(
                    label = stringResource(R.string.settings_version),
                    onClick = null,
                    trailingText = "${uiState.versionName} (${uiState.versionCode})",
                    showChevron = false,
                )
                if (uiState.updateAvailable) {
                    Text(
                        text = stringResource(R.string.settings_update_available),
                        style = MealsyType.label,
                        color = MealsyTheme.colors.muted,
                        modifier = Modifier.padding(start = 16.dp, end = 16.dp, bottom = 14.dp),
                    )
                }
            }
        }
    }
}

// --- Danger zone -----------------------------------------------------------

@Composable
internal fun DeleteAccountDialog(
    confirmationText: String,
    deleting: Boolean,
    error: String?,
    confirmed: Boolean,
    onConfirmationTextChange: (String) -> Unit,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    MealsyDialog(
        onDismissRequest = { if (!deleting) onDismiss() },
        title = stringResource(R.string.settings_delete_account),
        body = stringResource(R.string.settings_delete_dialog_body),
        content = {
            Column {
                PillInput(
                    value = confirmationText,
                    onValueChange = onConfirmationTextChange,
                    placeholder = stringResource(R.string.settings_delete_confirm_placeholder),
                    enabled = !deleting,
                )
                if (error != null) {
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(
                        text = error,
                        style = MealsyType.label,
                        color = MealsyTheme.colors.terracotta,
                    )
                }
            }
        },
        buttons = {
            MealsyButton(
                text = stringResource(R.string.settings_delete_cancel),
                onClick = onDismiss,
                enabled = !deleting,
                modifier = Modifier.fillMaxWidth(),
                style = MealsyButtonStyle.Secondary,
            )
            MealsyButton(
                text = stringResource(R.string.settings_delete_account),
                onClick = onConfirm,
                enabled = confirmed && !deleting,
                modifier = Modifier.fillMaxWidth(),
                style = MealsyButtonStyle.Destructive,
            )
        },
    )
}
