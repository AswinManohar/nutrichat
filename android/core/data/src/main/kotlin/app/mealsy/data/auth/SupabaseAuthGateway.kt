package app.mealsy.data.auth

import android.app.Activity
import io.github.jan.supabase.gotrue.Auth
import io.github.jan.supabase.gotrue.SessionStatus
import io.github.jan.supabase.gotrue.SignOutScope
import io.github.jan.supabase.gotrue.providers.Google
import io.github.jan.supabase.gotrue.providers.builtin.OTP
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import javax.inject.Inject

/**
 * [AuthGateway] backed by the real supabase-kt `Auth` plugin.
 *
 * Magic-link sign-in uses the built-in `OTP` provider with no password,
 * which Supabase treats as a magic link. Google sign-in uses supabase-kt's
 * generic OAuth flow (opens the system browser via a Custom Tab and relies
 * on the `mealsy://auth-callback` deep link to hand control back to the
 * app) rather than the native Credential Manager / ID-token flow, so no
 * extra Google Play Services dependency is needed for this task.
 */
class SupabaseAuthGateway @Inject constructor(private val auth: Auth) : AuthGateway {

    // supabase-kt's own StateFlow<SessionStatus> isn't backed by a scope we
    // control, so mapping it down to our SessionState needs one of our own.
    // SupervisorJob so a mapping failure on one emission can't kill the
    // whole session stream.
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    override val sessionState: StateFlow<SessionState> =
        auth.sessionStatus
            .map { it.toSessionState() }
            .stateIn(scope, SharingStarted.Eagerly, auth.sessionStatus.value.toSessionState())

    override suspend fun signInWithMagicLink(email: String) {
        auth.signInWith(OTP) { this.email = email }
    }

    override suspend fun signInWithGoogle(activity: Activity) {
        auth.signInWith(Google)
    }

    override suspend fun refreshCurrentSession(): String? {
        auth.refreshCurrentSession()
        return auth.currentAccessTokenOrNull()
    }

    override fun currentAccessTokenOrNull(): String? = auth.currentAccessTokenOrNull()

    override suspend fun signOut() {
        auth.signOut(SignOutScope.LOCAL)
    }

    private fun SessionStatus.toSessionState(): SessionState = when (this) {
        is SessionStatus.Authenticated -> SessionState.SignedIn(userId = session.user?.id.orEmpty())
        is SessionStatus.NotAuthenticated -> SessionState.SignedOut
        is SessionStatus.LoadingFromStorage -> SessionState.Loading
        // A refresh failing on the network doesn't necessarily mean the
        // session is invalid, but there's nothing usable to show as
        // "signed in" — fall back to signed-out rather than getting stuck
        // showing Loading forever.
        is SessionStatus.NetworkError -> SessionState.SignedOut
    }
}
