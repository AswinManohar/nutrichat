package app.mealsy.android.ui

import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import app.mealsy.android.ui.gate.UpdateRequiredContent
import app.mealsy.android.ui.login.LoginContent
import app.mealsy.android.ui.login.LoginUiState
import org.junit.Test

/**
 * Goldens for the login screen and the update-required gate, light and
 * dark. Both are rendered via their stateless content composables — no
 * Hilt, no [app.mealsy.android.ui.login.LoginViewModel] construction — so
 * the frames are deterministic (empty email field, no in-flight state).
 */
class AuthGoldenTest : AppScreenshotTestBase() {
    @Composable
    private fun renderLogin(uiState: LoginUiState) {
        LoginContent(
            uiState = uiState,
            email = "",
            onEmailChange = {},
            onSubmitEmail = {},
            onSignInWithGoogle = {},
            modifier = Modifier.fillMaxSize(),
        )
    }

    @Test
    fun login_light() = captureMealsy("Login", false) { renderLogin(LoginUiState.Idle) }

    @Test
    fun login_dark() = captureMealsy("Login", true) { renderLogin(LoginUiState.Idle) }

    @Test
    fun login_light_fontScale200() = captureMealsy("Login", false, 2.0f) { renderLogin(LoginUiState.Idle) }

    @Composable
    private fun renderUpdateRequired() {
        UpdateRequiredContent(onUpdate = {}, modifier = Modifier.fillMaxSize())
    }

    @Test
    fun updateRequired_light() = captureMealsy("UpdateRequired", false) { renderUpdateRequired() }

    @Test
    fun updateRequired_dark() = captureMealsy("UpdateRequired", true) { renderUpdateRequired() }
}
