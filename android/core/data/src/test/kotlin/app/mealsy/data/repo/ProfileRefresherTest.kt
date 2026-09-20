package app.mealsy.data.repo

import android.app.Activity
import app.mealsy.data.auth.AuthGateway
import app.mealsy.data.auth.ProfileMetadata
import app.mealsy.data.auth.SessionManager
import app.mealsy.data.auth.SessionState
import app.mealsy.data.error.ErrorReporter
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * [ProfileRefresher] and [SessionManager]'s `updateProfileMetadata`/
 * `currentProfileMetadata` pass-throughs, against a fake [AuthGateway] —
 * plain JVM, no supabase-kt object construction, same convention as
 * `SessionManagerTest`.
 */
class ProfileRefresherTest {
    private class FakeAuthGateway(
        initialState: SessionState = SessionState.SignedIn(userId = "user-123"),
        private val metadata: ProfileMetadata? = null,
        private val throwOnRead: Boolean = false,
    ) : AuthGateway {
        override val sessionState = MutableStateFlow(initialState)

        var updateCall: Pair<String, String>? = null
            private set

        override suspend fun signInWithMagicLink(email: String) = Unit

        override suspend fun signInWithGoogle(activity: Activity) = Unit

        override suspend fun refreshCurrentSession(): String? = null

        override fun currentAccessTokenOrNull(): String? = null

        override suspend fun signOut() = Unit

        override suspend fun updateProfileMetadata(
            firstName: String,
            goalFocus: String,
        ) {
            updateCall = firstName to goalFocus
        }

        override suspend fun currentProfileMetadata(): ProfileMetadata? {
            if (throwOnRead) throw RuntimeException("metadata fetch failed")
            return metadata
        }
    }

    private class FakeErrorReporter : ErrorReporter {
        val recorded = mutableListOf<Throwable>()

        override fun record(t: Throwable) {
            recorded += t
        }
    }

    @Test
    fun `SessionManager updateProfileMetadata delegates to the gateway`() =
        runTest {
            val gateway = FakeAuthGateway()
            val sessionManager = SessionManager(gateway)

            sessionManager.updateProfileMetadata("Sam", "mindful")

            assertEquals("Sam" to "mindful", gateway.updateCall)
        }

    @Test
    fun `SessionManager currentProfileMetadata delegates to the gateway`() =
        runTest {
            val gateway = FakeAuthGateway(metadata = ProfileMetadata("Sam", "mindful"))
            val sessionManager = SessionManager(gateway)

            assertEquals(ProfileMetadata("Sam", "mindful"), sessionManager.currentProfileMetadata())
        }

    @Test
    fun `refreshProfileFromMetadata writes the gateway's metadata into the store`() =
        runTest {
            val gateway = FakeAuthGateway(metadata = ProfileMetadata("Sam", "mindful"))
            val profileStore = DataStoreProfileStoreFake()
            val errorReporter = FakeErrorReporter()
            val refresher = ProfileRefresher(gateway, profileStore, errorReporter)

            refresher.refreshProfileFromMetadata()

            assertEquals(Profile("Sam", "mindful"), profileStore.get())
            assertTrue(errorReporter.recorded.isEmpty())
        }

    @Test
    fun `refreshProfileFromMetadata is a no-op when signed out`() =
        runTest {
            val gateway = FakeAuthGateway(metadata = null)
            val profileStore = DataStoreProfileStoreFake()
            val refresher = ProfileRefresher(gateway, profileStore, FakeErrorReporter())

            refresher.refreshProfileFromMetadata()

            assertEquals(Profile(), profileStore.get())
        }

    @Test
    fun `refreshProfileFromMetadata reports and swallows a gateway failure`() =
        runTest {
            val gateway = FakeAuthGateway(throwOnRead = true)
            val profileStore = DataStoreProfileStoreFake()
            val errorReporter = FakeErrorReporter()
            val refresher = ProfileRefresher(gateway, profileStore, errorReporter)

            refresher.refreshProfileFromMetadata()

            assertEquals(1, errorReporter.recorded.size)
            assertNull(profileStore.get().firstName)
        }
}

/** In-memory [ProfileStore] fake — no DataStore/Android framework dependency. */
private class DataStoreProfileStoreFake : ProfileStore {
    private val state = MutableStateFlow(Profile())
    override val profile = state

    override suspend fun get(): Profile = state.value

    override suspend fun set(
        firstName: String?,
        goalFocus: String?,
    ) {
        state.value =
            state.value.copy(
                firstName = firstName ?: state.value.firstName,
                goalFocus = goalFocus ?: state.value.goalFocus,
            )
    }

    override suspend fun clear() {
        state.value = Profile()
    }
}
