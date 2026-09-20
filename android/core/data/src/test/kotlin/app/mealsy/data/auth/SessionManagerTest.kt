package app.mealsy.data.auth

import android.app.Activity
import app.cash.turbine.test
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
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
    var refreshShouldThrow: Boolean = false
    var refreshCallCount: Int = 0
        private set

    var currentToken: String? = null
    var signOutCallCount: Int = 0
        private set

    /** Records the order calls actually happened in, for ordering assertions. */
    val callOrder = mutableListOf<String>()

    override suspend fun signInWithMagicLink(email: String) = Unit

    override suspend fun signInWithGoogle(activity: Activity) = Unit

    override suspend fun refreshCurrentSession(): String? {
        refreshCallCount++
        if (refreshShouldThrow) {
            throw RuntimeException("refresh failed")
        }
        currentToken = refreshedToken
        return refreshedToken
    }

    override fun currentAccessTokenOrNull(): String? = currentToken

    override suspend fun signOut() {
        callOrder += "authGateway.signOut"
        signOutCallCount++
        sessionState.value = SessionState.SignedOut
    }

    var profileMetadata: ProfileMetadata? = null

    override suspend fun updateProfileMetadata(
        firstName: String,
        goalFocus: String,
    ) {
        profileMetadata = ProfileMetadata(firstName, goalFocus)
    }

    override suspend fun currentProfileMetadata(): ProfileMetadata? = profileMetadata
}

class SessionManagerTest {
    @Test
    fun `sessionState is SignedIn after gotrue emits a session`() =
        runTest {
            val gateway = FakeAuthGateway(initialState = SessionState.Loading)
            val sessionManager = SessionManager(gateway)

            sessionManager.sessionState.test {
                assertEquals(SessionState.Loading, awaitItem())

                gateway.sessionState.value = SessionState.SignedIn(userId = "user-123")

                assertEquals(SessionState.SignedIn(userId = "user-123"), awaitItem())
            }
        }

    @Test
    fun `currentToken forceRefresh=true calls refreshSession`() =
        runTest {
            val gateway = FakeAuthGateway()
            gateway.currentToken = "stale-token"
            gateway.refreshedToken = "fresh-token"
            val sessionManager = SessionManager(gateway)

            val token = sessionManager.currentToken(forceRefresh = true)

            assertEquals(1, gateway.refreshCallCount)
            assertEquals("fresh-token", token)
        }

    @Test
    fun `currentToken forceRefresh=true returns null when gateway refresh throws`() =
        runTest {
            // AuthInterceptor's 401-retry path calls this from a runBlocking
            // block on an OkHttp dispatcher thread. A RestException/Ktor
            // exception escaping here would surface as an unhandled crash-type
            // exception from an interceptor instead of a clean second 401
            // (Task 3's contract) — so a gateway failure must come back as
            // null, not propagate.
            val gateway = FakeAuthGateway()
            gateway.refreshShouldThrow = true
            val sessionManager = SessionManager(gateway)

            val token = sessionManager.currentToken(forceRefresh = true)

            assertEquals(1, gateway.refreshCallCount)
            assertNull(token)
        }

    @Test
    fun `signOut clears state`() =
        runTest {
            val gateway = FakeAuthGateway(initialState = SessionState.SignedIn(userId = "user-123"))
            var deviceCleanupCalled = false
            val sessionManager =
                SessionManager(
                    gateway,
                    onSignOut = {
                        gateway.callOrder += "onSignOut"
                        deviceCleanupCalled = true
                    },
                )

            sessionManager.sessionState.test {
                assertEquals(SessionState.SignedIn(userId = "user-123"), awaitItem())

                sessionManager.signOut()

                assertEquals(SessionState.SignedOut, awaitItem())
            }

            assertEquals(1, gateway.signOutCallCount)
            assertTrueDeviceCleanupCalled(deviceCleanupCalled)
            // onSignOut (Task 9's authenticated deleteDevice hook) must run
            // before the session is cleared, or it would 401.
            assertEquals(listOf("onSignOut", "authGateway.signOut"), gateway.callOrder)
        }

    @Test
    fun `signOut still clears the session when onSignOut throws`() =
        runTest {
            val gateway = FakeAuthGateway(initialState = SessionState.SignedIn(userId = "user-123"))
            val sessionManager = SessionManager(gateway, onSignOut = { throw RuntimeException("boom") })

            sessionManager.sessionState.test {
                assertEquals(SessionState.SignedIn(userId = "user-123"), awaitItem())

                sessionManager.signOut()

                assertEquals(SessionState.SignedOut, awaitItem())
            }

            assertTrue(gateway.signOutCallCount == 1)
        }

    private fun assertTrueDeviceCleanupCalled(called: Boolean) {
        // Task 9 will replace onSignOut with a real FCM device-deregistration
        // call; this only confirms SessionManager invokes the seam it's given.
        assertEquals(true, called)
    }
}
