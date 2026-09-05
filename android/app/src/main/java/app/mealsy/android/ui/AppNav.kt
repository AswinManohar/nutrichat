package app.mealsy.android.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
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

@HiltViewModel
class AppNavViewModel @Inject constructor(
    private val api: MealsyApi,
    sessionManager: SessionManager,
) : ViewModel() {

    val sessionState: StateFlow<SessionState> = sessionManager.sessionState

    private val _gateState = MutableStateFlow<GateState>(GateState.Checking)
    val gateState: StateFlow<GateState> = _gateState.asStateFlow()

    init {
        viewModelScope.launch {
            _gateState.value = try {
                val meta = withTimeout(APP_META_TIMEOUT_MS) { api.appMeta() }
                if (isUpdateRequired(BuildConfig.VERSION_CODE, meta.minSupportedVersionCode)) {
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

            NavHost(navController = navController, startDestination = ROUTE_LOGIN) {
                composable(ROUTE_LOGIN) { LoginScreen() }
                composable(ROUTE_CHAT) { Text("Chat — coming in Task 6") }
            }

            LaunchedEffect(sessionState) {
                when (sessionState) {
                    is SessionState.SignedIn -> navController.navigate(ROUTE_CHAT) {
                        popUpTo(0)
                        launchSingleTop = true
                    }

                    SessionState.SignedOut -> navController.navigate(ROUTE_LOGIN) {
                        popUpTo(0)
                        launchSingleTop = true
                    }

                    SessionState.Loading -> Unit
                }
            }
        }
    }
}
