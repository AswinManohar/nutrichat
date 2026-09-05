package app.mealsy.data.auth

import android.app.Activity
import app.cash.turbine.test
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Fake [AuthGateway] that a test can drive directly, standing in for
 * [SupabaseAuthGateway] so these stay plain JVM tests with no network and no
 * supabase-kt `SessionStatus`/`UserSession` object construction.
 */
private class FakeAuthGateway(
    initialState: SessionState = SessionState.Loading,
) : AuthGateway {
    override val sessionState = MutableStateFlow(initialState)

    var refreshedToken: String? = "refreshed-token"
    var refreshCallCount: Int = 0
        private set

    var currentToken: String? = null
    var signOutCallCount: Int = 0
        private set

    override suspend fun signInWithMagicLink(email: String) = Unit

    override suspend fun signInWithGoogle(activity: Activity) = Unit

    override suspend fun refreshCurrentSession(): String? {
        refreshCallCount++
        currentToken = refreshedToken
        return refreshedToken
    }

    override fun currentAccessTokenOrNull(): String? = currentToken

    override suspend fun signOut() {
        signOutCallCount++
        sessionState.value = SessionState.SignedOut
    }
}

class SessionManagerTest {

    @Test
    fun `sessionState is SignedIn after gotrue emits a session`() = runTest {
        val gateway = FakeAuthGateway(initialState = SessionState.Loading)
        val sessionManager = SessionManager(gateway)

        sessionManager.sessionState.test {
            assertEquals(SessionState.Loading, awaitItem())

            gateway.sessionState.value = SessionState.SignedIn(userId = "user-123")

            assertEquals(SessionState.SignedIn(userId = "user-123"), awaitItem())
        }
    }

    @Test
    fun `currentToken forceRefresh=true calls refreshSession`() = runTest {
        val gateway = FakeAuthGateway()
        gateway.currentToken = "stale-token"
        gateway.refreshedToken = "fresh-token"
        val sessionManager = SessionManager(gateway)

        val token = sessionManager.currentToken(forceRefresh = true)

        assertEquals(1, gateway.refreshCallCount)
        assertEquals("fresh-token", token)
    }

    @Test
    fun `signOut clears state`() = runTest {
        val gateway = FakeAuthGateway(initialState = SessionState.SignedIn(userId = "user-123"))
        var deviceCleanupCalled = false
        val sessionManager = SessionManager(gateway, onSignOut = { deviceCleanupCalled = true })

        sessionManager.sessionState.test {
            assertEquals(SessionState.SignedIn(userId = "user-123"), awaitItem())

            sessionManager.signOut()

            assertEquals(SessionState.SignedOut, awaitItem())
        }

        assertEquals(1, gateway.signOutCallCount)
        assertTrueDeviceCleanupCalled(deviceCleanupCalled)
    }

    private fun assertTrueDeviceCleanupCalled(called: Boolean) {
        // Task 9 will replace onSignOut with a real FCM device-deregistration
        // call; this only confirms SessionManager invokes the seam it's given.
        assertEquals(true, called)
    }
}
