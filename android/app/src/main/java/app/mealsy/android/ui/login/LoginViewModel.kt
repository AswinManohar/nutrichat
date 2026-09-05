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

/** UI state for the login screen. */
sealed interface LoginUiState {
    data object Idle : LoginUiState
    data object AwaitingEmail : LoginUiState
    data class Error(val message: String) : LoginUiState
}

private val EMAIL_REGEX = Regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$")

/** Returns true when `email` is a plausible address to send a magic link to. */
fun isValidEmail(email: String): Boolean = EMAIL_REGEX.matches(email.trim())

@HiltViewModel
class LoginViewModel @Inject constructor(
    private val sessionManager: SessionManager,
) : ViewModel() {

    private val _uiState = MutableStateFlow<LoginUiState>(LoginUiState.Idle)
    val uiState: StateFlow<LoginUiState> = _uiState.asStateFlow()

    /** Validates `email` and, if valid, requests a magic link via [SessionManager]. */
    fun submitEmail(email: String) {
        if (!isValidEmail(email)) {
            _uiState.value = LoginUiState.Error("Enter a valid email address.")
            return
        }
        viewModelScope.launch {
            try {
                sessionManager.signInWithMagicLink(email.trim())
                _uiState.value = LoginUiState.AwaitingEmail
            } catch (exc: CancellationException) {
                throw exc
            } catch (exc: Exception) {
                _uiState.value = LoginUiState.Error("Could not send magic link. Try again.")
            }
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
                _uiState.value = LoginUiState.Error("Google sign-in failed. Try again.")
            }
        }
    }
}
