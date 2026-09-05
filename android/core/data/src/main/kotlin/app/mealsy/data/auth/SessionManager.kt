package app.mealsy.data.auth

import android.app.Activity
import kotlinx.coroutines.flow.StateFlow

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
 * Seam for Task 9's best-effort FCM device deregistration on sign-out.
 *
 * Declared here (rather than `SessionManager` depending on
 * `app.mealsy.android.push.PushRegistrar` directly) because `:core:data`
 * cannot depend on `:app`, where `PushRegistrar` lives — `AuthModule`
 * requires a [SignOutHook] binding, and `:app`'s `PushModule` supplies the
 * real implementation via Hilt.
 */
fun interface SignOutHook {
    suspend fun onDeviceSignOut()
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
class SessionManager(
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
            try {
                authGateway.refreshCurrentSession()
            } catch (_: Exception) {
                // AuthInterceptor calls this from its 401-retry path with
                // runBlocking; a RestException/Ktor exception escaping
                // here would surface as an unhandled crash-type exception
                // from an OkHttp interceptor instead of Task 3's "second
                // 401 propagates" contract. Swallow and return null so the
                // retried request goes out unauthenticated and yields a
                // clean 401.
                null
            }
        } else {
            authGateway.currentAccessTokenOrNull()
        }
    }

    suspend fun signOut() {
        // onSignOut (Task 9: best-effort FCM device deregistration) needs
        // an authenticated request, so it must run before the session is
        // cleared — clearing first would make that call 401. Wrapped so a
        // failing hook never blocks the local sign-out it's piggybacking on.
        try {
            onSignOut()
        } catch (_: Exception) {
            // Best-effort only — device deregistration failing must not
            // prevent the user from signing out.
        }
        authGateway.signOut()
    }
}
