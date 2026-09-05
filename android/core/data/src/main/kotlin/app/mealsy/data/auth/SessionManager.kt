package app.mealsy.data.auth

import android.app.Activity
import kotlinx.coroutines.flow.StateFlow
import javax.inject.Inject

/** Coarse-grained auth state exposed to the rest of the app. */
sealed interface SessionState {
    data object Loading : SessionState
    data object SignedOut : SessionState
    data class SignedIn(val userId: String) : SessionState
}

/**
 * Thin seam over supabase-kt's `Auth` plugin.
 *
 * `Auth` itself is a large multiplatform interface (OAuth providers, admin
 * APIs, etc.), and its session model (`SessionStatus` / `UserSession`) is
 * awkward to construct by hand. [SupabaseAuthGateway] does the real mapping
 * down to the app's own [SessionState]; [SessionManagerTest] swaps in a fake
 * that drives [sessionState] directly, so it stays a plain JVM test with no
 * supabase-kt object construction and no Android framework dependency.
 */
interface AuthGateway {
    val sessionState: StateFlow<SessionState>

    suspend fun signInWithMagicLink(email: String)

    suspend fun signInWithGoogle(activity: Activity)

    /** Forces a network refresh and returns the resulting access token. */
    suspend fun refreshCurrentSession(): String?

    /** Returns the current access token without triggering a refresh. */
    fun currentAccessTokenOrNull(): String?

    suspend fun signOut()
}

/**
 * Owns the app's Supabase auth session.
 *
 * [sessionState] mirrors [AuthGateway.sessionState]. [currentToken] is bound
 * as the [app.mealsy.data.api.TokenProvider] for
 * [app.mealsy.data.api.AuthInterceptor] (see `AuthModule`).
 *
 * `onSignOut` is a seam for Task 9's `POST /devices/{fcmToken}` best-effort
 * deregistration — that call needs the FCM token and API client, neither of
 * which this class should depend on directly. Task 9 supplies a real
 * implementation via Hilt; until then it defaults to a no-op.
 */
class SessionManager @Inject constructor(
    private val authGateway: AuthGateway,
    private val onSignOut: suspend () -> Unit = {},
) {
    val sessionState: StateFlow<SessionState> = authGateway.sessionState

    suspend fun signInWithMagicLink(email: String) {
        authGateway.signInWithMagicLink(email)
    }

    suspend fun signInWithGoogle(activity: Activity) {
        authGateway.signInWithGoogle(activity)
    }

    /**
     * Returns the current access token, or `null` when signed out.
     *
     * `forceRefresh = true` refreshes the session against Supabase first —
     * used by [app.mealsy.data.api.AuthInterceptor] after a 401.
     */
    suspend fun currentToken(forceRefresh: Boolean = false): String? {
        return if (forceRefresh) {
            authGateway.refreshCurrentSession()
        } else {
            authGateway.currentAccessTokenOrNull()
        }
    }

    suspend fun signOut() {
        authGateway.signOut()
        onSignOut()
    }
}
