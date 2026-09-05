package app.mealsy.android.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import app.mealsy.android.BuildConfig
import app.mealsy.android.di.AppVersionCode
import app.mealsy.android.push.PushRegistrar
import app.mealsy.android.ui.chat.ChatScreen
import app.mealsy.android.ui.gate.UpdateRequiredScreen
import app.mealsy.android.ui.login.LoginScreen
import app.mealsy.data.api.MealsyApi
import app.mealsy.data.auth.SessionManager
import app.mealsy.data.auth.SessionState
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeout
import javax.inject.Inject

private const val APP_META_TIMEOUT_MS = 3_000L

private const val ROUTE_LOGIN = "login"
private const val ROUTE_CHAT = "chat"

/** Result of the startup version-gate check. */
sealed interface GateState {
    data object Checking : GateState
    data object Ready : GateState
    data object UpdateRequired : GateState
}

/** Returns true when the installed build is older than the backend's minimum supported version. */
fun isUpdateRequired(currentVersionCode: Int, minSupportedVersionCode: Int): Boolean =
    currentVersionCode < minSupportedVersionCode

/**
 * `currentVersionCode` is [BuildConfig.VERSION_CODE] in production, bound via [AppVersionCode]
 * in `app.mealsy.android.di.AppModule` since Hilt has no visibility into `BuildConfig`. Being a
 * constructor param (rather than reading BuildConfig directly) lets tests override it and make
 * the gate's fail-open/fail-closed branches plain-JVM-testable without Robolectric.
 */
@HiltViewModel
class AppNavViewModel @Inject constructor(
    private val api: MealsyApi,
    sessionManager: SessionManager,
    @AppVersionCode private val currentVersionCode: Int,
    private val pushRegistrar: PushRegistrar,
) : ViewModel() {

    val sessionState: StateFlow<SessionState> = sessionManager.sessionState

    private val _gateState = MutableStateFlow<GateState>(GateState.Checking)
    val gateState: StateFlow<GateState> = _gateState.asStateFlow()

    init {
        checkGate()
        observeSignIn()
    }

    /**
     * FCM registration (Task 9) needs a signed-in user (`POST /devices/register`
     * requires auth), so it's driven from [sessionState] here rather than at
     * app startup — this is the "sensible place" the task brief calls for,
     * chosen because [AppNavViewModel] already observes [sessionState] for
     * routing and outlives any single screen.
     */
    private fun observeSignIn() {
        viewModelScope.launch {
            sessionState.collect { state ->
                if (state is SessionState.SignedIn) {
                    pushRegistrar.ensureRegistered()
                }
            }
        }
    }

    private fun checkGate() {
        viewModelScope.launch {
            _gateState.value = try {
                val meta = withTimeout(APP_META_TIMEOUT_MS) { api.appMeta() }
                if (isUpdateRequired(currentVersionCode, meta.minSupportedVersionCode)) {
                    GateState.UpdateRequired
                } else {
                    GateState.Ready
                }
            } catch (exc: TimeoutCancellationException) {
                // 3s timeout — treat as a failed check, per the spec "failure = proceed".
                GateState.Ready
            } catch (exc: CancellationException) {
                throw exc
            } catch (exc: Exception) {
                // appMeta() unreachable/erroring — same "failure = proceed" contract.
                GateState.Ready
            }
        }
    }
}

/**
 * App-level navigation host.
 *
 * On startup, blocks on the version gate ([AppNavViewModel.gateState]); once
 * clear, routes between `login` and `chat` based on [SessionManager]'s
 * [SessionState] so a sign-in/out anywhere in the tree updates navigation.
 */
@Composable
fun AppNav(navController: NavHostController = rememberNavController()) {
    val viewModel: AppNavViewModel = hiltViewModel()
    val gateState by viewModel.gateState.collectAsStateWithLifecycle()

    when (gateState) {
        GateState.Checking -> {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
        }

        GateState.UpdateRequired -> UpdateRequiredScreen()

        GateState.Ready -> {
            val sessionState by viewModel.sessionState.collectAsStateWithLifecycle()

            if (sessionState == SessionState.Loading) {
                // Session status isn't known yet — avoid flashing LoginScreen under the
                // NavHost before the first real sessionState value arrives.
                Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator()
                }
            } else {
                NavHost(navController = navController, startDestination = ROUTE_LOGIN) {
                    composable(ROUTE_LOGIN) { LoginScreen() }
                    composable(ROUTE_CHAT) { ChatScreen() }
                }

                LaunchedEffect(sessionState) {
                    when (sessionState) {
                        is SessionState.SignedIn -> navController.navigate(ROUTE_CHAT) {
                            popUpTo(navController.graph.id) { inclusive = true }
                            launchSingleTop = true
                        }

                        SessionState.SignedOut -> navController.navigate(ROUTE_LOGIN) {
                            popUpTo(navController.graph.id) { inclusive = true }
                            launchSingleTop = true
                        }

                        SessionState.Loading -> Unit
                    }
                }
            }
        }
    }
}
