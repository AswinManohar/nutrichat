package app.mealsy.android.ui.settings

import androidx.compose.runtime.Composable
import app.mealsy.android.ui.AppScreenshotTestBase
import org.junit.Test

/**
 * Goldens for the Profile sub-screens' designed states, light and dark. [GoalsContent] and its siblings
 * are rendered directly with hand-built [SettingsUiState] values — no Hilt
 * graph, no network, deterministic frames — same convention as
 * `HomeScreenGoldenTest`/`OnboardingScreenGoldenTest`.
 */
class SettingsGoldenTest : AppScreenshotTestBase() {
    private val goalsModeState =
        SettingsUiState(
            goalsLoading = false,
            firstName = "Alex",
            goalFocus = "maintain",
            trackingMode = "goals",
            kcalGoal = 2200.0,
            proteinGoal = 110.0,
            fiberGoal = 30.0,
            dietaryPrefs = setOf("vegetarian", "gluten_free"),
            reminderEnabled = true,
            versionName = "1.0",
            versionCode = 1,
        )

    private val mindfulModeState =
        goalsModeState.copy(
            trackingMode = "mindful",
            dietaryPrefs = emptySet(),
            reminderEnabled = false,
        )

    private val deleteDialogState =
        goalsModeState.copy(
            deleteConfirmationText = "DEL",
        )

    private val notificationsBlockedState =
        goalsModeState.copy(
            reminderEnabled = false,
            notificationsBlocked = true,
        )

    @Composable
    private fun renderGoals(state: SettingsUiState) {
        GoalsContent(
            uiState = state,
            onBack = {},
            onStartEditingName = {},
            onSetNameDraft = {},
            onSaveName = {},
            onOpenGoalSheet = {},
            onDismissGoalSheet = {},
            onSelectGoalFocus = {},
            onKeepCurrentKcalTarget = {},
            onUseGoalDefaultKcal = {},
            onSetTrackingEnabled = {},
            onSetKcalGoal = {},
            onSetProteinGoal = {},
            onSetFiberGoal = {},
        )
    }

    @Composable
    private fun renderFood(state: SettingsUiState) {
        FoodPreferencesContent(uiState = state, onBack = {}, onTogglePref = {})
    }

    @Composable
    private fun renderReminders(state: SettingsUiState) {
        RemindersContent(
            uiState = state,
            onBack = {},
            onSetReminderEnabled = {},
            onOpenNotificationSettings = {},
        )
    }

    @Composable
    private fun renderAccount(state: SettingsUiState) {
        AccountContent(
            uiState = state,
            onBack = {},
            onOpenPrivacyPolicy = {},
            onSetDeleteConfirmationText = {},
            onDeleteAccount = {},
            isDeleteConfirmed = { false },
        )
    }

    @Test
    fun goalsMode_light() = captureMealsy("Settings_goalsMode", false) { renderGoals(goalsModeState) }

    @Test
    fun goalsMode_light_fontScale130() = captureMealsy("Settings_goalsMode", false, 1.3f) { renderGoals(goalsModeState) }

    @Test
    fun goalsMode_light_fontScale200() = captureMealsy("Settings_goalsMode", false, 2.0f) { renderGoals(goalsModeState) }

    @Test
    fun goalsMode_dark() = captureMealsy("Settings_goalsMode", true) { renderGoals(goalsModeState) }

    @Test
    fun mindfulMode_light() = captureMealsy("Settings_mindfulMode", false) { renderGoals(mindfulModeState) }

    @Test
    fun mindfulMode_dark() = captureMealsy("Settings_mindfulMode", true) { renderGoals(mindfulModeState) }

    @Test
    fun foodPreferences_light() = captureMealsy("Settings_foodPreferences", false) { renderFood(goalsModeState) }

    @Test
    fun foodPreferences_dark() = captureMealsy("Settings_foodPreferences", true) { renderFood(goalsModeState) }

    @Test
    fun reminders_light() = captureMealsy("Settings_reminders", false) { renderReminders(goalsModeState) }

    @Test
    fun reminders_dark() = captureMealsy("Settings_reminders", true) { renderReminders(goalsModeState) }

    @Test
    fun notificationsBlocked_light() = captureMealsy("Settings_notificationsBlocked", false) { renderReminders(notificationsBlockedState) }

    @Test
    fun notificationsBlocked_dark() = captureMealsy("Settings_notificationsBlocked", true) { renderReminders(notificationsBlockedState) }

    @Test
    fun account_light() = captureMealsy("Settings_account", false) { renderAccount(goalsModeState) }

    @Test
    fun account_dark() = captureMealsy("Settings_account", true) { renderAccount(goalsModeState) }

    @Test
    fun deleteDialog_light() =
        captureMealsyDialog("Settings_deleteDialog", false) {
            DeleteAccountDialog(
                confirmationText = deleteDialogState.deleteConfirmationText,
                deleting = false,
                error = null,
                confirmed = false,
                onConfirmationTextChange = {},
                onConfirm = {},
                onDismiss = {},
            )
        }

    @Test
    fun deleteDialog_dark() =
        captureMealsyDialog("Settings_deleteDialog", true) {
            DeleteAccountDialog(
                confirmationText = deleteDialogState.deleteConfirmationText,
                deleting = false,
                error = null,
                confirmed = false,
                onConfirmationTextChange = {},
                onConfirm = {},
                onDismiss = {},
            )
        }
}
