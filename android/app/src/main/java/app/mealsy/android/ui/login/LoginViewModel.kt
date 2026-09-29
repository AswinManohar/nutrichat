package app.mealsy.android.ui.login

import android.app.Activity
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.mealsy.data.auth.AuthCallbackErrorKind
import app.mealsy.data.auth.AuthCallbackErrors
import app.mealsy.data.auth.GoogleAuthAvailabilityGateway
import app.mealsy.data.auth.GoogleSignInError
import app.mealsy.data.auth.GoogleSignInException
import app.mealsy.data.auth.SessionManager
import app.mealsy.data.auth.SessionState
import dagger.hilt.android.lifecycle.HiltViewModel
import io.github.jan.supabase.gotrue.exception.AuthErrorCode
import io.github.jan.supabase.gotrue.exception.AuthRestException
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

/** Seconds a user must wait before [LoginViewModel.resendMagicLink] is allowed again. */
internal const val RESEND_COOLDOWN_SECONDS = 60

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

    /** [SessionManager.signInWithMagicLink] threw, for a reason not covered below. */
    data object MagicLinkFailed : LoginErrorKind

    /** [SessionManager.signInWithGoogle] threw, for a reason not covered below. */
    data object GoogleSignInFailed : LoginErrorKind

    /** No Google account is signed in on this device (Credential Manager found none). */
    data object GoogleNoAccount : LoginErrorKind

    /** This build has no `GOOGLE_WEB_CLIENT_ID`. */
    data object GoogleNotConfigured : LoginErrorKind

    /** Supabase says the Google provider is not enabled. */
    data object GoogleUnavailable : LoginErrorKind

    /** The device could not reach Supabase during Google sign-in. */
    data object Offline : LoginErrorKind

    /**
     * The `mealsy://auth-callback` link was opened a second time, or after
     * its TTL elapsed (`otp_expired`) — either from
     * [AuthCallbackErrors] or from a fresh
     * [SessionManager.signInWithMagicLink]/resend call (#34).
     */
    data object LinkExpired : LoginErrorKind

    /**
     * Supabase's per-address/per-project send limit was hit (HTTP 429 /
     * `over_email_send_rate_limit`), from either path above (#34).
     */
    data object RateLimited : LoginErrorKind
}

/** UI state for the login screen. */
sealed interface LoginUiState {
    data object Idle : LoginUiState

    /**
     * @param email The address the link was (most recently) sent to — kept
     *   so [LoginViewModel.resendMagicLink] knows where to resend without
     *   the caller re-passing it.
     * @param resendCooldownSeconds Seconds until "Resend link" is enabled
     *   again; 0 means it's enabled now.
     */
    data class AwaitingEmail(val email: String, val resendCooldownSeconds: Int) : LoginUiState

    data class Error(val kind: LoginErrorKind) : LoginUiState
}

private val EMAIL_REGEX = Regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$")

/** Returns true when `email` is a plausible address to send a magic link to. */
fun isValidEmail(email: String): Boolean = EMAIL_REGEX.matches(email.trim())

/**
 * Maps an exception from [SessionManager.signInWithMagicLink] to a
 * [LoginErrorKind] (#34). supabase-kt surfaces Supabase's JSON error body as
 * [AuthRestException], which carries both the HTTP status and Supabase's own
 * `error_code`; a rate limit can show up as either (a `429` with a generic
 * body, or a `200`-adjacent body naming `over_email_send_rate_limit`
 * depending on which layer rejects the request), so both are checked.
 */
internal fun mapMagicLinkException(exc: Exception): LoginErrorKind =
    when {
        exc is AuthRestException &&
            (exc.errorCode == AuthErrorCode.OverEmailSendRateLimit || exc.statusCode == 429) -> LoginErrorKind.RateLimited
        exc is AuthRestException && exc.errorCode == AuthErrorCode.OtpExpired -> LoginErrorKind.LinkExpired
        else -> LoginErrorKind.MagicLinkFailed
    }

/** Maps a Google sign-in failure to a [LoginErrorKind]; null for a user cancel, which is silent. */
internal fun GoogleSignInException.toLoginErrorKind(): LoginErrorKind? =
    when (error) {
        GoogleSignInError.Cancelled -> null
        GoogleSignInError.NoAccount -> LoginErrorKind.GoogleNoAccount
        GoogleSignInError.NotConfigured -> LoginErrorKind.GoogleNotConfigured
        GoogleSignInError.ProviderDisabled -> LoginErrorKind.GoogleUnavailable
        GoogleSignInError.Network -> LoginErrorKind.Offline
        GoogleSignInError.Failed -> LoginErrorKind.GoogleSignInFailed
    }

/** True for the kinds that come from the Google button, so the screen can show them beside it. */
internal fun LoginErrorKind.isGoogleError(): Boolean =
    this == LoginErrorKind.GoogleSignInFailed ||
        this == LoginErrorKind.GoogleNoAccount ||
        this == LoginErrorKind.GoogleNotConfigured ||
        this == LoginErrorKind.GoogleUnavailable ||
        this == LoginErrorKind.Offline

/** Maps a parsed [AuthCallbackErrorKind] (from a deep link, #34) to a [LoginErrorKind]. */
internal fun mapCallbackErrorKind(kind: AuthCallbackErrorKind): LoginErrorKind =
    when (kind) {
        AuthCallbackErrorKind.LINK_EXPIRED_OR_USED -> LoginErrorKind.LinkExpired
        AuthCallbackErrorKind.RATE_LIMITED -> LoginErrorKind.RateLimited
        AuthCallbackErrorKind.OTHER -> LoginErrorKind.MagicLinkFailed
    }

@HiltViewModel
class LoginViewModel
    @Inject
    constructor(
        private val sessionManager: SessionManager,
        private val authCallbackErrors: AuthCallbackErrors = AuthCallbackErrors(),
        private val googleAuthAvailabilityGateway: GoogleAuthAvailabilityGateway =
            object : GoogleAuthAvailabilityGateway {
                override suspend fun isGoogleSignInEnabled() = true
            },
    ) : ViewModel() {
        private val _uiState = MutableStateFlow<LoginUiState>(LoginUiState.Idle)
        val uiState: StateFlow<LoginUiState> = _uiState.asStateFlow()

        // #32: hidden (rather than defaulted visible-but-broken) until the
        // one-time /auth/v1/settings fetch resolves, then reflects it;
        // GoogleAuthAvailabilityGateway itself fails open on error/timeout,
        // so this only ever stays false when Supabase confirms the provider
        // is off.
        private val _googleSignInAvailable = MutableStateFlow(true)
        val googleSignInAvailable: StateFlow<Boolean> = _googleSignInAvailable.asStateFlow()

        private val _googleBusy = MutableStateFlow(false)

        /** True while a Google sign-in is in flight, so the button can't be double-tapped. */
        val googleBusy: StateFlow<Boolean> = _googleBusy.asStateFlow()

        private var cooldownJob: Job? = null

        init {
            viewModelScope.launch {
                _googleSignInAvailable.value = googleAuthAvailabilityGateway.isGoogleSignInEnabled()
            }
            // MainActivity owns the raw deep-link Intent (see
            // AuthCallbackErrors' kdoc) and publishes here whenever it
            // carries an error instead of a successful `code` — most
            // notably an already-used/expired magic link opened on this
            // device after another one already consumed it (#34). This also
            // covers the app being cold-started by the error link itself:
            // AuthCallbackErrors.pending is a StateFlow, so a publish from
            // MainActivity.onCreate before this collector starts is still
            // replayed here rather than lost.
            viewModelScope.launch {
                authCallbackErrors.pending.collect { error ->
                    if (error == null) return@collect
                    cooldownJob?.cancel()
                    _uiState.value = LoginUiState.Error(mapCallbackErrorKind(error.kind))
                    // Consumed immediately so a *later* LoginViewModel
                    // (e.g. after the user backs out and returns) doesn't
                    // re-show an error already surfaced once.
                    authCallbackErrors.consume()
                }
            }
            // A stale pending error (from the deep link that carried the
            // session's own successful sign-in, or a leftover from before
            // it) has nothing left to say once the user is signed in.
            viewModelScope.launch {
                sessionManager.sessionState.collect { state ->
                    if (state is SessionState.SignedIn) {
                        authCallbackErrors.consume()
                    }
                }
            }
        }

        /** Validates `email` and, if valid, requests a magic link via [SessionManager]. */
        fun submitEmail(email: String) {
            if (!isValidEmail(email)) {
                _uiState.value = LoginUiState.Error(LoginErrorKind.InvalidEmail)
                return
            }
            val trimmed = email.trim()
            viewModelScope.launch {
                try {
                    sessionManager.signInWithMagicLink(trimmed)
                    enterAwaitingEmail(trimmed)
                } catch (exc: CancellationException) {
                    throw exc
                } catch (exc: Exception) {
                    _uiState.value = LoginUiState.Error(mapMagicLinkException(exc))
                }
            }
        }

        /**
         * Re-sends the magic link to the address already in
         * [LoginUiState.AwaitingEmail], and resets its cooldown. A no-op
         * outside that state, or while the cooldown hasn't elapsed yet —
         * [LoginScreen] disables the action in both cases, this just guards
         * against a stale click racing a state change.
         */
        fun resendMagicLink() {
            val current = _uiState.value
            if (current !is LoginUiState.AwaitingEmail || current.resendCooldownSeconds > 0) return
            viewModelScope.launch {
                try {
                    sessionManager.signInWithMagicLink(current.email)
                    enterAwaitingEmail(current.email)
                } catch (exc: CancellationException) {
                    throw exc
                } catch (exc: Exception) {
                    _uiState.value = LoginUiState.Error(mapMagicLinkException(exc))
                }
            }
        }

        private fun enterAwaitingEmail(email: String) {
            _uiState.value = LoginUiState.AwaitingEmail(email, RESEND_COOLDOWN_SECONDS)
            startCooldown()
        }

        private fun startCooldown() {
            cooldownJob?.cancel()
            cooldownJob =
                viewModelScope.launch {
                    while (true) {
                        delay(1_000)
                        val current = _uiState.value
                        if (current !is LoginUiState.AwaitingEmail || current.resendCooldownSeconds <= 0) return@launch
                        _uiState.value = current.copy(resendCooldownSeconds = current.resendCooldownSeconds - 1)
                    }
                }
        }

        /**
         * Returns from [LoginUiState.AwaitingEmail] to the email-entry step.
         * Wired to system Back (#29 — every in-screen multi-step flow should
         * step back rather than exit) and to the "Use a different email"
         * link (#34), so a user who sent themselves a magic link can
         * correct the address or pick Google sign-in instead, without
         * leaving the screen.
         */
        fun backToEmail() {
            if (_uiState.value is LoginUiState.AwaitingEmail) {
                cooldownJob?.cancel()
                _uiState.value = LoginUiState.Idle
            }
        }

        /** Starts native Google sign-in (Credential Manager) via [SessionManager]. */
        fun signInWithGoogle(activity: Activity) {
            if (_googleBusy.value) return
            _googleBusy.value = true
            viewModelScope.launch {
                try {
                    sessionManager.signInWithGoogle(activity)
                } catch (exc: CancellationException) {
                    throw exc
                } catch (exc: GoogleSignInException) {
                    // A user cancel maps to null: stay silent, leave any prior state alone.
                    exc.toLoginErrorKind()?.let { _uiState.value = LoginUiState.Error(it) }
                } catch (exc: Exception) {
                    _uiState.value = LoginUiState.Error(LoginErrorKind.GoogleSignInFailed)
                } finally {
                    _googleBusy.value = false
                }
            }
        }
    }
