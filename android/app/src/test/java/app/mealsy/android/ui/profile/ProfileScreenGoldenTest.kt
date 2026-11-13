package app.mealsy.android.ui.profile

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import app.mealsy.android.ui.AppScreenshotTestBase
import app.mealsy.android.ui.settings.SettingsUiState
import org.junit.Test

/**
 * Goldens for the Profile tab, light and dark. [ProfileContent] is rendered
 * directly with a hand-built [SettingsUiState] — no Hilt graph, no network.
 */
class ProfileScreenGoldenTest : AppScreenshotTestBase() {
    private val state =
        SettingsUiState(
            goalsLoading = false,
            firstName = "Alex",
            email = "alex@example.com",
            trackingMode = "goals",
            kcalGoal = 1800.0,
            dietaryPrefs = setOf("vegetarian", "gluten_free"),
            reminderEnabled = true,
        )

    @Composable
    private fun render() {
        ProfileContent(
            uiState = state,
            careState = CareProfileUiState.Loaded(CareFixtures.typical),
            onOpenGoals = {},
            onOpenFood = {},
            onOpenReminders = {},
            onOpenAccount = {},
            onOpenCare = {},
            onSignOut = {},
            modifier = Modifier.fillMaxSize(),
        )
    }

    @Test
    fun profile_light() = captureMealsy("Profile_tab", false) { render() }

    @Test
    fun profile_dark() = captureMealsy("Profile_tab", true) { render() }
}
