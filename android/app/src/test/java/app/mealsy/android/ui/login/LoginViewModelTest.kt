package app.mealsy.android.ui.login

import android.app.Activity
import app.cash.turbine.test
import app.mealsy.android.ui.isUpdateRequired
import app.mealsy.data.auth.AuthCallbackError
import app.mealsy.data.auth.AuthCallbackErrorKind
import app.mealsy.data.auth.AuthCallbackErrors
import app.mealsy.data.auth.AuthGateway
import app.mealsy.data.auth.GoogleAuthAvailabilityGateway
import app.mealsy.data.auth.ProfileMetadata
import app.mealsy.data.auth.SessionManager
import app.mealsy.data.auth.SessionState
import io.github.jan.supabase.gotrue.exception.AuthRestException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceTimeBy
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

    override suspend fun updateProfileMetadata(
        firstName: String,
        goalFocus: String,
    ) = Unit

    override suspend fun currentProfileMetadata(): ProfileMetadata? = null
}

private class FakeGoogleAuthAvailabilityGateway(private val enabled: Boolean = true) : GoogleAuthAvailabilityGateway {
    override suspend fun isGoogleSignInEnabled(): Boolean = enabled
}

@OptIn(ExperimentalCoroutinesApi::class)
class LoginViewModelTest {
    private val dispatcher = StandardTestDispatcher()
    private lateinit var fakeAuthGateway: FakeAuthGateway
    private lateinit var authCallbackErrors: AuthCallbackErrors
    private lateinit var viewModel: LoginViewModel

    @Before
    fun setUp() {
        Dispatchers.setMain(dispatcher)
        fakeAuthGateway = FakeAuthGateway()
        authCallbackErrors = AuthCallbackErrors()
        viewModel =
            LoginViewModel(
                sessionManager = SessionManager(fakeAuthGateway),
                authCallbackErrors = authCallbackErrors,
                googleAuthAvailabilityGateway = FakeGoogleAuthAvailabilityGateway(),
            )
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun `submit email calls signInWithMagicLink and enters AwaitingEmail state`() =
        runTest {
            viewModel.uiState.test {
                assertEquals(LoginUiState.Idle, awaitItem())

                viewModel.submitEmail("user@example.com")

                assertEquals(
                    LoginUiState.AwaitingEmail("user@example.com", RESEND_COOLDOWN_SECONDS),
                    awaitItem(),
                )
                assertEquals(listOf("user@example.com"), fakeAuthGateway.magicLinkCalls)
            }
        }

    @Test
    fun `invalid email shows error, no call`() =
        runTest {
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
    fun `magic link failure shows MagicLinkFailed error`() =
        runTest {
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
    fun `429 magic link failure shows RateLimited error`() =
        runTest {
            fakeAuthGateway.throwOnMagicLink = AuthRestException("over_email_send_rate_limit", "too many", 429)
            viewModel.uiState.test {
                assertEquals(LoginUiState.Idle, awaitItem())

                viewModel.submitEmail("user@example.com")

                val state = awaitItem()
                assertTrue(state is LoginUiState.Error)
                assertEquals(LoginErrorKind.RateLimited, (state as LoginUiState.Error).kind)
            }
        }

    @Test
    fun `over_email_send_rate_limit error code shows RateLimited even without 429 status`() =
        runTest {
            fakeAuthGateway.throwOnMagicLink =
                AuthRestException("over_email_send_rate_limit", "too many", 200)
            viewModel.uiState.test {
                assertEquals(LoginUiState.Idle, awaitItem())

                viewModel.submitEmail("user@example.com")

                val state = awaitItem()
                assertTrue(state is LoginUiState.Error)
                assertEquals(LoginErrorKind.RateLimited, (state as LoginUiState.Error).kind)
            }
        }

    @Test
    fun `otp_expired error code shows LinkExpired`() =
        runTest {
            fakeAuthGateway.throwOnMagicLink = AuthRestException("otp_expired", "expired", 403)
            viewModel.uiState.test {
                assertEquals(LoginUiState.Idle, awaitItem())

                viewModel.submitEmail("user@example.com")

                val state = awaitItem()
                assertTrue(state is LoginUiState.Error)
                assertEquals(LoginErrorKind.LinkExpired, (state as LoginUiState.Error).kind)
            }
        }

    @Test
    fun `backToEmail returns from AwaitingEmail to Idle`() =
        runTest {
            viewModel.uiState.test {
                assertEquals(LoginUiState.Idle, awaitItem())

                viewModel.submitEmail("user@example.com")
                awaitItem()

                viewModel.backToEmail()
                assertEquals(LoginUiState.Idle, awaitItem())
            }
        }

    @Test
    fun `backToEmail is a no-op outside AwaitingEmail`() =
        runTest {
            viewModel.uiState.test {
                assertEquals(LoginUiState.Idle, awaitItem())

                viewModel.submitEmail("not-an-email")
                val errorState = awaitItem()
                assertTrue(errorState is LoginUiState.Error)

                viewModel.backToEmail()
                expectNoEvents()
            }
        }

    @Test
    fun `resend is a no-op before the cooldown elapses`() =
        runTest {
            viewModel.uiState.test {
                assertEquals(LoginUiState.Idle, awaitItem())

                viewModel.submitEmail("user@example.com")
                awaitItem()
                assertEquals(listOf("user@example.com"), fakeAuthGateway.magicLinkCalls)

                viewModel.resendMagicLink()
                // No new call, no new state — still under cooldown.
                assertEquals(listOf("user@example.com"), fakeAuthGateway.magicLinkCalls)
                expectNoEvents()
            }
        }

    @Test
    fun `cooldown ticks down and resend succeeds once it reaches zero`() =
        runTest {
            viewModel.uiState.test {
                assertEquals(LoginUiState.Idle, awaitItem())

                viewModel.submitEmail("user@example.com")
                assertEquals(
                    LoginUiState.AwaitingEmail("user@example.com", RESEND_COOLDOWN_SECONDS),
                    awaitItem(),
                )

                // Drain every 1s tick down to 0.
                repeat(RESEND_COOLDOWN_SECONDS) { tick ->
                    advanceTimeBy(1_000)
                    assertEquals(
                        LoginUiState.AwaitingEmail("user@example.com", RESEND_COOLDOWN_SECONDS - tick - 1),
                        awaitItem(),
                    )
                }

                viewModel.resendMagicLink()
                assertEquals(
                    LoginUiState.AwaitingEmail("user@example.com", RESEND_COOLDOWN_SECONDS),
                    awaitItem(),
                )
                assertEquals(
                    listOf("user@example.com", "user@example.com"),
                    fakeAuthGateway.magicLinkCalls,
                )
            }
        }

    @Test
    fun `auth callback error updates state to the mapped LoginErrorKind`() =
        runTest {
            viewModel.uiState.test {
                assertEquals(LoginUiState.Idle, awaitItem())

                authCallbackErrors.publish(
                    AuthCallbackError(AuthCallbackErrorKind.LINK_EXPIRED_OR_USED, "otp_expired", null),
                )

                val state = awaitItem()
                assertTrue(state is LoginUiState.Error)
                assertEquals(LoginErrorKind.LinkExpired, (state as LoginUiState.Error).kind)
            }
        }

    @Test
    fun `auth callback error published before the ViewModel exists is still shown (cold start)`() =
        runTest {
            // Mirrors MainActivity.onCreate publishing from a killed-app
            // cold start, before LoginViewModel is constructed and starts
            // collecting.
            val coldStartErrors = AuthCallbackErrors()
            coldStartErrors.publish(
                AuthCallbackError(AuthCallbackErrorKind.LINK_EXPIRED_OR_USED, "otp_expired", null),
            )

            val coldStartViewModel =
                LoginViewModel(
                    sessionManager = SessionManager(FakeAuthGateway()),
                    authCallbackErrors = coldStartErrors,
                    googleAuthAvailabilityGateway = FakeGoogleAuthAvailabilityGateway(),
                )

            coldStartViewModel.uiState.test {
                // The StateFlow's own initial value (Idle) is always
                // replayed to a new collector first; the mapped error
                // follows as soon as init's collector coroutine runs.
                assertEquals(LoginUiState.Idle, awaitItem())

                val state = awaitItem()
                assertTrue(state is LoginUiState.Error)
                assertEquals(LoginErrorKind.LinkExpired, (state as LoginUiState.Error).kind)
            }
        }

    @Test
    fun `a consumed auth callback error does not replay into a later ViewModel`() =
        runTest {
            val sharedErrors = AuthCallbackErrors()
            sharedErrors.publish(
                AuthCallbackError(AuthCallbackErrorKind.LINK_EXPIRED_OR_USED, "otp_expired", null),
            )

            val firstViewModel =
                LoginViewModel(
                    sessionManager = SessionManager(FakeAuthGateway()),
                    authCallbackErrors = sharedErrors,
                    googleAuthAvailabilityGateway = FakeGoogleAuthAvailabilityGateway(),
                )
            firstViewModel.uiState.test {
                assertEquals(LoginUiState.Idle, awaitItem())
                val state = awaitItem()
                assertTrue(state is LoginUiState.Error)
            }

            val secondViewModel =
                LoginViewModel(
                    sessionManager = SessionManager(FakeAuthGateway()),
                    authCallbackErrors = sharedErrors,
                    googleAuthAvailabilityGateway = FakeGoogleAuthAvailabilityGateway(),
                )
            secondViewModel.uiState.test {
                assertEquals(LoginUiState.Idle, awaitItem())
                expectNoEvents()
            }
        }

    @Test
    fun `a pending auth callback error is cleared once the session is signed in`() =
        runTest {
            val fakeAuthGatewayForSession = FakeAuthGateway()
            val sharedErrors = AuthCallbackErrors()
            sharedErrors.publish(
                AuthCallbackError(AuthCallbackErrorKind.OTHER, "server_error", null),
            )

            LoginViewModel(
                sessionManager = SessionManager(fakeAuthGatewayForSession),
                authCallbackErrors = sharedErrors,
                googleAuthAvailabilityGateway = FakeGoogleAuthAvailabilityGateway(),
            )

            fakeAuthGatewayForSession.sessionState.value = SessionState.SignedIn(userId = "user-1")
            dispatcher.scheduler.advanceUntilIdle()

            assertEquals(null, sharedErrors.pending.value)
        }

    @Test
    fun `google sign-in availability reflects the gateway`() =
        runTest {
            val hiddenViewModel =
                LoginViewModel(
                    sessionManager = SessionManager(FakeAuthGateway()),
                    authCallbackErrors = AuthCallbackErrors(),
                    googleAuthAvailabilityGateway = FakeGoogleAuthAvailabilityGateway(enabled = false),
                )
            hiddenViewModel.googleSignInAvailable.test {
                assertEquals(true, awaitItem()) // default before the fetch resolves
                assertEquals(false, awaitItem())
            }
        }

    @Test
    fun `gate blocks when versionCode below min`() {
        assertTrue(isUpdateRequired(currentVersionCode = 1, minSupportedVersionCode = 2))
        assertFalse(isUpdateRequired(currentVersionCode = 2, minSupportedVersionCode = 2))
        assertFalse(isUpdateRequired(currentVersionCode = 3, minSupportedVersionCode = 2))
    }
}
