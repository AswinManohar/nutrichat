package app.mealsy.android.ui.settings

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import app.mealsy.android.ui.AppScreenshotTestBase
import org.junit.Test

/**
 * Goldens for Settings' designed states, light and dark. [SettingsContent]
 * is rendered directly with hand-built [SettingsUiState] values — no Hilt
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
    private fun render(state: SettingsUiState) {
        SettingsContent(
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
            onToggleDietaryPref = {},
            onSetReminderEnabled = {},
            onOpenNotificationSettings = {},
            onOpenPrivacyPolicy = {},
            onSignOut = {},
            onSetDeleteConfirmationText = {},
            onDeleteAccount = {},
            isDeleteConfirmed = { false },
            modifier = Modifier.fillMaxSize(),
        )
    }

    @Test
    fun goalsMode_light() = captureMealsy("Settings_goalsMode", false) { render(goalsModeState) }

    @Test
    fun goalsMode_light_fontScale130() = captureMealsy("Settings_goalsMode", false, 1.3f) { render(goalsModeState) }

    @Test
    fun goalsMode_light_fontScale200() = captureMealsy("Settings_goalsMode", false, 2.0f) { render(goalsModeState) }

    @Test
    fun goalsMode_dark() = captureMealsy("Settings_goalsMode", true) { render(goalsModeState) }

    @Test
    fun mindfulMode_light() = captureMealsy("Settings_mindfulMode", false) { render(mindfulModeState) }

    @Test
    fun mindfulMode_dark() = captureMealsy("Settings_mindfulMode", true) { render(mindfulModeState) }

    @Test
    fun notificationsBlocked_light() = captureMealsy("Settings_notificationsBlocked", false) { render(notificationsBlockedState) }

    @Test
    fun notificationsBlocked_dark() = captureMealsy("Settings_notificationsBlocked", true) { render(notificationsBlockedState) }

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
