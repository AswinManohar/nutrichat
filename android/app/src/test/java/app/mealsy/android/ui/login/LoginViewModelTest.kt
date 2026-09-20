package app.mealsy.android.ui.login

import android.app.Activity
import app.cash.turbine.test
import app.mealsy.android.ui.isUpdateRequired
import app.mealsy.data.auth.AuthGateway
import app.mealsy.data.auth.ProfileMetadata
import app.mealsy.data.auth.SessionManager
import app.mealsy.data.auth.SessionState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * [AuthGateway] is already the seam Task 4 designed for faking (see its
 * kdoc), so this fake plugs straight into a real [SessionManager] rather
 * than needing a second interface carved out of the ViewModel.
 */
private class FakeAuthGateway : AuthGateway {
    override val sessionState = MutableStateFlow<SessionState>(SessionState.SignedOut)

    val magicLinkCalls = mutableListOf<String>()
    var throwOnMagicLink: Exception? = null

    override suspend fun signInWithMagicLink(email: String) {
        throwOnMagicLink?.let { throw it }
        magicLinkCalls.add(email)
    }

    override suspend fun signInWithGoogle(activity: Activity) = Unit

    override suspend fun refreshCurrentSession(): String? = null

    override fun currentAccessTokenOrNull(): String? = null

    override suspend fun signOut() = Unit

    override suspend fun updateProfileMetadata(firstName: String, goalFocus: String) = Unit

    override suspend fun currentProfileMetadata(): ProfileMetadata? = null
}

@OptIn(ExperimentalCoroutinesApi::class)
class LoginViewModelTest {

    private val dispatcher = StandardTestDispatcher()
    private lateinit var fakeAuthGateway: FakeAuthGateway
    private lateinit var viewModel: LoginViewModel

    @Before
    fun setUp() {
        Dispatchers.setMain(dispatcher)
        fakeAuthGateway = FakeAuthGateway()
        viewModel = LoginViewModel(SessionManager(fakeAuthGateway))
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun `submit email calls signInWithMagicLink and enters AwaitingEmail state`() = runTest {
        viewModel.uiState.test {
            assertEquals(LoginUiState.Idle, awaitItem())

            viewModel.submitEmail("user@example.com")

            assertEquals(LoginUiState.AwaitingEmail, awaitItem())
            assertEquals(listOf("user@example.com"), fakeAuthGateway.magicLinkCalls)
        }
    }

    @Test
    fun `invalid email shows error, no call`() = runTest {
        viewModel.uiState.test {
            assertEquals(LoginUiState.Idle, awaitItem())

            viewModel.submitEmail("not-an-email")

            val state = awaitItem()
            assertTrue(state is LoginUiState.Error)
            assertEquals(LoginErrorKind.InvalidEmail, (state as LoginUiState.Error).kind)
            assertTrue(fakeAuthGateway.magicLinkCalls.isEmpty())
        }
    }

    @Test
    fun `magic link failure shows MagicLinkFailed error`() = runTest {
        fakeAuthGateway.throwOnMagicLink = RuntimeException("boom")
        viewModel.uiState.test {
            assertEquals(LoginUiState.Idle, awaitItem())

            viewModel.submitEmail("user@example.com")

            val state = awaitItem()
            assertTrue(state is LoginUiState.Error)
            assertEquals(LoginErrorKind.MagicLinkFailed, (state as LoginUiState.Error).kind)
        }
    }

    @Test
    fun `gate blocks when versionCode below min`() {
        assertTrue(isUpdateRequired(currentVersionCode = 1, minSupportedVersionCode = 2))
        assertFalse(isUpdateRequired(currentVersionCode = 2, minSupportedVersionCode = 2))
        assertFalse(isUpdateRequired(currentVersionCode = 3, minSupportedVersionCode = 2))
    }
}
