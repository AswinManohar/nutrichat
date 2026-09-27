package app.mealsy.android.ui.login

import android.app.Activity
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.mealsy.data.auth.SessionManager
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

/**
 * Login-specific error kinds. Login's failures are validation/auth outcomes,
 * not the generic "couldn't load a screen" shape covered by
 * `app.mealsy.android.ui.common.ErrorKind` — so this screen defines its own
 * sealed kind rather than reusing that one. [LoginScreen] resolves each kind
 * to its user-facing string via `stringResource`.
 */
sealed interface LoginErrorKind {
    /** The entered address failed [isValidEmail]'s format check. */
    data object InvalidEmail : LoginErrorKind

    /** [SessionManager.signInWithMagicLink] threw. */
    data object MagicLinkFailed : LoginErrorKind

    /** [SessionManager.signInWithGoogle] threw. */
    data object GoogleSignInFailed : LoginErrorKind
}

/** UI state for the login screen. */
sealed interface LoginUiState {
    data object Idle : LoginUiState

    data object AwaitingEmail : LoginUiState

    data class Error(val kind: LoginErrorKind) : LoginUiState
}

private val EMAIL_REGEX = Regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$")

/** Returns true when `email` is a plausible address to send a magic link to. */
fun isValidEmail(email: String): Boolean = EMAIL_REGEX.matches(email.trim())

@HiltViewModel
class LoginViewModel
    @Inject
    constructor(
        private val sessionManager: SessionManager,
    ) : ViewModel() {
        private val _uiState = MutableStateFlow<LoginUiState>(LoginUiState.Idle)
        val uiState: StateFlow<LoginUiState> = _uiState.asStateFlow()

        /** Validates `email` and, if valid, requests a magic link via [SessionManager]. */
        fun submitEmail(email: String) {
            if (!isValidEmail(email)) {
                _uiState.value = LoginUiState.Error(LoginErrorKind.InvalidEmail)
                return
            }
            viewModelScope.launch {
                try {
                    sessionManager.signInWithMagicLink(email.trim())
                    _uiState.value = LoginUiState.AwaitingEmail
                } catch (exc: CancellationException) {
                    throw exc
                } catch (exc: Exception) {
                    _uiState.value = LoginUiState.Error(LoginErrorKind.MagicLinkFailed)
                }
            }
        }

        /**
         * Returns from [LoginUiState.AwaitingEmail] to the email-entry step.
         * Wired to system Back (#29 — every in-screen multi-step flow should
         * step back rather than exit) so a user who sent themselves a magic
         * link can correct the address or pick Google sign-in instead,
         * without leaving the screen.
         */
        fun backToEmail() {
            if (_uiState.value == LoginUiState.AwaitingEmail) {
                _uiState.value = LoginUiState.Idle
            }
        }

        /** Starts the Google OAuth sign-in flow via [SessionManager]. */
        fun signInWithGoogle(activity: Activity) {
            viewModelScope.launch {
                try {
                    sessionManager.signInWithGoogle(activity)
                } catch (exc: CancellationException) {
                    throw exc
                } catch (exc: Exception) {
                    _uiState.value = LoginUiState.Error(LoginErrorKind.GoogleSignInFailed)
                }
            }
        }
    }
