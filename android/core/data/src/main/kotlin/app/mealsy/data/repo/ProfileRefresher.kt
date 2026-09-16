package app.mealsy.data.repo

import app.mealsy.data.auth.AuthGateway
import app.mealsy.data.error.ErrorReporter
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Pulls `first_name`/`goal_focus` from Supabase user metadata into the
 * local [ProfileStore] cache.
 *
 * `:app`'s `AppNavViewModel` calls [refreshProfileFromMetadata] whenever it
 * observes a sign-in (Task T5), so the greeting shown right after login
 * reflects whatever onboarding wrote to Supabase on a previous device/
 * session, not just this device's local cache. That call site is wired by
 * a later task — this class only needs to exist and be Hilt-injectable.
 *
 * Best-effort by design: metadata fetch failures (offline, token expiry
 * mid-refresh, etc.) must not block sign-in or crash the caller, so any
 * exception is recorded via [ErrorReporter] and swallowed, matching
 * [app.mealsy.data.auth.SessionManager]'s existing best-effort swallow
 * paths.
 */
@Singleton
class ProfileRefresher @Inject constructor(
    private val authGateway: AuthGateway,
    private val profileStore: ProfileStore,
    private val errorReporter: ErrorReporter,
) {
    suspend fun refreshProfileFromMetadata() {
        try {
            val metadata = authGateway.currentProfileMetadata() ?: return
            profileStore.set(metadata.firstName, metadata.goalFocus)
        } catch (exc: Exception) {
            errorReporter.record(exc)
        }
    }
}
